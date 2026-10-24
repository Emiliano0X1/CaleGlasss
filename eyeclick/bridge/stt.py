"""Voz -> texto con faster-whisper, local en la laptop.  (bridge)

El modelo se carga una sola vez (tarda unos segundos) y luego transcribe cada
grabación. Se llama desde el hilo de trabajo de listener.py, nunca desde el
hilo principal.

TODO (bridge):
- [ ] Agregar faster-whisper a requirements.txt.
- [ ] Cargar WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8") en load().
- [ ] transcribe(audio): audio float32 mono a 16 kHz -> texto (language=LANGUAGE).
- [ ] Medir la latencia en la laptop del demo; si es lenta, bajar a "tiny" o "base".
"""
import logging

log = logging.getLogger(__name__)

MODEL_SIZE = "small"
LANGUAGE = "es"


class Transcriber:
    def __init__(self, model_size=MODEL_SIZE, language=LANGUAGE):
        self.model_size = model_size
        self.language = language
        self._model = None

    def load(self):
        # TODO (bridge): from faster_whisper import WhisperModel (aquí, no arriba)
        raise NotImplementedError

    def transcribe(self, audio) -> str:
        # TODO (bridge): if self._model is None: self.load(); unir los segmentos en un texto
        raise NotImplementedError
