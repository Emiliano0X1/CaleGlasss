"""Calibración (~8 s). Se corre al iniciar y cuando cambia la luz o se mueve la cámara.  (SWE 1)

Pasos (cada fase empieza con READY_SECONDS para reaccionar al mensaje, sin guardar frames):
    1. "Mantén el ojo abierto" 3 s: guardar frames.
    2. "Cierra el ojo" 3 s: guardar frames.
    3. Probar umbrales entre el gris más oscuro y el típico del ojo abierto. Para cada
       uno: open_area y centro = medianas con el ojo abierto, y puntaje = % de frames
       abiertos que classify() llamaría 'open' - % de frames cerrados que llamaría 'open'.
    4. thr = el umbral MÁS ALTO que deja el ojo cerrado como cerrado (<= 20 %) y ve el
       abierto, un paso más abajo (_pick). Medido en ojo.mp4 y ojo2.mp4: el error típico
       fuera de la calibración es "cerrado" con el ojo abierto, y un umbral alto lo evita.
    5. min_std = mitad de la desviación de gris más baja vista.
    6. Red (model.py, si está eye_model.onnx): logit de cada frame guardado. Si separa
       bien (mediana abierta - mediana cerrada >= MODEL_MIN_SEP), se usa la red para
       decidir abierto/cerrado con el corte a MODEL_K del camino de cerrado a abierto
       (más cerca de cerrado: un clic falso es peor que uno perdido). El umbral clásico
       se sigue calculando para dibujar la pupila y por si la red no separa.
    7. pipeline.py emite CALIBRATED y guarda en calib.json para no recalibrar al reiniciar.

Calibrator no bloquea: pipeline.py lo alimenta frame a frame con feed() y muestra
.message en la EyeView. Los pasos 3-5 corren en un hilo aparte (en la Raspberry
tardan unos segundos) y .done se pone en True al terminar.
Si algo sale dudoso (no se ve la pupila, o se sigue viendo con el ojo cerrado),
.warning lo explica y pipeline.py lo muestra unos segundos.

Ante cambios de luz: el umbral se escala solo con el brillo del frame (detector.py),
el slider corrige al momento, y si el ojo no se ve abierto durante un rato,
pipeline.py sugiere recalibrar.
"""
import json
import math
import threading
from dataclasses import asdict, dataclass, replace

import cv2
import numpy as np

from eyeclick.vision import detector, model

CALIB_FILE = "calib.json"
VERSION = 3                 # sube cuando cambian las unidades: un calib.json viejo se ignora
OPEN_SECONDS = 3.0
CLOSED_SECONDS = 3.0
READY_SECONDS = 1.0         # tiempo para reaccionar al mensaje
SAMPLE_DT = 1 / 10          # ~30 frames por fase: suficiente y rápido de procesar
MAX_CANDIDATES = 24         # umbrales a probar
GOOD_MARGIN = 0.10          # puntaje a menos de esto del mejor = "tramo bueno"
OPEN_SLACK = 0.10           # "ve el ojo abierto" = a menos de esto del mejor % visto
SAFETY_STEPS = 3            # bajar este número de umbrales desde el límite
SMOOTH = 5                  # umbrales vecinos que se promedian (un pico suelto es ruido)
MAX_CLOSED_RATE = 0.20      # con el ojo cerrado no debería verse pupila en más de esto
MIN_OPEN_RATE = 0.50        # con el ojo abierto debería verse pupila al menos en esto
MODEL_MIN_SEP = 3.0         # la red separa si las medianas de logit difieren al menos esto
MODEL_K = 0.4               # corte de la red: 0 = mediana cerrada, 1 = mediana abierta

OPEN_MSG = "Keep your eye open"
CLOSED_MSG = "Close your eye"
WORKING_MSG = "Calculating..."


