"""Detección de la pupila -> 'open' / 'closed' / 'lost'.  (SWE 1)

La pupila es la mancha más oscura y redonda. Si aparece, el ojo está abierto;
si desaparece o se hace muy pequeña (la tapa el párpado), está cerrado.
Si la imagen es plana (cámara tapada, desenfocada o sin señal), es 'lost'.
OpenCV clásico, sin MediaPipe (la cámara está a 2-3 cm del ojo).

Pasos de find_pupil:
    1. Gris + GaussianBlur 7x7 (quita ruido y pestañas).             -> preprocess()
    2. Umbral inverso con thr (sale de calibración, se ajusta con el slider).
    3. Apertura morfológica (borra puntitos y pestañas delgadas).
    4. Contorno más grande con área razonable y circularidad > 0.5.  -> segment()
    5. Comparar su área con open_area de la calibración.             -> classify()

min_area/max_area son relativos a calib.open_area (area_limits) para que pestañas
y sombras no pasen por pupila. La circularidad usa el perímetro de la envolvente
convexa: un reflejo del LED que muerde el borde de la pupila no la descarta,
pero una pestaña larga sí.

Plan B: USE_STD_ONLY = True ignora la pupila y clasifica solo con la desviación
de gris (un ojo cerrado se ve más plano), con open_std/closed_std de la calibración.
"""
import math
from dataclasses import dataclass

import cv2
import numpy as np

KERNEL = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
MIN_CIRCULARITY = 0.5
CLOSED_AREA_RATIO = 0.35    # área < 35 % de la calibrada = cerrado
USE_STD_ONLY = False        # Plan B


@dataclass
class EyeState:
    status: str                         # 'open', 'closed' o 'lost'
    area: float = 0.0
    center: tuple | None = None
    contour: np.ndarray | None = None   # para que annotate.py lo dibuje
    mask: np.ndarray | None = None      # imagen binaria del umbral (miniatura en el monitor)


def preprocess(frame):
    """Paso 1: BGR (o gris) -> gris suavizado. calibration.py guarda esto."""
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (7, 7), 0)


def area_limits(open_area, shape):
    """(min_area, max_area) de la pupila. Sin calibrar (open_area <= 0), relativos al frame."""
    n = shape[0] * shape[1]
    if open_area <= 0:
        return 0.0007 * n, 0.4 * n
    return max(20.0, 0.10 * open_area), min(0.6 * n, 4.0 * open_area)


def segment(gray, thr, min_area, max_area):
    """Pasos 2-4 sobre un gris ya suavizado. Devuelve (contorno | None, área, máscara)."""
    _, mask = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY_INV)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best, best_area = None, 0.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area or area <= best_area:
            continue
        perimeter = cv2.arcLength(cv2.convexHull(c), True)
        if perimeter and 4 * math.pi * area / perimeter ** 2 >= MIN_CIRCULARITY:
            best, best_area = c, area
    return best, best_area, mask


def find_pupil(frame, thr, min_area=200, max_area=40000):
    """Devuelve (contorno | None, área, gris, máscara)."""
    gray = preprocess(frame)
    contour, area, mask = segment(gray, thr, min_area, max_area)
    return contour, area, gray, mask


def classify(frame, calib) -> EyeState:
    """calib es una Calibration (thr, open_area, min_std)."""
    if frame is None:
        return EyeState("lost")
    gray = preprocess(frame)
    if USE_STD_ONLY:
        return _classify_std(gray, calib)
    contour, area, mask = segment(gray, calib.thr, *area_limits(calib.open_area, gray.shape))
    if gray.std() < calib.min_std:
        return EyeState("lost", mask=mask)
    if contour is None or area < CLOSED_AREA_RATIO * calib.open_area:
        return EyeState("closed", area, contour=contour, mask=mask)
    m = cv2.moments(contour)
    center = (m["m10"] / m["m00"], m["m01"] / m["m00"]) if m["m00"] else None
    return EyeState("open", area, center, contour, mask)


def _classify_std(gray, calib):
    std = float(gray.std())
    if std < calib.min_std:
        return EyeState("lost")
    cut = (calib.open_std + calib.closed_std) / 2
    return EyeState("open" if std >= cut else "closed")
