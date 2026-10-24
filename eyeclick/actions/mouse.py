"""Clics del sistema operativo.  (SWE 2, suscriptor del bus)

El giroscopio (ESP32 como mouse BLE) sigue moviendo el cursor mientras el ojo
está cerrado. Por eso:
    EYE_CLOSED            -> guardar self.mouse.position
    CLICK_LEFT / RIGHT    -> regresar el cursor a la posición guardada y hacer clic
    CANCELLED             -> olvidar la posición guardada
Respeta CLICK_COOLDOWN entre clics y no hace nada si está en pausa.

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

from eyeclick.config import CLICK_COOLDOWN
from eyeclick.events import EventType as E

log = logging.getLogger(__name__)

TYPES = {E.EYE_CLOSED, E.CLICK_LEFT, E.CLICK_RIGHT, E.CANCELLED}   # para bus.subscribe


class MouseActions:
    def __init__(self, controller=None, buttons=None):
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

    def toggle_pause(self):
        return self.set_paused(not self.paused)

    def set_paused(self, paused):
        self.paused = paused
        if paused:
            self.saved = None       # un cierre en curso ya no debe terminar en clic
        log.info("Clics %s", "en pausa" if paused else "activos")
        return self.paused

    def handle(self, ev):
        if self.paused:
            return
        if ev.type == E.EYE_CLOSED:
            self.saved = self.mouse.position
        elif ev.type == E.CANCELLED:
            self.saved = None
        elif ev.type in (E.CLICK_LEFT, E.CLICK_RIGHT):
            self._click(ev)

    def _click(self, ev):
        saved, self.saved = self.saved, None
        if saved is None:
            return
        if self.last_click is not None and ev.t - self.last_click < CLICK_COOLDOWN:
            log.info("Clic ignorado por cooldown (%.2f s)", ev.t - self.last_click)
            return
        self.mouse.position = saved
        self.mouse.click(self.left_button if ev.type == E.CLICK_LEFT else self.right_button)
        self.last_click = ev.t
