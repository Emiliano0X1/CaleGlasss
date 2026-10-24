"""Bips de retroalimentación por las bocinas.  (SWE 2, suscriptor del bus)

    STAGE_LEFT  (0.5 s) -> bip 880 Hz       "si abres ahora es clic izquierdo"
    STAGE_RIGHT (1.2 s) -> bip 1320 Hz      "si abres ahora es clic derecho"
    CLICK_*             -> doble bip 1000 Hz
    EYE_LOST            -> bip grave 300 Hz, 200 ms

sounddevice.play no bloquea, así que el bip no frena el procesamiento.
Después se puede mover al buzzer del ESP32.

TODO (SWE 2):
- [ ] handle(): mapear cada evento a su bip.
- [ ] Revisar que los bips se oigan distintos en la laptop del demo.
"""
import numpy as np
import sounddevice as sd

from eyeclick.events import EventType as E

SR = 44100
TYPES = {E.STAGE_LEFT, E.STAGE_RIGHT, E.CLICK_LEFT, E.CLICK_RIGHT, E.EYE_LOST}


def _tone(freq, ms):
    t = np.arange(int(SR * ms / 1000)) / SR
    return (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


class Feedback:
    def beep(self, freq, ms=80):
        sd.play(_tone(freq, ms), SR)

    def double_beep(self):
        gap = np.zeros(int(SR * 0.05), np.float32)
        sd.play(np.concatenate([_tone(1000, 60), gap, _tone(1000, 60)]), SR)

    def handle(self, ev):
        # TODO (SWE 2)
        raise NotImplementedError
