"""Clics del sistema operativo.  (SWE 2, suscriptor del bus)

El giroscopio (ESP32 "Calestick" como mouse BLE, firmware/Calemouse) sigue moviendo
el cursor mientras el ojo está cerrado. Por eso:
    EYE_CLOSED            -> guardar self.mouse.position
    CLICK_LEFT / RIGHT    -> clic en la posición guardada y DEVOLVER el cursor a donde
                             lo dejó el giroscopio (si no, el cursor "salta" solo)
    CANCELLED             -> olvidar la posición guardada
    STAGE_DRAG (3 s)      -> apretar el botón izquierdo en la posición guardada; con el
                             ojo cerrado la cabeza arrastra
    DRAG_END              -> soltar donde esté el cursor (abrió el ojo o se perdió)
Respeta CLICK_COOLDOWN entre clics y no hace nada si está en pausa.

Doble clic: dos clics izquierdos en menos de DOUBLE_WINDOW y a menos de DOUBLE_RADIUS
px. Windows solo junta dos clics separados por ~0.5 s y dos parpadeos tardan más, así
que el segundo parpadeo manda un doble clic real (click(botón, 2)) donde fue el primero.

Arrastrar (botón Drag del monitor o F10), en tres pasos:
    toggle_drag()        -> drag = "armed": el próximo parpadeo izquierdo agarra
    CLICK_LEFT           -> press() en la posición guardada, drag = "holding";
                            el giroscopio mueve el cursor con el botón apretado
    CLICK_LEFT           -> release() en la posición guardada, drag = None
Un clic derecho, la pausa o toggle_drag() a mitad del arrastre lo cancelan (si el
botón estaba apretado, se suelta donde está el cursor). Nunca queda apretado.

on_action(texto) avisa lo que pasó ("double click ✓", "grabbed"...) para el monitor
y el overlay; app.py lo aplica después del reparto de eventos.

intercept(ev): si devuelve True, ese CLICK_* no se hace. app.py lo usa para que, con un
dictado en preview, el parpadeo confirme/descarte sin hacer clic (el foco no se mueve).

Un clic solo se hace si su EYE_CLOSED llegó sin pausa (hay posición guardada).
Así, pausar a mitad de un cierre y quitar la pausa antes de abrir no hace clic.

toggle_pause() / set_paused() pueden llamarse desde otro hilo (F9 llega por el
listener de pynput): solo cambian un booleano.

En Mac: dar permisos de Accesibilidad y Monitoreo de entrada a la terminal / VS Code.
Si no, el cursor no se mueve y NO hay error.

TODO (SWE 2):
- [x] handle(): EYE_CLOSED guarda posición; CLICK_* aplica cooldown, mueve y hace clic.
- [x] toggle_pause() (F9 y botón del monitor; conectado en app.py).
- [ ] Probar con python run.py --mock (F8) cuando estén bus.py y sources/mock.py.
"""
import logging

from eyeclick.config import CLICK_COOLDOWN, DOUBLE_RADIUS, DOUBLE_WINDOW
from eyeclick.events import EventType as E

log = logging.getLogger(__name__)

TYPES = {E.EYE_CLOSED, E.CLICK_LEFT, E.CLICK_RIGHT, E.CANCELLED, E.STAGE_DRAG, E.DRAG_END}


