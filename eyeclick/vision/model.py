"""Red chica abierto/cerrado (eye_model.onnx), para cámaras en cualquier ángulo.  (SWE 1)

El detector clásico busca la pupila como la mancha oscura y redonda; falla con la
cámara de cabeza, con el iris cortado por el borde o fuera del cuadro (solo se ve lo
blanco del ojo). Esta red mira el frame entero y aprendió de ojo.mp4, ojo2.mp4 y
ojo3.mp4 (etiquetados a mano) con aumentos de cualquier rotación, espejo, zoom,
desplazamiento, brillo y color.

    logit(frame) -> número: > 0 se parece a abierto, < 0 a cerrado.
El corte exacto NO es 0: calibration.py lo pone entre los logits de los frames
abiertos y cerrados de la persona (ajusta luz, cara y montaje de la cámara).

Entrada del modelo: BGR reducido a IN_W x IN_H, 0..255 (la normalización va dentro).
Corre con onnxruntime (~1 ms por frame en CPU). Si no está el archivo o no carga,
available() es False y el detector usa el método clásico.
"""
import logging
import threading
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

MODEL_FILE = Path(__file__).parent / "eye_model.onnx"
IN_W, IN_H = 64, 48

_session = None
_failed = False
_lock = threading.Lock()


def _load():
    global _session, _failed
    with _lock:
        if _session is None and not _failed:
            try:
                import onnxruntime as ort
                opts = ort.SessionOptions()
                opts.intra_op_num_threads = 1       # un frame a la vez: más hilos no ayudan
                _session = ort.InferenceSession(str(MODEL_FILE), opts, providers=["CPUExecutionProvider"])
            except Exception:
                _failed = True
                log.warning("No se pudo cargar %s; se usa el detector clásico", MODEL_FILE, exc_info=True)
    return _session


def available():
    return MODEL_FILE.exists() and _load() is not None


def prepare(frame):
    """Frame BGR (o gris) de cualquier tamaño -> tensor (1, 3, IN_H, IN_W) float32."""
    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    small = cv2.resize(frame, (IN_W, IN_H), interpolation=cv2.INTER_AREA).astype(np.float32)
    return small.transpose(2, 0, 1)[None]


def logit(frame):
    """Qué tan abierto se ve el ojo (ver arriba). None si el modelo no está."""
    session = _load() if MODEL_FILE.exists() else None
    if session is None:
        return None
    return float(session.run(None, {"bgr": prepare(frame)})[0][0])