@dataclass
class Calibration:
    thr: int = 50               # umbral de gris para la pupila, al brillo ref_level
    open_area: float = 1500.0   # área mediana de la pupila con el ojo abierto (px de trabajo)
    min_std: float = 5.0        # debajo de esto la imagen es "plana" -> 'lost'
    open_std: float = 0.0       # desviación de gris típica con el ojo abierto (Plan B)
    closed_std: float = 0.0     # desviación de gris típica con el ojo cerrado (Plan B)
    ref_level: float = 0.0      # brillo típico al calibrar (0 = no escalar thr)
    cx: float = -1.0            # centro típico de la pupila (-1 = desconocido)
    cy: float = -1.0
    use_model: bool = False     # decidir con la red (model.py) en vez del umbral
    model_cut: float = 0.0      # logit > model_cut = abierto
    version: int = VERSION

    def save(self, path=CALIB_FILE):
        with open(path, "w") as f:
            json.dump(asdict(self), f)

    @classmethod
    def load(cls, path=CALIB_FILE):
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("version") != VERSION:
                return None
            return cls(**data)
        except (OSError, ValueError, TypeError, AttributeError):
            return None


class Calibrator:
    """Se alimenta con feed(frame, t) desde el hilo del pipeline."""

    def __init__(self):
        self.message = OPEN_MSG
        self.done = False
        self.result: Calibration | None = None
        self.warning = ""
        self._phase = "open"            # 'open' -> 'closed' -> 'working'
        self._t_phase = None
        self._last_sample = -math.inf
        self._grays = {"open": [], "closed": []}
        self._logits = {"open": [], "closed": []}
        self._finished = threading.Event()

    def feed(self, frame, t):
        if self._phase == "working" or frame is None:
            return
        if self._t_phase is None:
            self._t_phase = t
        elapsed = t - self._t_phase
        total = READY_SECONDS + (OPEN_SECONDS if self._phase == "open" else CLOSED_SECONDS)
        if elapsed >= total:
            if self._phase == "open":
                self._phase, self._t_phase = "closed", t
                self.message = f"{CLOSED_MSG}... {math.ceil(READY_SECONDS + CLOSED_SECONDS)}"
            else:
                self._phase, self.message = "working", WORKING_MSG
                threading.Thread(target=self._finish, name="calibration", daemon=True).start()
            return
        label = OPEN_MSG if self._phase == "open" else CLOSED_MSG
        self.message = f"{label}... {math.ceil(total - elapsed)}"
        if elapsed >= READY_SECONDS and t - self._last_sample >= SAMPLE_DT:
            self._last_sample = t
            self._grays[self._phase].append(detector.preprocess(frame))
            score = model.logit(frame)          # None si no hay modelo
            if score is not None:
                self._logits[self._phase].append(score)

    def wait(self, timeout=None):
        """Espera a que termine el cálculo (para pruebas y herramientas)."""
        return self._finished.wait(timeout)

    def _finish(self):
        opened, closed = self._grays["open"], self._grays["closed"]
        self._grays = {"open": [], "closed": []}    # liberar memoria
        logits, self._logits = self._logits, {"open": [], "closed": []}
        try:
            self.result = self._compute(opened, closed)
            self.result = self._with_model(self.result, logits["open"], logits["closed"])
        except Exception as e:              # nunca dejar al pipeline esperando
            self.warning, self.result = f"Calibration failed: {e}", Calibration()
        self.message = "Done"
        self.done = True
        self._finished.set()

    def _compute(self, opened, closed):
        if not opened or not closed:
            self.warning = "Calibration got no images: check the camera"
            return Calibration()

        # paso 3: probar umbrales
        ref_level = float(np.median([detector.level(g) for g in opened]))
        lo = int(np.median([np.percentile(g, 1) for g in opened])) + 1
        hi = int(np.median([np.percentile(g, 50) for g in opened]))
        step = max(1, (hi - lo) // MAX_CANDIDATES)
        trials = [self._try(thr, ref_level, opened, closed) for thr in range(lo, max(lo, hi) + 1, step)]
        trials = [tr for tr in trials if tr is not None]
        if not trials:
            self.warning = "Pupil not visible: move the camera closer or focus it"
            return Calibration(ref_level=ref_level)

        # paso 4: el umbral más alto que aún separa, menos SAFETY_STEPS de margen
        _, cand, open_rate, closed_rate = trials[_pick(trials)]

        warnings = []
        if open_rate < MIN_OPEN_RATE:
            warnings.append("La pupila se ve poco: revisa la luz o el enfoque")
        if closed_rate > MAX_CLOSED_RATE:
            warnings.append("Pupil still visible with the eye closed: lower the threshold")
        self.warning = "; ".join(warnings)

        # paso 5 (+ desviaciones para el Plan B)
        open_stds = [float(g.std()) for g in opened]
        closed_stds = [float(g.std()) for g in closed]
        return replace(
            cand,
            min_std=0.5 * min(open_stds + closed_stds),
            open_std=float(np.median(open_stds)),
            closed_std=float(np.median(closed_stds)),
        )

    def _with_model(self, result, open_logits, closed_logits):
        """Paso 6: ¿la red separa el ojo abierto del cerrado de esta persona?"""
        if not open_logits or not closed_logits:
            return result
        lo, hi = float(np.median(closed_logits)), float(np.median(open_logits))
        if hi - lo < MODEL_MIN_SEP:
            self.warning = "; ".join(filter(None, [self.warning, "Model unsure here: using pupil detection"]))
            return result
        # la red decide: los avisos de la pupila (p. ej. iris fuera del cuadro) ya no aplican
        self.warning = ""
        return replace(result, use_model=True, model_cut=lo + MODEL_K * (hi - lo))

    @staticmethod
    def _try(thr, ref_level, opened, closed):
        """(puntaje, Calibration candidata, % abiertos vistos, % cerrados vistos como abiertos)."""
        found = []
        for g in opened:
            c, area, _ = detector.segment(g, detector.effective_thr(thr, g, ref_level), 0)
            if c is not None:
                found.append((area, *_centroid(c)))
        if not found:
            return None
        areas, xs, ys = np.array(found).T
        cand = Calibration(thr=int(thr), open_area=float(np.median(areas)), min_std=0.0,
                           ref_level=ref_level, cx=float(np.median(xs)), cy=float(np.median(ys)))
        open_rate = _open_rate(opened, cand)
        closed_rate = _open_rate(closed, cand)
        return open_rate - closed_rate, cand, open_rate, closed_rate


def _pick(trials):
    """Índice del umbral elegido. trials va de umbral bajo a alto.

    Un umbral alto ve el iris aunque cambie un poco la luz o el ángulo (lo que falla
    fuera de los 3 s de calibración es "cerrado" con el ojo abierto); el límite es
    cuando el ojo cerrado empieza a verse abierto. Por eso: el más alto que deja el
    ojo cerrado como cerrado y ve el abierto casi siempre, un paso más abajo.
    Si ninguno cumple, el centro del tramo con mejor puntaje (suavizado).
    """
    best_open = max(tr[2] for tr in trials)
    ok = [i for i, (_, _, o, c) in enumerate(trials)
          if c <= MAX_CLOSED_RATE and o >= best_open - OPEN_SLACK]
    if ok:
        top = ok[-1]
        back = top - SAFETY_STEPS
        return back if back in ok else top
    scores = _smooth([tr[0] for tr in trials], SMOOTH)
    good = max(scores) - GOOD_MARGIN
    i = j = int(np.argmax(scores))
    while i > 0 and scores[i - 1] >= good:
        i -= 1
    while j < len(scores) - 1 and scores[j + 1] >= good:
        j += 1
    return (i + j) // 2


def _smooth(values, n):
    """Promedio móvil de n, repitiendo los extremos."""
    pad = n // 2
    v = np.pad(np.asarray(values, float), pad, mode="edge")
    return list(np.convolve(v, np.ones(n) / n, mode="valid"))


def _centroid(contour):
    m = cv2.moments(contour)
    return (m["m10"] / m["m00"], m["m01"] / m["m00"]) if m["m00"] else (0.0, 0.0)


def _open_rate(grays, calib):
    """Fracción de frames que classify() llamaría 'open' con esta calibración."""
    hits = 0
    for g in grays:
        c, area, _ = detector.detect(g, calib)
        hits += c is not None and area >= detector.CLOSED_AREA_RATIO * calib.open_area
    return hits / len(grays)
