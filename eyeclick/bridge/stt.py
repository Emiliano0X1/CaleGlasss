"""Speech -> text with faster-whisper, locally on the laptop.  (bridge)

    mic = Microphone(device)          # opens the mic once and keeps it running
    audio = mic.record()              # 16 kHz mono float32, until 1 s of silence or 8 s
    text = Transcriber().transcribe(audio)

The person always speaks English, so it uses Whisper's English-only model (small.en): more
accurate and faster than the multilingual one, and it can't "translate" into another language.
INITIAL_PROMPT gives Whisper the Jira words it should expect ("sprint", "bugs", "approve").

Microphone keeps the stream open between recordings and holds the last PREROLL_S of audio,
so a short word said right after the trigger ("approve") isn't cut off while the device
starts up. record() waits for the person to start talking (volume above SILENCE_RMS) and
stops after SILENCE_S of quiet once they did, or at MAX_S in any case.
next_utterance() is the always-on version for the wake phrase (wake.py): it waits as long
as it takes for speech and returns each utterance, until should_stop() says to let go.
Only one of them reads the microphone at a time (a lock), so a blink or F10 recording
takes over from the wake loop instead of splitting the audio with it. If the device can't
open at 16 kHz (WASAPI only takes its native rate) it records at the device's rate and resamples.

The model is loaded once (a few seconds; the first run also downloads it to the
Hugging Face cache) and then transcribes each recording. Called from a worker thread
(listener.py) or from `python -m eyeclick.bridge`, never from EyeClick's main thread.

What the text means (request, approve, reject) and cleaning it up is done in forge-app
(agents/interpret.ts), not here.

The microphone is MIC_DEVICE in eyeclick/bridge/.env: an index or part of the name, as
`python -m eyeclick.bridge --list-devices` prints them. Empty = the system default.
"""
import collections
import logging
import queue
import threading
import time

import numpy as np

log = logging.getLogger(__name__)

MODEL_SIZE = "small.en"
LANGUAGE = "en"
INITIAL_PROMPT = "Hey glasses, Jira, sprint 12, sprint 13, PROJ-14, bugs, backlog, assign, approve, reject, priority."
SAMPLE_RATE = 16000     # what faster-whisper expects
SILENCE_RMS = 0.01      # volume (RMS of a block, float32 -1..1) under which it counts as silence
SILENCE_S = 1.0         # this much silence after speaking ends the recording
WAKE_SILENCE_S = 0.8    # shorter for the wake loop: "Hey glasses" alone should answer fast
MAX_S = 8.0
PREROLL_S = 0.5         # audio kept from before the trigger
BLOCK_S = 0.05


