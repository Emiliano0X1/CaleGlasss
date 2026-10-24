"""Detección de la pupila -> 'open' / 'closed' / 'lost'.  (SWE 1)

La pupila (con el iris, si es oscuro) es la mancha más oscura y redonda. Si aparece,
el ojo está abierto; si desaparece o se hace muy pequeña (la tapa el párpado), está
cerrado. Si la imagen es plana (cámara tapada, desenfocada o sin señal), es 'lost'.
OpenCV clásico, sin MediaPipe (la cámara está a 2-3 cm del ojo).

Pasos (detect):
    1. Gris, reducido a WORK_W de ancho y GaussianBlur 5x5.         -> preprocess()
       A 320x240 todo es ~4x más rápido que a 640x480 (importa en la Raspberry).
    2. Umbral inverso con thr ESCALADO por el brillo del frame: thr está medido con
       el brillo de la calibración (ref_level); si la cámara ajusta la exposición,
       el umbral la sigue.                                            -> effective_thr()
    3. Rellenar huecos (reflejos del LED dentro de la pupila).
    4. Apertura morfológica con un kernel de ~1/4 del radio de la pupila: corta las
       pestañas y el párpado que se pegan al iris (con 5x5 fijo el blob se comía la ceja).
    5. Contorno más grande con área razonable, circularidad > 0.5 y que no esté muy
       por encima del centro calibrado (eso es la ceja). Si no es redondo porque el
       iris quedó pegado a la línea de pestañas (forma de "sombrero", típico cuando el
       párpado tapa la parte de arriba del iris), se recorta a su círculo inscrito y
       se vuelve a evaluar, solo si el círculo conserva buena parte del blob, no toca
       el borde y está cerca del centro calibrado (si no, es una sombra).  -> _rescue()
    6. Comparar su área con open_area de la calibración.             -> classify()
    7. Solo para dibujar: recortar el blob a su círculo inscrito (x REFINE), así el
       contorno del monitor no incluye pestañas o ceja pegadas al iris.  -> refine()
       (Clasificar con el blob recortado salió peor: el radio inscrito es sensible
       a reflejos y al párpado.)

Coordenadas (contour, center, calib.cx/cy) y áreas están en la resolución de
trabajo (work_size), no en la del frame original.

Plan B: USE_STD_ONLY = True ignora la pupila y clasifica solo con la desviación
de gris (un ojo cerrado se ve más plano), con open_std/closed_std de la calibración.

Medido con ojo.mp4 (128 frames etiquetados a mano, cámara en la mano): la versión
anterior (umbral fijo, apertura 5x5, área < 35 %) acertaba ~88 % con el mejor umbral
y 62-70 % con el que elegía su calibración; esta, con su propia calibración, ~98 %.
En ese video el iris abierto sube hasta 0.71 radios sobre el centro y la ceja
aparece a 0.96-1.1: de ahí MAX_ABOVE.
"""
import math
from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

WORK_W = 320
MIN_CIRCULARITY = 0.5
OPEN_DIV = 4                # kernel de la apertura = radio de la pupila / OPEN_DIV
CLOSED_AREA_RATIO = 0.20    # área < 20 % de la calibrada = cerrado (bajo: tolera que la cámara se aleje)
RESCUE_MIN_KEEP = 0.45      # el círculo rescatado conserva al menos esto del blob
RESCUE_MAX_DIST = 1.0       # y está a menos de estos radios del centro calibrado
REFINE = 1.15               # radio del recorte / radio del círculo inscrito
MAX_ABOVE = 0.85            # radios de pupila por encima del centro calibrado = ceja, no ojo
LEVEL_RANGE = (0.6, 1.6)    # cuánto puede escalar el umbral con el brillo
USE_STD_ONLY = False        # Plan B


@dataclass
class EyeState:
    status: str                         # 'open', 'closed' o 'lost'
    area: float = 0.0
    center: tuple | None = None
    contour: np.ndarray | None = None   # para que annotate.py lo dibuje
    mask: np.ndarray | None = None      # imagen binaria del umbral (miniatura en el monitor)


def work_size(shape):
    """(ancho, alto) de trabajo para un frame de esa forma; conserva la proporción."""
    h, w = shape[:2]
    return WORK_W, max(1, round(WORK_W * h / w))


def preprocess(frame):
    """Paso 1: BGR (o gris) -> gris reducido y suavizado. calibration.py guarda esto."""
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, work_size(gray.shape), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(gray, (5, 5), 0)


def level(gray):
    """Brillo típico del frame (mediana: casi no cambia al cerrar el ojo)."""
    return float(np.median(gray[::2, ::2]))


def effective_thr(thr, gray, ref_level):
    if ref_level <= 0:
        return thr
    return thr * float(np.clip(level(gray) / ref_level, *LEVEL_RANGE))


def area_limits(open_area, shape):
    """(min_area, max_area) de la pupila. Sin calibrar (open_area <= 0), relativos al frame."""
    n = shape[0] * shape[1]
    if open_area <= 0:
        return 0.0007 * n, 0.4 * n
    return max(20.0, 0.10 * open_area), min(0.6 * n, 4.0 * open_area)


