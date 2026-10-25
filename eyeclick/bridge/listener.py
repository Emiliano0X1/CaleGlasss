""""Hey glasses" or a long blink -> a Jira request or an approval.  (bridge, bus subscriber)

It's one more subscriber: app.py registers it with bus.subscribe(listener, TYPES) when it
runs with --voice. handle() runs on the main thread, so it only starts a worker thread;
recording, transcribing (stt.py) and sending (forge_client.py) happen there.

The long blink is the eye module's CANCELLED event fired while the eye has been closed for
CANCEL_AT (3 s): the point where a click is no longer possible. events.py has no event of
its own for it, so the contract between SWE 1 and SWE 2 stays as it is. Resting the eyes for
3 s counts as a long blink too, so --voice is opt-in.

trigger() (long blink; in --mock, hold F8 for 3 s):
    pending plan (live_state.py)  -> send_approval(plan id)
    no plan                       -> record -> transcribe -> handle_text()
talk() (F10, the voice fallback): always records, so "approve" can be said instead of blinking.
run_wake_loop() (its own thread, the main way in): the mic is always on and an utterance
    that starts with "Hey glasses" (wake.py) beeps and is handled: the words after the
    phrase are the command, or, if there are none, it records the command next.
Only one of these runs at a time (the busy lock); the wake loop lets go of the microphone
while a blink or F10 recording is on.

handle_text(): a transcript like "approve" / "approve it" / "yes, approve" with a pending
plan becomes an approval of that exact plan; anything else is a request, and forge-app
(agents/interpret.ts) still recognizes looser approvals ("go ahead") and rejections.

on_status(text) is called from the worker thread; app.py reads it from the main thread
(Bridge.note() in __init__.py), it never touches tkinter from here.
"""
import logging
import re
import threading

from eyeclick.config import CANCEL_AT
from eyeclick.events import EventType as E

from . import wake
from .forge_client import ForgeError

log = logging.getLogger(__name__)

TYPES = {E.CANCELLED}
LONG_BLINK_S = CANCEL_AT

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
    def __init__(self, client, live_state, transcriber, microphone=None, on_status=lambda text: None):
        """client: forge_client.ForgeClient. live_state: live_state.LiveState (its .pending).
        transcriber: stt.Transcriber. microphone: stt.Microphone, or None until load() opens it.
        on_status: called from ANOTHER thread."""
        self.client = client
        self.live_state = live_state
        self.transcriber = transcriber
        self.microphone = microphone
        self.on_status = on_status
        self._busy = threading.Lock()

    def handle(self, ev):
        if ev.type == E.CANCELLED and ev.duration >= LONG_BLINK_S:
            self.trigger()

    def trigger(self):
        """Long blink: approve the pending plan, or listen for a request. Any thread."""
        self._start(approve_first=True)

    def talk(self):
        """Voice fallback (F10): always listen; saying "approve" approves the pending plan."""
        self._start(approve_first=False)

    @property
    def busy(self):
        return self._busy.locked()

    def _start(self, approve_first):
        if not self._busy.acquire(blocking=False):
            log.info("still busy with the last one, ignored")
            return
        threading.Thread(target=self._run, args=(approve_first,), name="voice", daemon=True).start()

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

    def _run(self, approve_first):
        try:
            plan = self.live_state.pending
            if approve_first and plan:
                self.on_status("Approving…")
                self._guarded(lambda: self.on_status(describe(self.client.send_approval(plan["id"]))))
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