def input_devices():
    """[(index, name, host API, default sample rate)] of the devices that can record."""
    import sounddevice as sd

    return [
        (i, d["name"], sd.query_hostapis(d["hostapi"])["name"], int(d["default_samplerate"]))
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


def find_device(spec):
    """MIC_DEVICE -> device index (None = system default). Accepts an index or part of the name."""
    spec = (spec or "").strip()
    if not spec:
        return None
    if spec.isdigit():
        return int(spec)
    for index, name, _, _ in input_devices():
        if spec.lower() in name.lower():
            return index
    raise ValueError(f"no input device matches {spec!r} (see --list-devices)")


class Microphone:
    def __init__(self, device=None):
        import sounddevice as sd

        try:
            sd.check_input_settings(device=device, channels=1, samplerate=SAMPLE_RATE)
            self.rate = SAMPLE_RATE
        except sd.PortAudioError:
            self.rate = int(sd.query_devices(device, "input")["default_samplerate"])
            log.info("device can't record at %d Hz, recording at %d Hz and resampling", SAMPLE_RATE, self.rate)
        self.name = sd.query_devices(device, "input")["name"]
        self._preroll = collections.deque(maxlen=int(PREROLL_S / BLOCK_S))
        self._blocks = queue.Queue()
        self._recording = False
        self._use = threading.Lock()    # record() and next_utterance() never read at the same time
        self._stream = sd.InputStream(
            device=device, channels=1, samplerate=self.rate, blocksize=int(self.rate * BLOCK_S),
            dtype="float32", callback=self._callback,
        )
        self._stream.start()

    def _callback(self, data, frames, time_info, status):
        # PortAudio's thread: only hand the block over
        block = data[:, 0].copy()
        if self._recording:
            self._blocks.put(block)
        else:
            self._preroll.append(block)

    def record(self, silence_rms=SILENCE_RMS, silence_s=SILENCE_S, max_s=MAX_S):
        """Records until silence_s of quiet after speech, or max_s. 16 kHz float32 (with the preroll)."""
        with self._use:
            return self._record(silence_rms, silence_s, max_s)

    def next_utterance(self, should_stop, silence_rms=SILENCE_RMS, silence_s=WAKE_SILENCE_S, max_s=MAX_S):
        """Waits for speech and returns it (16 kHz float32), or None as soon as should_stop() is true."""
        with self._use:
            chunks = list(self._preroll)
            self._preroll.clear()
            self._recording = True
            spoke, quiet, talked = False, 0.0, 0.0
            try:
                while not should_stop():
                    try:
                        block = self._blocks.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    seconds = len(block) / self.rate
                    if not spoke:
                        chunks = (chunks + [block])[-self._preroll.maxlen:]   # keep a short lead-in only
                        if rms(block) >= silence_rms:
                            spoke = True
                        continue
                    chunks.append(block)
                    talked += seconds
                    quiet = 0.0 if rms(block) >= silence_rms else quiet + seconds
                    if quiet >= silence_s or talked >= max_s:
                        audio = np.concatenate(chunks)
                        return resample(audio, self.rate) if self.rate != SAMPLE_RATE else audio
                return None
            finally:
                self._recording = False

    def _record(self, silence_rms, silence_s, max_s):
        chunks = list(self._preroll)
        self._preroll.clear()
        while not self._blocks.empty():
            self._blocks.get_nowait()
        self._recording = True
        spoke = any(rms(c) >= silence_rms for c in chunks)
        quiet, start = 0.0, time.monotonic()
        try:
            while time.monotonic() - start < max_s:
                block = self._blocks.get(timeout=1.0)
                chunks.append(block)
                if rms(block) >= silence_rms:
                    spoke, quiet = True, 0.0
                elif spoke:
                    quiet += len(block) / self.rate
                    if quiet >= silence_s:
                        break
        finally:
            self._recording = False
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        log.info("recorded %.1f s (speech detected: %s)", len(audio) / self.rate, spoke)
        return resample(audio, self.rate) if self.rate != SAMPLE_RATE else audio

    def close(self):
        self._stream.stop()
        self._stream.close()


def rms(block):
    return float(np.sqrt(np.mean(block**2))) if len(block) else 0.0


def resample(audio, rate):
    """Linear resampling to SAMPLE_RATE; good enough for speech recognition."""
    n = int(len(audio) * SAMPLE_RATE / rate)
    return np.interp(np.linspace(0, len(audio), n, endpoint=False), np.arange(len(audio)), audio).astype(np.float32)


class Transcriber:
    def __init__(self, model_size=MODEL_SIZE, language=LANGUAGE, prompt=INITIAL_PROMPT):
        self.model_size = model_size
        self.language = language
        self.prompt = prompt
        self._model = None

    def load(self):
        from faster_whisper import WhisperModel  # here: importing it takes a while

        log.info("loading Whisper %s...", self.model_size)
        self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio) -> str:
        """float32 mono audio at 16 kHz -> text ('' if nothing was said)."""
        if self._model is None:
            self.load()
        segments, _ = self._model.transcribe(
            audio,
            language=self.language,
            initial_prompt=self.prompt,
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 300},
        )
        return " ".join(s.text.strip() for s in segments).strip()