def pupil_radius(open_area, shape):
    """Radio de la pupila calibrada; sin calibrar, una estimación por el tamaño del frame."""
    return math.sqrt(open_area / math.pi) if open_area > 0 else shape[1] / 8


@lru_cache(maxsize=16)
def _kernel(size):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def opening_kernel(radius):
    return _kernel(max(3, int(round(radius / OPEN_DIV)) | 1))


def fill_holes(mask):
    """Rellena lo que no se alcanza desde el borde (reflejos dentro de la pupila)."""
    h, w = mask.shape
    flood = np.zeros((h + 2, w + 2), np.uint8)
    flood[1:-1, 1:-1] = mask
    cv2.floodFill(flood, None, (0, 0), 255)
    return mask | cv2.bitwise_not(flood[1:-1, 1:-1])


def refine(contour, mask):
    """Recorta el blob a REFINE x su círculo inscrito. Devuelve (contorno, área)."""
    x, y, w, h = cv2.boundingRect(contour)
    # distancia al fondo con 1 px de margen: el borde de la imagen cuenta como fondo
    roi = cv2.copyMakeBorder(mask[y:y + h, x:x + w], 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    dist = cv2.distanceTransform(roi, cv2.DIST_L2, 5)[1:-1, 1:-1]
    blob = np.zeros((h, w), np.uint8)
    cv2.drawContours(blob, [contour], -1, 255, -1, offset=(-x, -y))
    inside = np.where(blob > 0, dist, 0)
    _, r, _, (px, py) = cv2.minMaxLoc(inside)
    disk = np.zeros_like(blob)
    cv2.circle(disk, (px, py), int(math.ceil(REFINE * r)), 255, -1)
    parts, _ = cv2.findContours(blob & disk, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE, offset=(x, y))
    if not parts:
        return contour, cv2.contourArea(contour)
    part = max(parts, key=cv2.contourArea)
    return part, cv2.contourArea(part)


def _circularity(contour, area):
    perimeter = cv2.arcLength(cv2.convexHull(contour), True)
    return 4 * math.pi * area / perimeter ** 2 if perimeter else 0.0


def _rescue(contour, area, mask, center, radius):
    """Blob no redondo: si es un iris pegado a la línea de pestañas ("sombrero"),
    devuelve su círculo inscrito; si no, (None, 0). Sin estas condiciones, las sombras
    de la esquina del ojo cerrado también se "rescataban" como iris."""
    c, a = refine(contour, mask)
    if a < RESCUE_MIN_KEEP * area or _circularity(c, a) < MIN_CIRCULARITY:
        return None, 0.0
    x, y, w, h = cv2.boundingRect(c)
    if x <= 1 or y <= 1 or x + w >= mask.shape[1] - 1 or y + h >= mask.shape[0] - 1:
        return None, 0.0
    if center is not None:
        m = cv2.moments(c)
        if m["m00"] and math.dist((m["m10"] / m["m00"], m["m01"] / m["m00"]), center) > RESCUE_MAX_DIST * radius:
            return None, 0.0
    return c, a


def segment(gray, thr, open_area, center=None):
    """Pasos 2-6 sobre un gris de preprocess(). thr ya escalado.
    center=(cx, cy) calibrado activa el filtro de la ceja. Devuelve (contorno | None, área, máscara)."""
    _, mask = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY_INV)
    radius = pupil_radius(open_area, gray.shape)
    mask = cv2.morphologyEx(fill_holes(mask), cv2.MORPH_OPEN, opening_kernel(radius))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area, max_area = area_limits(open_area, gray.shape)
    best, best_area = None, 0.0
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area or area <= best_area:
            continue
        if _circularity(c, area) < MIN_CIRCULARITY:
            c, area = _rescue(c, area, mask, center, radius)
            if c is None or area < min_area or area <= best_area:
                continue
        if center is not None:
            m = cv2.moments(c)
            if m["m00"] and center[1] - m["m01"] / m["m00"] > MAX_ABOVE * radius:
                continue
        best, best_area = c, area
    return best, best_area, mask


def detect(gray, calib):
    """segment() con todo lo de la calibración (umbral escalado, área y centro)."""
    center = (calib.cx, calib.cy) if calib.cx >= 0 else None
    return segment(gray, effective_thr(calib.thr, gray, calib.ref_level), calib.open_area, center)


def find_pupil(frame, thr, open_area=0.0):
    """Devuelve (contorno | None, área, gris, máscara), sin escalar thr ni filtrar la ceja."""
    gray = preprocess(frame)
    contour, area, mask = segment(gray, thr, open_area)
    return contour, area, gray, mask


def classify(frame, calib) -> EyeState:
    """calib es una Calibration."""
    if frame is None:
        return EyeState("lost")
    gray = preprocess(frame)
    if USE_STD_ONLY:
        return _classify_std(gray, calib)
    contour, area, mask = detect(gray, calib)
    if gray.std() < calib.min_std:
        return EyeState("lost", mask=mask)
    if contour is not None:
        contour = refine(contour, mask)[0]
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
