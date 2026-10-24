"""Fuente real del ojo: frame -> detector -> FSM -> bus + EyeView.  (SWE 1)

Cumple la "interfaz de fuente" (la misma que sources/mock.py):
    start(), stop(), latest_view() -> EyeView | None,
    recalibrate(), set_threshold(valor)

Su hilo repite en cada frame NUEVO (mismo t = saltar):
    1. Tomar el último frame de la cámara o del video.
    2. Si está calibrando: Calibrator.feed(); al terminar publicar CALIBRATED.
    3. Clasificarlo con detector.classify().
    4. Pasar el estado a BlinkFSM.update() (publica eventos en el bus).
    5. Dibujar con annotate() y guardar la EyeView como último valor (con lock).

recalibrate() y set_threshold() se llaman desde el hilo principal (botones del
monitor): solo dejan una marca, y el hilo del pipeline aplica el cambio antes
del siguiente frame.

TODO (SWE 1):
- [ ] start(): arrancar la cámara/video, cargar calib.json o calibrar, lanzar el hilo.
- [ ] _loop(): pasos 1-5 de arriba.
- [ ] Aplicar las marcas _want_recalibrate / _want_thr al inicio de cada vuelta.
- [ ] Durante la calibración, poner Calibrator.message en EyeView.message.
- [ ] stop(): parar el hilo y la cámara.
"""
import threading

from eyeclick.events import EyeView
from eyeclick.logic.blink_fsm import BlinkFSM


class PipelineSource:
    def __init__(self, camera, publish):
        """camera: CameraSource o VideoFileSource. publish: bus.publish."""
        self.camera = camera
        self.publish = publish
        self.fsm = BlinkFSM(publish)
        self.calib = None
        self._view: EyeView | None = None
        self._lock = threading.Lock()
        self._want_recalibrate = False
        self._want_thr: int | None = None
        self._running = False

    # --- interfaz de fuente ---
    def start(self):
        # TODO (SWE 1)
        raise NotImplementedError

    def stop(self):
        # TODO (SWE 1): también self.camera.stop()
        self._running = False

    def latest_view(self) -> EyeView | None:
        with self._lock:
            return self._view

    def recalibrate(self):
        self._want_recalibrate = True

    def set_threshold(self, value):
        self._want_thr = int(value)

    # --- hilo ---
    def _loop(self):
        # TODO (SWE 1)
        raise NotImplementedError
