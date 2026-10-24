"""Calibración (~8 s). Se corre al iniciar y cuando cambia la luz o se mueve la cámara.  (SWE 1)

Pasos (cada fase empieza con READY_SECONDS para reaccionar al mensaje, sin guardar frames):
    1. "Mantén el ojo abierto" 3 s: guardar frames.
    2. thr = percentil 5 del gris + 15 (la pupila es lo más oscuro).
    3. Con ese thr, open_area = mediana del área de la pupila.
    4. "Cierra el ojo" 3 s: si se detecta pupila en > 20 % de frames, bajar thr y repetir.
    5. min_std = mitad de la desviación de gris más baja vista.
    6. pipeline.py emite CALIBRATED y guarda en calib.json para no recalibrar al reiniciar.

Calibrator no bloquea: pipeline.py lo alimenta frame a frame con feed() y muestra
.message en la EyeView. Los frames se guardan ya en gris y suavizados, así el paso 4
vuelve a probar los mismos frames con otro thr sin pedirle al usuario que repita.
Si algo sale dudoso (no se ve la pupila, o se sigue viendo con el ojo cerrado),
.warning lo explica y pipeline.py lo muestra unos segundos.

Ante cambios de luz: el slider de umbral corrige al momento, y si el ojo no se ve
abierto durante un rato, pipeline.py sugiere recalibrar.
"""
import json
import math
from dataclasses import asdict, dataclass

import numpy as np

from eyeclick.vision import detector

CALIB_FILE = "calib.json"
OPEN_SECONDS = 3.0
CLOSED_SECONDS = 3.0
READY_SECONDS = 1.0         # tiempo para reaccionar al mensaje
SAMPLE_DT = 1 / 15          # ~45 frames por fase: suficiente y no tarda en procesarse
THR_MARGIN = 15
THR_STEP = 5
MIN_THR = 5
MAX_CLOSED_RATE = 0.20      # con el ojo cerrado no debería verse pupila en más de esto
MIN_OPEN_RATE = 0.50        # con el ojo abierto debería verse pupila al menos en esto

OPEN_MSG = "Mantén el ojo abierto"
CLOSED_MSG = "Cierra el ojo"


@dataclass
class Calibration:
    thr: int = 50               # umbral de gris para la pupila
    open_area: float = 1500.0   # área mediana de la pupila con el ojo abierto
    min_std: float = 5.0        # debajo de esto la imagen es "plana" -> 'lost'
    open_std: float = 0.0       # desviación de gris típica con el ojo abierto (Plan B)
    closed_std: float = 0.0     # desviación de gris típica con el ojo cerrado (Plan B)

    def save(self, path=CALIB_FILE):
        with open(path, "w") as f:
            json.dump(asdict(self), f)

    @classmethod
    def load(cls, path=CALIB_FILE):
        try:
            with open(path) as f:
                return cls(**json.load(f))
        except (OSError, ValueError, TypeError):
            return None


class Calibrator:
    """Se alimenta con feed(frame, t) desde el hilo del pipeline."""

    def __init__(self):
        self.message = OPEN_MSG
        self.done = False
        self.result: Calibration | None = None
        self.warning = ""
        self._phase = "open"            # 'open' -> 'closed'
        self._t_phase = None
        self._last_sample = -math.inf
        self._grays = {"open": [], "closed": []}

    def feed(self, frame, t):
        if self.done or frame is None:
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
                self.result = self._compute()
                self.message = "Listo"
                self.done = True
            return
        label = OPEN_MSG if self._phase == "open" else CLOSED_MSG
        self.message = f"{label}... {math.ceil(total - elapsed)}"
        if elapsed >= READY_SECONDS and t - self._last_sample >= SAMPLE_DT:
            self._last_sample = t
            self._grays[self._phase].append(detector.preprocess(frame))

    def _compute(self):
        opened, closed = self._grays["open"], self._grays["closed"]
        self._grays = {"open": [], "closed": []}    # liberar memoria
        if not opened or not closed:
            self.warning = "Calibración sin imágenes: revisa la cámara"
            return Calibration()

        # pasos 2-4: bajar thr mientras el ojo cerrado siga mostrando "pupila",
        # pero sin llegar a perder la pupila con el ojo abierto
        limits = detector.area_limits(0, opened[0].shape)
        start = int(np.median([np.percentile(g[::2, ::2], 5) for g in opened])) + THR_MARGIN
        best = None
        for thr in range(max(MIN_THR, min(250, start)), MIN_THR - 1, -THR_STEP):
            areas = np.array([detector.segment(g, thr, *limits)[1] for g in opened])
            found = areas[areas > 0]
            open_area = float(np.median(found)) if found.size else 0.0
            open_rate = found.size / len(opened)
            if best is not None and open_rate < MIN_OPEN_RATE:
                break
            closed_rate = self._open_rate(closed, thr, open_area) if open_area else 0.0
            best = thr, open_area, open_rate, closed_rate
            if open_area == 0 or closed_rate <= MAX_CLOSED_RATE:
                break                           # sin pupila, bajar thr no la hace aparecer
        thr, open_area, open_rate, closed_rate = best

        warnings = []
        if open_area == 0:
            warnings.append("No se ve la pupila: acerca o enfoca la cámara")
            open_area = Calibration().open_area
        else:
            if open_rate < MIN_OPEN_RATE:
                warnings.append("La pupila se ve poco: revisa la luz o el enfoque")
            if closed_rate > MAX_CLOSED_RATE:
                warnings.append("Con el ojo cerrado aún se ve pupila: baja el umbral")
        self.warning = "; ".join(warnings)

        # paso 5 (+ desviaciones para el Plan B)
        open_stds = [float(g.std()) for g in opened]
        closed_stds = [float(g.std()) for g in closed]
        return Calibration(
            thr=int(thr),
            open_area=float(open_area),
            min_std=0.5 * min(open_stds + closed_stds),
            open_std=float(np.median(open_stds)),
            closed_std=float(np.median(closed_stds)),
        )

    @staticmethod
    def _open_rate(grays, thr, open_area):
        """Fracción de frames que classify() llamaría 'open' con este thr y open_area."""
        limits = detector.area_limits(open_area, grays[0].shape)
        hits = sum(detector.segment(g, thr, *limits)[1] >= detector.CLOSED_AREA_RATIO * open_area
                   for g in grays)
        return hits / len(grays)
