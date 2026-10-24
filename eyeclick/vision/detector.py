"""Detección de la pupila -> 'open' / 'closed' / 'lost'.  (SWE 1)

La pupila es la mancha más oscura y redonda. Si aparece, el ojo está abierto;
si desaparece o se hace muy pequeña (la tapa el párpado), está cerrado.
OpenCV clásico, sin MediaPipe (la cámara está a 2-3 cm del ojo).

Pasos de find_pupil:
    1. Gris + GaussianBlur 7x7 (quita ruido y pestañas).
    2. Umbral inverso con thr (sale de calibración, se ajusta con el slider).
    3. Apertura morfológica (borra puntitos y pestañas delgadas).
    4. Contorno más grande con área razonable y circularidad > 0.5.
    5. Comparar su área con open_area de la calibración.

TODO (SWE 1):
- [ ] Implementar find_pupil (ver código de referencia en el plan técnico).
- [ ] Implementar classify con la regla de 'lost' por gray.std() < calib.min_std.
- [ ] Afinar min_area/max_area relativos a calib.open_area (pestañas vistas como pupila).
- [ ] Plan B: si la pupila falla, clasificar solo con la desviación de gris.
"""
from dataclasses import dataclass

import cv2
import numpy as np

KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
MIN_CIRCULARITY = 0.5
CLOSED_AREA_RATIO = 0.35    # área < 35 % de la calibrada = cerrado


@dataclass
class EyeState:
    status: str                         # 'open', 'closed' o 'lost'
    area: float = 0.0
    center: tuple | None = None
    contour: np.ndarray | None = None   # para que annotate.py lo dibuje
    mask: np.ndarray | None = None      # imagen binaria del umbral (miniatura en el monitor)


def find_pupil(frame, thr, min_area=200, max_area=40000):
    """Devuelve (contorno | None, área, gris, máscara)."""
    # TODO (SWE 1): pasos 1-4 de arriba.
    raise NotImplementedError


def classify(frame, calib) -> EyeState:
    """calib es una Calibration (thr, open_area, min_std)."""
    if frame is None:
        return EyeState("lost")
    # TODO (SWE 1): find_pupil -> 'lost' si la imagen es plana, 'closed' si no hay pupila
    #               o area < CLOSED_AREA_RATIO * calib.open_area, si no 'open' con su centro.
    raise NotImplementedError
