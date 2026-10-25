"""glasses-bridge: voice + agents, in the same process as EyeClick.

    wake.py          -> the wake phrase "Hey glasses" that turns on the Jira command
    listener.py      -> wake loop + bus subscriber; long blink approves the pending plan or listens
    stt.py           -> microphone + audio -> text with faster-whisper (local)
    forge_client.py  -> POSTs the text or the approval to forge-app's `glasses` web trigger
    live_state.py    -> polls SpacetimeDB for the newest pending plan
    Bridge (here)    -> builds them for app.py and says what the overlay should show

None of this blocks the main thread: recording, transcribing, sending and reading
SpacetimeDB run on their own threads (see README, "Agent team").
"""
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

# httpx logs every SpacetimeDB poll (every 2 s) and faster_whisper every utterance at INFO:
# that drowns out the bridge's own messages.
for noisy in ("httpx", "httpcore", "httpx2", "httpcore2", "faster_whisper"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

STATUS_S = 4.0          # how long a finished status ("Approved ✓") stays before the plan note returns
PLAN_NOTE = 'Plan ready: "Hey glasses, approve" or blink'
IDLE_NOTE = 'Say "Hey glasses, ..."'
WORKING = ("Approving…", "Listening…", "Transcribing…", "Sending", "Voice is loading…")
WAKE_BEEP = (1500, 120)     # Hz, ms: "I heard you"


class Bridge:
    """Everything app.py needs for --voice: subscribe `listener`, call start(), talk() on F10,
    read note() from the main thread each tick, stop() on exit.
    beep(freq, ms): feedback.Feedback.beep, so the wake phrase is answered with a sound."""

    def __init__(self, model_size=None, beep=None):
        from . import stt
        from .forge_client import ForgeClient
        from .listener import VoiceListener
        from .live_state import LiveState
        from . import wake

        self._stt = stt
        self.model_size = model_size or stt.MODEL_SIZE
        self.live_state = LiveState()
        self.listener = VoiceListener(ForgeClient(), self.live_state, stt.Transcriber(self.model_size),
                                      on_status=self._set_status)
        self.wake_transcriber = stt.Transcriber(wake.WAKE_MODEL, prompt=None)   # a prompt with the phrase could make Whisper "hear" it in noise
        self._beep = beep
        self._stop = threading.Event()
        self._status = ("", 0.0)
        self._lock = threading.Lock()

    def start(self):
        self.live_state.start()
        self._set_status("Voice is loading…")
        threading.Thread(target=self._load, name="voice-load", daemon=True).start()

    def talk(self):
        self.listener.talk()

    def stop(self):
        self._stop.set()
        self.live_state.stop()
        self.listener.close()

    def note(self):
        """Second line of the overlay: a voice status while it's fresh, else the pending plan, else ''."""
        with self._lock:
            text, until = self._status
        if text and (time.monotonic() < until or text.startswith(WORKING)):
            return text
        if self.live_state.pending:
            return PLAN_NOTE
        return IDLE_NOTE if self.listener.microphone is not None else ""

    def _load(self):
        """Whisper takes a few seconds to load: off the main thread, so EyeClick starts right away."""
        try:
            self.listener.transcriber.load()
            self.wake_transcriber.load()
            self.listener.microphone = self._stt.Microphone(self._stt.find_device(os.environ.get("MIC_DEVICE")))
            self._set_status("Voice ready")
        except Exception:
            log.exception("voice couldn't start (blink approvals still work)")
            self._set_status("No microphone")
            return
        self.listener.run_wake_loop(self._stop, self.wake_transcriber, on_wake=self._on_wake)

    def _on_wake(self):
        if self._beep is not None:
            try:
                self._beep(*WAKE_BEEP)
            except Exception:
                log.exception("wake beep failed")

    def _set_status(self, text):
        with self._lock:
            self._status = (text, time.monotonic() + STATUS_S)
