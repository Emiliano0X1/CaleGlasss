"""Contrato entre SWE 1 y SWE 2. Se escribe juntos al inicio (15 min).

SWE 1 solo PRODUCE estos eventos y la EyeView; SWE 2 solo los CONSUME.
Nadie cambia este archivo sin avisar al otro.

Secuencias típicas:
    clic derecho:       EYE_CLOSED -> STAGE_LEFT -> STAGE_RIGHT -> CLICK_RIGHT
    parpadeo natural:   EYE_CLOSED -> CANCELLED
"""
from dataclasses import dataclass, field
from enum import Enum
import time

import numpy as np


class EventType(Enum):
    EYE_CLOSED = "eye_closed"    # empezó un cierre (SWE 2 guarda la posición del cursor)
    STAGE_LEFT = "stage_left"    # lleva 0.5 s cerrado: si abre ahora es clic izquierdo (bip 1)
    STAGE_RIGHT = "stage_right"  # lleva 1.2 s cerrado: si abre ahora es clic derecho (bip 2)
    CLICK_LEFT = "click_left"    # abrió entre 0.5 y 1.2 s
    CLICK_RIGHT = "click_right"  # abrió entre 1.2 y 3.0 s
    CANCELLED = "cancelled"      # parpadeo natural, más de 3 s, o se perdió la imagen
    EYE_LOST = "eye_lost"        # la cámara no ve bien el ojo (mal enfoque, se movió)
    CALIBRATED = "calibrated"    # terminó la calibración, ya se puede usar


@dataclass
class EyeEvent:
    type: EventType
    t: float = field(default_factory=time.monotonic)
    duration: float = 0.0        # segundos que el ojo estuvo cerrado (en CLICK_* y CANCELLED)


@dataclass
class EyeView:
    """Lo que el detector ve en un frame. NO va por la cola de eventos:
    la fuente la guarda como "último valor" con un lock y el monitor la lee
    con latest_view(). Si el monitor se atrasa, se salta frames."""
    frame: np.ndarray                   # imagen ya anotada, 320x240 BGR
    status: str = "open"                # 'open', 'closed' o 'lost'
    mask: np.ndarray | None = None      # miniatura binaria del umbral, o None
    closed_for: float = 0.0             # segundos que lleva cerrado (barra de progreso)
    pupil_area: float = 0.0             # área actual de la pupila
    open_area: float = 0.0              # área calibrada con el ojo abierto
    thr: int = 0                        # umbral actual (posición del slider)
    fps: float = 0.0                    # FPS reales de la cámara
    message: str = ""                   # instrucción de calibración ("Mantén el ojo abierto"...)
    t: float = field(default_factory=time.monotonic)  # para detectar imagen congelada
