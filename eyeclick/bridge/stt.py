"""Speech -> text with faster-whisper, locally on the laptop.  (bridge)

The model is loaded once (takes a few seconds) and then transcribes each
recording. Called from listener.py's worker thread, never from the main thread.

TODO (bridge):
- [ ] Add faster-whisper to requirements.txt.
- [ ] Load WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8") in load().
- [ ] transcribe(audio): float32 mono audio at 16 kHz -> text (language=LANGUAGE).
- [ ] Measure latency on the demo laptop; if it's slow, drop to "tiny" or "base".
"""
import logging

log = logging.getLogger(__name__)

MODEL_SIZE = "small"
LANGUAGE = "es"         # language the wearer speaks; None = auto-detect


class Transcriber:
    def __init__(self, model_size=MODEL_SIZE, language=LANGUAGE):
        self.model_size = model_size
        self.language = language
        self._model = None

    def load(self):
        # TODO (bridge): from faster_whisper import WhisperModel (here, not at the top)
        raise NotImplementedError

    def transcribe(self, audio) -> str:
        # TODO (bridge): if self._model is None: self.load(); join the segments into one text
        raise NotImplementedError
