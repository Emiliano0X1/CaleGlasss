"""Clics del sistema operativo.  (SWE 2, suscriptor del bus)

El giroscopio (ESP32 como mouse BLE) sigue moviendo el cursor mientras el ojo
está cerrado. Por eso:
    EYE_CLOSED            -> guardar self.mouse.position
    CLICK_LEFT / RIGHT    -> regresar el cursor a la posición guardada y hacer clic
Respeta CLICK_COOLDOWN entre clics y no hace nada si está en pausa.

En Mac: dar permisos de Accesibilidad y Monitoreo de entrada a la terminal / VS Code.
Si no, el cursor no se mueve y NO hay error.

TODO (SWE 2):
- [ ] handle(): EYE_CLOSED guarda posición; CLICK_* aplica cooldown, mueve y hace clic.
- [ ] toggle_pause() (F9 y botón del monitor).
- [ ] Probar con python run.py --mock (F8).
"""
from pynput.mouse import Button, Controller  # noqa: F401

from eyeclick.config import CLICK_COOLDOWN  # noqa: F401
from eyeclick.events import EventType as E

TYPES = {E.EYE_CLOSED, E.CLICK_LEFT, E.CLICK_RIGHT}   # para bus.subscribe


class MouseActions:
    def __init__(self):
        self.mouse = Controller()
        self.saved = None
        self.last_click = 0.0
        self.paused = False

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused

    def handle(self, ev):
        # TODO (SWE 2)
        raise NotImplementedError
