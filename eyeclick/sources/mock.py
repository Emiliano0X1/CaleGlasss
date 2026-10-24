"""Simulador del ojo: F8 sostenida = ojo cerrado, F9 = pausa.  (SWE 2)

Cumple la MISMA interfaz de fuente que vision/pipeline.py:
    start(), stop(), latest_view() -> EyeView | None,
    recalibrate(), set_threshold(valor)

Un hilo alimenta la misma BlinkFSM de SWE 1 60 veces por segundo, así los eventos
son idénticos a los reales. latest_view() devuelve una EyeView falsa (imagen gris
con el estado escrito) para poder construir el monitor sin cámara.

TODO (SWE 2):
- [ ] keyboard.Listener de pynput: F8 press/release -> self._closed; F9 -> on_pause_toggle().
- [ ] Hilo a 60 Hz: fsm.update('closed'/'open', time.monotonic()) y armar la EyeView falsa
      (np.full((240, 320, 3), 80, np.uint8) + cv2.putText con el estado y closed_for).
- [ ] recalibrate(): publicar CALIBRATED tras ~1 s para probar el flujo del monitor.
- [ ] set_threshold(): guardar el valor y reflejarlo en EyeView.thr.
- [ ] stop(): parar el listener y el hilo.
"""
import threading

from eyeclick.events import EyeView
from eyeclick.logic.blink_fsm import BlinkFSM

HZ = 60


class MockSource:
    def __init__(self, publish, on_pause_toggle=lambda: None):
        self.publish = publish
        self.on_pause_toggle = on_pause_toggle
        self.fsm = BlinkFSM(publish)
        self._closed = False
        self._thr = 50
        self._view: EyeView | None = None
        self._lock = threading.Lock()
        self._running = False

    def start(self):
        # TODO (SWE 2)
        raise NotImplementedError

    def stop(self):
        # TODO (SWE 2)
        self._running = False

    def latest_view(self) -> EyeView | None:
        with self._lock:
            return self._view

    def recalibrate(self):
        # TODO (SWE 2)
        pass

    def set_threshold(self, value):
        self._thr = int(value)
