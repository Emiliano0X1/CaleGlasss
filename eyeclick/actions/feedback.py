"""Bips de retroalimentación por las bocinas.  (SWE 2, suscriptor del bus)

    STAGE_LEFT  (0.5 s) -> bip 880 Hz       "si abres ahora es clic izquierdo"
    STAGE_RIGHT (1.2 s) -> bip 1320 Hz      "si abres ahora es clic derecho"
    CLICK_*             -> doble bip 1000 Hz
    EYE_LOST            -> bip grave 300 Hz, 200 ms

Los sonidos se definen en SOUNDS y se generan una sola vez al crear Feedback.
"Dónde suena" está aparte (SpeakerOutput): para usar el buzzer del ESP32 basta
con otra clase que tenga play(samples) y pasarla en Feedback(output=...).

SpeakerOutput abre UN stream de audio al empezar y lo deja abierto: play() solo
cambia el buffer que lee el callback, así que no bloquea (sd.play abría un stream
nuevo en cada bip y congelaba el hilo principal 200-400 ms en Windows). Un bip
nuevo corta al anterior. Si no hay dispositivo de audio, se avisa una vez en el
log y Feedback se queda callado en lugar de fallar en cada evento.

TODO (SWE 2):
- [x] handle(): mapear cada evento a su bip.
- [ ] Revisar que los bips se oigan distintos en la laptop del demo.
- [ ] Esp32Output: mandar el bip al buzzer de los lentes (misma interfaz play()).
"""
import logging
import threading

import numpy as np

from eyeclick.events import EventType as E

log = logging.getLogger(__name__)

SR = 44100
VOLUME = 0.3
FADE_MS = 5             # rampa al inicio y al final para que no truene la bocina

# Cada sonido es una lista de (frecuencia Hz, duración ms); frecuencia 0 = silencio.
DOUBLE = [(1000, 60), (0, 50), (1000, 60)]
SOUNDS = {
    E.STAGE_LEFT: [(880, 80)],
    E.STAGE_RIGHT: [(1320, 80)],
    E.CLICK_LEFT: DOUBLE,
    E.CLICK_RIGHT: DOUBLE,
    E.EYE_LOST: [(300, 200)],
}
TYPES = set(SOUNDS)     # para bus.subscribe(feedback, TYPES)


def _tone(freq, ms):
    n = int(SR * ms / 1000)
    if freq == 0:
        return np.zeros(n, np.float32)
    t = np.arange(n) / SR
    wave = VOLUME * np.sin(2 * np.pi * freq * t)
    fade = min(int(SR * FADE_MS / 1000), n // 2)
    if fade:
        ramp = np.linspace(0.0, 1.0, fade)
        wave[:fade] *= ramp
        wave[-fade:] *= ramp[::-1]
    return wave.astype(np.float32)


def _build(spec):
    return np.concatenate([_tone(f, ms) for f, ms in spec])


class SpeakerOutput:
    """Bocinas de la laptop con sounddevice, con un stream que queda abierto."""

    def __init__(self):
        import sounddevice as sd    # aquí y no arriba: las pruebas no necesitan audio
        self._lock = threading.Lock()
        self._buf, self._pos = np.zeros(0, np.float32), 0
        self._stream = sd.OutputStream(samplerate=SR, channels=1, dtype="float32",
                                       callback=self._callback)
        self._stream.start()

    def _callback(self, outdata, frames, time_info, status):
        # hilo de audio: copiar lo que toca del bip actual y rellenar con silencio
        with self._lock:
            chunk = self._buf[self._pos:self._pos + frames]
            self._pos += len(chunk)
        outdata[:len(chunk), 0] = chunk
        outdata[len(chunk):] = 0

    def play(self, samples):
        with self._lock:
            self._buf, self._pos = samples, 0

    def stop(self):
        self._stream.stop()
        self._stream.close()


class Feedback:
    def __init__(self, output=None):
        self.output = output
        self.muted = False
        self._broken = False
        self._sounds = {etype: _build(spec) for etype, spec in SOUNDS.items()}

    def set_muted(self, muted):
        self.muted = muted

    def beep(self, freq, ms=80):
        self._play(_tone(freq, ms))

    def double_beep(self):
        self._play(_build(DOUBLE))

    def handle(self, ev):
        samples = self._sounds.get(ev.type)
        if samples is not None:
            self._play(samples)

    def close(self):
        if self.output is not None and hasattr(self.output, "stop"):
            try:
                self.output.stop()
            except Exception:
                pass

    def _play(self, samples):
        if self.muted or self._broken:
            return
        try:
            if self.output is None:
                self.output = SpeakerOutput()
            self.output.play(samples)
        except Exception:
            self._broken = True
            log.warning("No se pudo reproducir audio; los bips quedan desactivados.", exc_info=True)
