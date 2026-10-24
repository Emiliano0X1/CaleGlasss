"""Captura de frames.  (SWE 1)

Un hilo lee sin parar y guarda SOLO el último frame, así el detector nunca
procesa imágenes viejas. CameraSource y VideoFileSource tienen la misma
interfaz para que pipeline.py no sepa de dónde viene la imagen.

Interfaz:
    start(), stop(), latest() -> (frame BGR | None, t: float), fps: float

TODO (SWE 1):
- [ ] Conectar la cámara endoscópica; confirmar índice, resolución y FPS reales (>= 15).
- [ ] CameraSource: CAP_DSHOW en Windows, CAP_ANY en Mac; pedir FRAME_W x FRAME_H.
- [ ] CameraSource: hilo daemon que guarda el último frame + time.monotonic() con lock.
- [ ] Medir los FPS reales y exponerlos en self.fps.
- [ ] VideoFileSource: leer un .mp4 al ritmo de su FPS original y repetir en bucle.
- [ ] stop(): terminar el hilo y liberar cap.release().
"""
import platform
import threading
import time  # noqa: F401

import cv2

from eyeclick.config import CAMERA_INDEX, FRAME_H, FRAME_W  # noqa: F401


class CameraSource:
    def __init__(self, index=CAMERA_INDEX):
        self.index = index
        self.frame, self.t = None, 0.0
        self.fps = 0.0
        self.lock = threading.Lock()
        self._running = False

    def start(self):
        # TODO (SWE 1): abrir cv2.VideoCapture(self.index, backend), fijar tamaño
        #               y lanzar self._loop en un hilo daemon.
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY  # noqa: F841
        raise NotImplementedError

    def _loop(self):
        # TODO (SWE 1): while self._running: leer, guardar (frame, t) con lock, actualizar fps.
        raise NotImplementedError

    def latest(self):
        with self.lock:
            return self.frame, self.t

    def stop(self):
        # TODO (SWE 1): esperar al hilo y liberar la cámara.
        self._running = False


class VideoFileSource:
    """Misma interfaz que CameraSource, pero lee un video grabado (--video ojo.mp4)."""

    def __init__(self, path):
        self.path = path
        self.frame, self.t = None, 0.0
        self.fps = 0.0
        self.lock = threading.Lock()
        self._running = False

    def start(self):
        # TODO (SWE 1): abrir el video y lanzar un hilo que respete su FPS (sleep 1/fps)
        #               y vuelva al inicio al terminar.
        raise NotImplementedError

    def latest(self):
        with self.lock:
            return self.frame, self.t

    def stop(self):
        self._running = False