class MouseActions:
    def __init__(self, controller=None, buttons=None, on_action=None):
        """controller y buttons=(izquierdo, derecho) se inyectan en las pruebas."""
        if controller is None or buttons is None:
            from pynput.mouse import Button, Controller   # aquí y no arriba: las pruebas no necesitan pynput
            controller = controller or Controller()
            buttons = buttons or (Button.left, Button.right)
        self.mouse = controller
        self.left_button, self.right_button = buttons
        self.saved = None
        self.last_click = None
        self.paused = False
        self.drag = None            # None, "armed" o "holding" (botón Drag / F10)
        self.eye_drag = False       # arrastre con el ojo cerrado más de DRAG_AT
        self.last_left = None       # (t, posición) del último clic izquierdo, para el doble clic
        self.on_action = on_action or (lambda text: None)
        self.intercept = None       # intercept(ev) -> True: ese clic no se hace (lo usa app.py)

    def toggle_drag(self):
        """None -> armed; armed o holding -> cancelar. Devuelve el estado nuevo."""
        if self.drag is None:
            if not self.paused:
                self.drag = "armed"
                self.on_action("drag: blink to grab")
        else:
            self._cancel_drag()
        return self.drag

    def _cancel_drag(self):
        if self.drag == "holding":
            self.mouse.release(self.left_button)
        if self.drag is not None:
            self.drag = None
            self.on_action("drag cancelled")

    def toggle_pause(self):
        return self.set_paused(not self.paused)

    def set_paused(self, paused):
        self.paused = paused
        if paused:
            self.saved = None       # un cierre en curso ya no debe terminar en clic
            self._cancel_drag()
            self._end_eye_drag()
        log.info("Clics %s", "en pausa" if paused else "activos")
        return self.paused

    def handle(self, ev):
        if self.paused:
            return
        if ev.type == E.EYE_CLOSED:
            self.saved = self.mouse.position
        elif ev.type == E.CANCELLED:
            self.saved = None
        elif ev.type == E.STAGE_DRAG:
            self._start_eye_drag()
        elif ev.type == E.DRAG_END:
            if self._end_eye_drag():
                self.last_click = ev.t
                self.on_action("dropped ✓")
        elif ev.type in (E.CLICK_LEFT, E.CLICK_RIGHT):
            if self.intercept is not None and self.intercept(ev):
                self.saved = None       # el parpadeo era para otra cosa (confirmar un dictado)
                return
            self._click(ev)

    def _click(self, ev):
        saved, self.saved = self.saved, None
        if saved is None:
            return
        if self.last_click is not None and ev.t - self.last_click < CLICK_COOLDOWN:
            log.info("Clic ignorado por cooldown (%.2f s)", ev.t - self.last_click)
            return
        self.last_click = ev.t
        current = self.mouse.position
        if ev.type == E.CLICK_RIGHT:
            if self.drag is not None:
                self._cancel_drag()         # el clic derecho solo cancela el arrastre
                return
            self._at(saved, current, lambda: self.mouse.click(self.right_button))
        elif self.drag == "armed":
            self.drag = "holding"
            self._at(saved, current, lambda: self.mouse.press(self.left_button))
            self.on_action("grabbed")
        elif self.drag == "holding":
            self.drag = None
            self._at(saved, current, lambda: self.mouse.release(self.left_button))
            self.on_action("dropped ✓")
        elif self._is_double(ev.t, saved):
            first = self.last_left[1]
            self.last_left = None       # un tercer parpadeo empieza de nuevo
            self._at(first, current, lambda: self.mouse.click(self.left_button, 2))
            self.on_action("double click ✓")
        else:
            self.last_left = (ev.t, saved)
            self._at(saved, current, lambda: self.mouse.click(self.left_button))

    def _start_eye_drag(self):
        saved, self.saved = self.saved, None
        if saved is None or self.drag is not None:
            return                  # cierre que empezó en pausa, o ya hay un arrastre con Drag/F10
        self.eye_drag = True
        self._at(saved, self.mouse.position, lambda: self.mouse.press(self.left_button))
        self.on_action("dragging")

    def _end_eye_drag(self):
        if not self.eye_drag:
            return False
        self.eye_drag = False
        self.mouse.release(self.left_button)    # donde quedó el cursor: ahí se suelta
        return True

    def _is_double(self, t, pos):
        if self.last_left is None or t - self.last_left[0] > DOUBLE_WINDOW:
            return False
        (x1, y1), (x2, y2) = self.last_left[1], pos
        return (x1 - x2) ** 2 + (y1 - y2) ** 2 <= DOUBLE_RADIUS ** 2

    def _at(self, pos, back, action):
        """Hace action con el cursor en pos y lo devuelve a back (donde lo dejó el giroscopio).
        Con el botón apretado, volver a back también arrastra hasta ahí."""
        self.mouse.position = pos
        action()
        self.mouse.position = back
