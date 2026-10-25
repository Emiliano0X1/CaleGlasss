"""Dibujo sobre el frame de lo que detectó el detector.  (SWE 1)

Devuelve una copia reducida a VIEW_W x VIEW_H con lo detectado encima.
El monitor (SWE 2) solo la muestra.

    open   -> contorno verde, elipse ajustada y punto en el centro
    closed -> contorno amarillo si queda algo de pupila; si no, borde amarillo
    lost   -> borde rojo grueso y el texto "SIN OJO"
    abajo  -> texto pequeño: área vs calibrada y umbral actual
    mask   -> miniatura de la imagen binaria (el monitor la muestra u oculta)

Es rápido: reduce primero (cv2.resize ya es la copia) y dibuja sobre la imagen
reducida, escalando las coordenadas del contorno (vienen en la resolución de
trabajo del detector, detector.work_size).
"""
import cv2
import numpy as np

from eyeclick.config import VIEW_H, VIEW_W
from eyeclick.vision.detector import work_size

GREEN, YELLOW, RED = (0, 200, 0), (0, 200, 255), (0, 0, 220)   # BGR
WHITE, BLACK = (255, 255, 255), (0, 0, 0)
MASK_W, MASK_H = 80, 60
FONT = cv2.FONT_HERSHEY_SIMPLEX
AA = cv2.LINE_AA


def annotate(frame, state, calib):
    """frame BGR completo + EyeState + Calibration -> frame BGR 320x240 anotado.
    frame=None (no llegan imágenes) dibuja sobre negro."""
    if frame is None:
        view = np.zeros((VIEW_H, VIEW_W, 3), np.uint8)
        scale = np.array([1.0, 1.0], np.float32)
    else:
        w, h = work_size(frame.shape)
        scale = np.array([VIEW_W / w, VIEW_H / h], np.float32)
        view = cv2.resize(frame, (VIEW_W, VIEW_H), interpolation=cv2.INTER_AREA)
        if view.ndim == 2:
            view = cv2.cvtColor(view, cv2.COLOR_GRAY2BGR)

    if state.status == "lost":
        cv2.rectangle(view, (0, 0), (VIEW_W - 1, VIEW_H - 1), RED, 8)
        _text_center(view, "NO EYE", RED)
    else:
        is_open = state.status == "open"
        color = GREEN if is_open else YELLOW
        if state.contour is not None:
            pts = state.contour.reshape(-1, 2).astype(np.float32) * scale
            cv2.polylines(view, [pts.astype(np.int32)], True, color, 1, AA)
            if is_open and len(pts) >= 5:
                cv2.ellipse(view, cv2.fitEllipse(pts), color, 1, AA)
        elif not is_open:
            cv2.rectangle(view, (0, 0), (VIEW_W - 1, VIEW_H - 1), YELLOW, 4)
        if is_open and state.center is not None:
            cx, cy = state.center[0] * scale[0], state.center[1] * scale[1]
            cv2.circle(view, (round(cx), round(cy)), 3, color, -1, AA)

    if state.score is not None:
        _text(view, f"model {state.score:+.1f}  cut {calib.model_cut:+.1f}", (6, VIEW_H - 8))
    else:
        _text(view, f"area {state.area:.0f}/{calib.open_area:.0f}  thr {calib.thr}", (6, VIEW_H - 8))
    return view


def small_mask(mask):
    """Máscara binaria -> miniatura, o None si no hay máscara."""
    if mask is None:
        return None
    return cv2.resize(mask, (MASK_W, MASK_H), interpolation=cv2.INTER_NEAREST)


def _text(img, s, org, color=WHITE, scale=0.4):
    cv2.putText(img, s, org, FONT, scale, BLACK, 3, AA)    # contorno para leerse sobre cualquier fondo
    cv2.putText(img, s, org, FONT, scale, color, 1, AA)


def _text_center(img, s, color):
    (tw, th), _ = cv2.getTextSize(s, FONT, 1.0, 2)
    org = ((VIEW_W - tw) // 2, (VIEW_H + th) // 2)
    cv2.putText(img, s, org, FONT, 1.0, BLACK, 5, AA)
    cv2.putText(img, s, org, FONT, 1.0, color, 2, AA)
