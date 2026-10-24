"""Calibración (~8 s). Se corre al iniciar y cuando cambia la luz o se mueve la cámara.  (SWE 1)

Pasos:
    1. "Mantén el ojo abierto" 3 s: guardar frames.
    2. thr = percentil 5 del gris + 15 (la pupila es lo más oscuro).
    3. Con ese thr, open_area = mediana del área de la pupila.
    4. "Cierra el ojo" 3 s: si se detecta pupila en > 20 % de frames, bajar thr y repetir.
    5. min_std = mitad de la desviación de gris más baja vista.
    6. Emitir CALIBRATED y guardar en calib.json para no recalibrar al reiniciar.

TODO (SWE 1):
- [ ] Calibrator como máquina por pasos que pipeline.py alimenta frame a frame
      (no bloquea el hilo; expone .message para la EyeView).
- [ ] Implementar pasos 1-5.
- [ ] Robustez a cambios de luz (fase 3:30 - 5:00).
"""
import json
from dataclasses import asdict, dataclass

CALIB_FILE = "calib.json"
OPEN_SECONDS = 3.0
CLOSED_SECONDS = 3.0


@dataclass
class Calibration:
    thr: int = 50               # umbral de gris para la pupila
    open_area: float = 1500.0   # área mediana de la pupila con el ojo abierto
    min_std: float = 5.0        # debajo de esto la imagen es "plana" -> 'lost'

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
        self.message = "Mantén el ojo abierto"
        self.done = False
        self.result: Calibration | None = None

    def feed(self, frame, t):
        # TODO (SWE 1): acumular frames por fase, cambiar self.message,
        #               y al terminar llenar self.result y poner self.done = True.
        raise NotImplementedError
