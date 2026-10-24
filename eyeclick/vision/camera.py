"""Captura de frames.  (SWE 1)

Un hilo lee sin parar y guarda SOLO el último frame, así el detector nunca
procesa imágenes viejas. CameraSource y VideoFileSource tienen la misma
interfaz para que pipeline.py no sepa de dónde viene la imagen.

Interfaz:
    start(), stop(), latest() -> (frame BGR | None, t: float), fps: float

Si la cámara deja de entregar frames, latest() sigue devolviendo el último con
su t viejo; pipeline.py lo detecta y lo trata como 'lost'.

Herramientas para montar la cámara y grabar el video de prueba:
    python -m eyeclick.vision.camera --probe                        # índices, resolución y FPS reales
    python -m eyeclick.vision.camera --record ojo.mp4 --camera 1    # graba 2 min con vista previa

TODO (SWE 1):
- [ ] Conectar la cámara endoscópica; confirmar índice, resolución y FPS reales (>= 15)
      con --probe y poner el índice en config.CAMERA_INDEX.
- [ ] Grabar 2 minutos de video del ojo con --record.
"""
import argparse
import logging
import platform
import threading
import time

import cv2

from eyeclick.config import CAMERA_INDEX, FRAME_H, FRAME_W

log = logging.getLogger(__name__)

MIN_FPS = 15


def _backend():
    return cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY


def open_camera(index):
    """cv2.VideoCapture con el backend correcto y FRAME_W x FRAME_H, o None si no abre."""
    cap = cv2.VideoCapture(index, _backend())
    if not cap.isOpened():
        cap.release()
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
    return cap


class _LatestFrame:
    """Lo común a las dos fuentes: último frame con lock y un hilo lector."""

    def __init__(self):
        self.frame, self.t = None, 0.0
        self.fps = 0.0
        self.lock = threading.Lock()
        self._running = False
        self._thread = None
        self._cap = None

    def latest(self):
        with self.lock:
            return self.frame, self.t

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            if self._thread.is_alive():
                # cap.read() sigue bloqueado: liberar ahora puede tumbar el proceso
                log.warning("El hilo de captura no terminó; la cámara se libera al salir")
                return
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _launch(self, name):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=name, daemon=True)
        self._thread.start()

    def _store(self, frame):
        t = time.monotonic()
        with self.lock:
            self.frame, self.t = frame, t
        return t

    def _loop(self):
        raise NotImplementedError


class CameraSource(_LatestFrame):
    def __init__(self, index=CAMERA_INDEX):
        super().__init__()
        self.index = index

    def start(self):
        self._cap = open_camera(self.index)
        if self._cap is None:
            raise RuntimeError(f"No se pudo abrir la cámara {self.index} "
                               "(prueba: python -m eyeclick.vision.camera --probe)")
        self._launch("camera")

    def _loop(self):
        n, t_fps = 0, time.monotonic()
        while self._running:
            ok, frame = self._cap.read()
            if not ok:
                # desconectada o sin imagen: el pipeline verá el t viejo y dirá 'lost'
                if time.monotonic() - self.t > 1.0:
                    self.fps = 0.0
                time.sleep(0.01)
                continue
            t = self._store(frame)
            n += 1
            if t - t_fps >= 1.0:
                self.fps, n, t_fps = n / (t - t_fps), 0, t


class VideoFileSource(_LatestFrame):
    """Misma interfaz que CameraSource, pero lee un video grabado (--video ojo.mp4)."""

    def __init__(self, path):
        super().__init__()
        self.path = path

    def start(self):
        self._cap = cv2.VideoCapture(self.path)
        if not self._cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el video {self.path}")
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if 1 <= fps <= 240 else 30.0
        self._launch("video")

    def _loop(self):
        period = 1.0 / self.fps
        next_t = time.monotonic()
        while self._running:
            ok, frame = self._cap.read()
            if not ok:                      # fin del video: volver al inicio
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self._cap.read()
                if not ok:
                    log.error("No se pudo leer ningún frame de %s", self.path)
                    return
            self._store(frame)
            next_t += period
            delay = next_t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:                           # vamos atrasados: no acumular la deuda
                next_t = time.monotonic()


# --- herramientas de línea de comandos ---

def probe(max_index=5, frames=30):
    """Imprime qué índices abren, con su resolución y FPS reales."""
    for i in range(max_index):
        cap = open_camera(i)
        if cap is None:
            print(f"[{i}] no disponible")
            continue
        ok, frame = cap.read()
        if not ok:
            print(f"[{i}] abre pero no entrega imágenes")
            cap.release()
            continue
        t0, n = time.monotonic(), 0
        for _ in range(frames):
            n += cap.read()[0]
        fps = n / (time.monotonic() - t0)
        h, w = frame.shape[:2]
        slow = f"  <- menos de {MIN_FPS} FPS" if fps < MIN_FPS else ""
        print(f"[{i}] {w}x{h} a {fps:.1f} FPS{slow}")
        cap.release()


def record(index, path, seconds):
    """Graba la cámara a sus FPS reales, con vista previa (q = parar antes)."""
    cam = CameraSource(index)
    cam.start()
    try:
        time.sleep(2.0)                     # medir los FPS reales: el video se reproduce a ese ritmo
        frame, last_t = cam.latest()
        if frame is None:
            raise RuntimeError(f"La cámara {index} no entrega imágenes")
        fps = cam.fps or 30.0
        h, w = frame.shape[:2]
        out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        if not out.isOpened():
            raise RuntimeError(f"No se pudo crear {path}")
        print(f"Grabando {seconds:.0f} s a {fps:.1f} FPS ({w}x{h}) en {path}. q = parar")
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            frame, t = cam.latest()
            if t != last_t:
                last_t = t
                out.write(frame)
                cv2.imshow("grabando (q = parar)", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        out.release()
        print("Listo.")
    finally:
        cam.stop()
        cv2.destroyAllWindows()


def main():
    p = argparse.ArgumentParser(description="Herramientas de la cámara del ojo")
    p.add_argument("--probe", action="store_true", help="listar cámaras con resolución y FPS reales")
    p.add_argument("--record", metavar="RUTA", help="grabar video del ojo (p. ej. ojo.mp4)")
    p.add_argument("--camera", type=int, default=CAMERA_INDEX, metavar="N", help="índice para --record")
    p.add_argument("--seconds", type=float, default=120.0, help="duración de --record")
    args = p.parse_args()
    if args.record:
        record(args.camera, args.record, args.seconds)
    else:
        probe()


if __name__ == "__main__":
    main()
