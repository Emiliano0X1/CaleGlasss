"""glasses-bridge: voice + agents, in the same process as EyeClick.

    wake.py          -> the wake phrase "Hey glasses" that turns on the Jira command
    listener.py      -> sends the command (request or approval); its own wake loop for the standalone test
    stt.py           -> microphone + Whisper, only for the standalone test (python -m eyeclick.bridge)
    forge_client.py  -> POSTs the text or the approval to forge-app's `glasses` web trigger
    live_state.py    -> polls SpacetimeDB for the newest pending plan
    Bridge (here)    -> what app.py uses with --voice, and what the overlay should show

Inside EyeClick there's one microphone and one Whisper: dictation's (actions/dictation.py,
always on with DICTATION_AUTO). It hands every transcript to Bridge.heard() first:
    "Hey glasses, <command>"  -> beep, the command goes to Jira; nothing is typed
    "Hey glasses" alone       -> beep, the next utterance (within ARM_S) is the command
    anything else             -> None: dictation types it / shows its preview as usual
Approving is by voice ("Hey glasses, approve"), from the panel or from Telegram: since main's
merge the 3 s blink is drag.

None of this blocks the main thread: sending and reading SpacetimeDB run on their own
threads (see README, "Agent team").
"""
import logging
import threading
import time

log = logging.getLogger(__name__)

# httpx logs every SpacetimeDB poll (every 2 s) and faster_whisper every utterance at INFO:
# that drowns out the bridge's own messages.
for noisy in ("httpx", "httpcore", "httpx2", "httpcore2", "faster_whisper"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

STATUS_S = 4.0          # how long a finished status ("Approved ✓") stays before the plan note returns
ARM_S = 8.0             # after "Hey glasses" alone, the next utterance within this is the command
PLAN_NOTE = 'Plan ready: "Hey glasses, approve"'
IDLE_NOTE = 'Say "Hey glasses, ..."'
WORKING = ("Approving…", "Listening…", "Transcribing…", "Sending")
WAKE_BEEP = (1500, 120)     # Hz, ms: "I heard you"


class Bridge:
    """Everything app.py needs for --voice: pass heard() to Dictation as its voice_hook, call
    start(), read note() from the main thread each tick, stop() on exit.
    beep(freq, ms): feedback.Feedback.beep, so the wake phrase is answered with a sound.
    client / live_state: fakes in the tests (default: ForgeClient() and LiveState())."""

    def __init__(self, beep=None, client=None, live_state=None, clock=time.monotonic):
        from .listener import VoiceListener

        if client is None:
            from .forge_client import ForgeClient
            client = ForgeClient()      # fails now if eyeclick/bridge/.env is missing, not after talking
        if live_state is None:
            from .live_state import LiveState
            live_state = LiveState()
        self.live_state = live_state
        self.listener = VoiceListener(client, live_state, on_status=self._set_status)
        self._beep = beep
        self._clock = clock
        self._armed_until = 0.0
        self._status = ("", 0.0)
        self._lock = threading.Lock()

    def start(self):
        self.live_state.start()

    def stop(self):
        self.live_state.stop()

    def heard(self, text):
        """Dictation's voice_hook, on its thread: a note if the text was for Jira (so it isn't
        typed), None if it wasn't."""
        from . import wake

        command = wake.command_after(text)
        if command is None:
            if self._clock() >= self._armed_until:
                return None
            command = text.strip()          # the command after a bare "Hey glasses"
        self._armed_until = 0.0
        if command:
            if self.listener.busy:
                return "Still sending the last one…"
            self._on_wake()
            self.listener.send_async(command)
            return "Sending to Jira…"
        self._on_wake()
        self._armed_until = self._clock() + ARM_S
        return "Hey glasses ✓"

    def note(self):
        """Second line of the overlay: a voice status while it's fresh, else the pending plan, else the hint."""
        if self._clock() < self._armed_until:
            return "Listening… say the command"
        with self._lock:
            text, until = self._status
        if text and (time.monotonic() < until or text.startswith(WORKING)):
            return text
        if self.live_state.pending:
            return PLAN_NOTE
        return IDLE_NOTE

    def _on_wake(self):
        if self._beep is not None:
            try:
                self._beep(*WAKE_BEEP)
            except Exception:
                log.exception("wake beep failed")

    def _set_status(self, text):
        with self._lock:
            self._status = (text, time.monotonic() + STATUS_S)
