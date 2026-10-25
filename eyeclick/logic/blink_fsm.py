"""Máquina de estados del parpadeo: duraciones -> eventos.  (SWE 1)

Recibe 'open' / 'closed' / 'lost' con su tiempo en cada frame y emite EyeEvents.
Un cambio abierto/cerrado solo cuenta si se repite FRAMES_TO_CHANGE frames
seguidos; el cierre empieza a contar desde el primero de esos frames.

No conoce la cámara: se prueba con secuencias inventadas (tests/test_blink_fsm.py)
y SWE 2 la reutiliza tal cual en sources/mock.py.

Decisiones:
- MIN_BLINK: todo cierre < LEFT_AT termina en CANCELLED, así que un parpadeo natural
  (< MIN_BLINK) nunca hace clic; entre MIN_BLINK y LEFT_AT hay un margen muerto que
  también cancela. MIN_BLINK solo lo usa el monitor para la barra.
- Un 'lost' corto (< LOST_FRAMES) con el ojo cerrado NO pausa el cierre: el tiempo
  sigue corriendo y los STAGE_* salen a su hora aunque caigan en esos frames.
- Más de DRAG_AT cerrado = arrastrar (STAGE_DRAG). Termina SIEMPRE con DRAG_END: al abrir,
  al perder el ojo (LOST_FRAMES) o con reset(); así el botón nunca se queda apretado.
"""
from eyeclick.config import DRAG_AT, FRAMES_TO_CHANGE, LEFT_AT, LOST_FRAMES, RIGHT_AT
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent


class BlinkFSM:
    def __init__(self, emit):
        self.emit = emit                # función que recibe un EyeEvent (bus.publish)
        self.closed = False
        self.t0 = 0.0                   # cuándo empezó el cierre
        self.stage = 0                  # 0 nada, 1 izquierdo, 2 derecho, 3 arrastrando, 4 terminado
        self.streak, self.streak_t = 0, 0.0
        self.lost_frames = 0

    def closed_for(self, t):
        """Segundos que lleva cerrado (para la barra de progreso de la EyeView)."""
        return t - self.t0 if self.closed else 0.0

    def reset(self, t):
        """Olvida el cierre en curso (p. ej. al recalibrar); si no había terminado, lo cancela."""
        if self.closed:
            self._abort(t)
        self.closed, self.stage = False, 0
        self.streak, self.lost_frames = 0, 0

    def update(self, status, t):
        if status == "lost":
            self.lost_frames += 1
            if self.lost_frames == LOST_FRAMES:
                if self.closed:
                    self._abort(t)
                self.emit(EyeEvent(E.EYE_LOST, t))
            if self.closed:
                self._tick(t)
            return
        self.lost_frames = 0

        now_closed = status == "closed"
        if now_closed != self.closed:
            if self.streak == 0:
                self.streak_t = t
            self.streak += 1
            if self.streak >= FRAMES_TO_CHANGE:
                self.closed, self.streak = now_closed, 0
                self._on_close() if now_closed else self._on_open()
        else:
            self.streak = 0
        if self.closed:
            self._tick(t)

    def _on_close(self):
        self.t0, self.stage = self.streak_t, 0
        self.emit(EyeEvent(E.EYE_CLOSED, self.t0))

    def _tick(self, t):
        d = t - self.t0
        if self.stage == 0 and d >= LEFT_AT:
            self.stage = 1
            self.emit(EyeEvent(E.STAGE_LEFT, t, d))
        elif self.stage == 1 and d >= RIGHT_AT:
            self.stage = 2
            self.emit(EyeEvent(E.STAGE_RIGHT, t, d))
        elif self.stage == 2 and d >= DRAG_AT:
            self.stage = 3
            self.emit(EyeEvent(E.STAGE_DRAG, t, d))

    def _abort(self, t):
        """Cierre que termina sin abrir el ojo: soltar si arrastraba, si no cancelar."""
        if self.stage == 3:
            self.emit(EyeEvent(E.DRAG_END, t, t - self.t0))
        elif self.stage != 4:
            self.emit(EyeEvent(E.CANCELLED, t, t - self.t0))
        self.stage = 4

    def _on_open(self):
        d = self.streak_t - self.t0
        if self.stage == 1:
            self.emit(EyeEvent(E.CLICK_LEFT, self.streak_t, d))
        elif self.stage == 2:
            self.emit(EyeEvent(E.CLICK_RIGHT, self.streak_t, d))
        elif self.stage == 3:
            self.emit(EyeEvent(E.DRAG_END, self.streak_t, d))
        elif self.stage == 0:
            self.emit(EyeEvent(E.CANCELLED, self.streak_t, d))
