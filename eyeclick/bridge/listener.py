""""Hey glasses, ..." -> a Jira request or an approval.  (bridge)

Two ways in, both "Hey glasses" (wake.py) and then the command:
    send_async(command)  inside EyeClick (--voice): dictation's always-on mic transcribes,
                         Bridge.heard() (__init__.py) spots the phrase and hands the command here
    run_wake_loop()      standalone (python -m eyeclick.bridge --wake): this listener's own
                         microphone (stt.Microphone, MIC_DEVICE); the words after the phrase are
                         the command, or, if there are none, it records the command next
Only one send runs at a time (the busy lock). Approving is by voice only: since main's merge
the 3 s blink is drag (config.DRAG_AT), so there's no blink trigger anymore.

handle_text(): a transcript like "approve" / "approve it" / "yes, approve" with a pending
plan becomes an approval of that exact plan; anything else is a request, and forge-app
(agents/interpret.ts) still recognizes looser approvals ("go ahead") and rejections.

on_status(text) is called from the worker thread; app.py reads it from the main thread
(Bridge.note() in __init__.py), it never touches tkinter from here.
"""
import logging
import re
import threading

from . import wake
from .forge_client import ForgeError

log = logging.getLogger(__name__)

APPROVAL = re.compile(r"^\W*(yes\W+)?(approve|approved|approve it|approve that|approve the plan|i approve)\W*$", re.I)


def is_approval(text):
    return bool(APPROVAL.match(text or ""))


def handle_text(client, text, plan):
    """Sends what was heard: an approval of `plan` if it's an "approve" and there's a plan, else a request."""
    if plan and is_approval(text):
        log.info("heard an approval for %s", plan["id"])
        return client.send_approval(plan["id"])
    return client.send_request(text)


def describe(answer):
    """One short line on what forge-app did (terminal and overlay)."""
    if answer.get("duplicate"):
        return "Already sent"
    intent = answer.get("intent")
    if intent == "request":
        return f'Request sent: "{answer.get("instruction")}"'
    if intent == "approve":
        return {
            "approved": "Approved ✓ executing",
            "already": "Already approved",
            "nothing_pending": "No plan to approve",
            "not_registered": "Not registered",
            "not_found": "Plan not found",
        }.get(answer.get("result"), f"Approve: {answer.get('result')}")
    if intent == "reject":
        return "Rejected ✓" if answer.get("result") == "rejected" else f"Reject: {answer.get('result')}"
    return "Didn't get that, try again"


class VoiceListener:
    def __init__(self, client, live_state, transcriber=None, microphone=None, on_status=lambda text: None):
        """client: forge_client.ForgeClient. live_state: live_state.LiveState (its .pending).
        transcriber, microphone: stt.Transcriber / stt.Microphone, only for run_wake_loop()
        (inside EyeClick dictation already has the text). on_status: called from ANOTHER thread."""
        self.client = client
        self.live_state = live_state
        self.transcriber = transcriber
        self.microphone = microphone
        self.on_status = on_status
        self._busy = threading.Lock()

    @property
    def busy(self):
        return self._busy.locked()

    def send_async(self, command):
        """Sends `command` on a worker thread. False (and nothing sent) if the last one is still going."""
        if not self._busy.acquire(blocking=False):
            log.info("still busy with the last one, ignored")
            return False
        threading.Thread(target=self._run_send, args=(command,), name="voice", daemon=True).start()
        return True

    def _run_send(self, command):
        try:
            self._guarded(self._send, command)
        finally:
            self._busy.release()

    def run_wake_loop(self, stop, wake_transcriber, on_wake=lambda: None, on_heard=lambda text: None):
        """Always-on listening for "Hey glasses" until `stop` (threading.Event) is set.
        wake_transcriber: a fast stt.Transcriber (wake.WAKE_MODEL). on_wake(): e.g. a beep.
        on_heard(text): every non-empty utterance without the phrase (the terminal test shows them)."""
        while not stop.is_set():
            if self.microphone is None or self.busy:
                stop.wait(0.2)
                continue
            audio = self.microphone.next_utterance(lambda: stop.is_set() or self.busy)
            if audio is None or self.busy:
                continue
            heard = wake_transcriber.transcribe(audio)
            command = wake.command_after(heard)
            log.debug("utterance %.1f s: %r (wake: %s)", len(audio) / 16000, heard, command is not None)
            if command is None:
                if heard:
                    on_heard(heard)
                continue
            if not self._busy.acquire(blocking=False):
                continue
            log.info("wake phrase in %r", heard)
            try:
                on_wake()
                self.on_status("Hey glasses ✓")
                if command:
                    # same audio, accurate model: tiny.en only had to spot the phrase
                    command = wake.command_after(self.transcriber.transcribe(audio)) or command
                    self._guarded(self._send, command)
                else:
                    self._guarded(self._listen_and_send)
            finally:
                self._busy.release()

    def _listen_and_send(self):
        if self.microphone is None:
            self.on_status("Voice is still loading…")
            return
        self.on_status("Listening…")
        audio = self.microphone.record()
        self.on_status("Transcribing…")
        text = self.transcriber.transcribe(audio)
        log.info("heard: %r", text)
        if not text:
            self.on_status("Didn't hear anything")
            return
        self._send(wake.command_after(text) or text)   # "Hey glasses, ..." said again is fine

    def _send(self, text):
        self.on_status(f'Sending "{text}"')
        self.on_status(describe(handle_text(self.client, text, self.live_state.pending)))

    def _guarded(self, fn, *args):
        try:
            fn(*args)
        except ForgeError as e:
            log.warning("couldn't send: %s", e)
            self.on_status("Couldn't reach Forge")
        except Exception:
            log.exception("voice failed")
            self.on_status("Voice error")

    def close(self):
        if self.microphone is not None:
            self.microphone.close()
