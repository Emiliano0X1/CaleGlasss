"""Dibujo sobre el frame de lo que detectó el detector.  (SWE 1)

Devuelve una copia reducida a VIEW_W x VIEW_H con lo detectado encima.
El monitor (SWE 2) solo la muestra.

    open   -> contorno verde, elipse ajustada y punto en el centro
    closed -> contorno amarillo si queda algo de pupila; si no, borde amarillo
    lost   -> borde rojo grueso y el texto "SIN OJO"
    abajo  -> texto pequeño: área vs calibrada y umbral actual
    mask   -> miniatura de la imagen binaria (el monitor la muestra u oculta)

Tiene que ser rápido: reducir primero, dibujar sobre la imagen reducida
(escalando las coordenadas del contorno) y no copiar de más.

TODO (SWE 1):
- [ ] Implementar annotate() con los casos de arriba.
- [ ] Implementar small_mask() (miniatura de la máscara, p. ej. 80x60).
"""
import cv2  # noqa: F401

from eyeclick.config import VIEW_H, VIEW_W  # noqa: F401

GREEN, YELLOW, RED = (0, 200, 0), (0, 200, 255), (0, 0, 220)   # BGR


def annotate(frame, state, calib):
    """frame BGR completo + EyeState + Calibration -> frame BGR 320x240 anotado."""
    # TODO (SWE 1)
    raise NotImplementedError


def small_mask(mask):
    """Máscara binaria -> miniatura, o None si no hay máscara."""
    # TODO (SWE 1)
    raise NotImplementedError
