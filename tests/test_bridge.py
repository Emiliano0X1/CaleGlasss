"""Bridge tests: long blink / voice -> approval or request, and the live plan state.  (bridge)

No network, microphone or Whisper: the client, transcriber and microphone are fakes.
"""
import threading

import pytest

from eyeclick.bridge import listener, live_state
from eyeclick.bridge.listener import VoiceListener, handle_text, is_approval
from eyeclick.bridge.live_state import LiveState
from eyeclick.config import CANCEL_AT
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent

PLAN = {"id": "p-w-1", "summary": "Move 8 issues to Sprint 13"}


class FakeClient:
    def __init__(self):
        self.sent = []
        self.done = threading.Event()

    def send_request(self, text):
        self.sent.append(("request", text))
        self.done.set()
        return {"intent": "request", "instruction": text}

    def send_approval(self, proposal_id):
        self.sent.append(("approve", proposal_id))
        self.done.set()
        return {"intent": "approve", "result": "approved", "proposal_id": proposal_id}


class FakeState:
    def __init__(self, pending=None):
        self.pending = pending


class FakeTranscriber:
    def __init__(self, text):
        self.text = text

    def transcribe(self, audio):
        return self.text


class FakeMic:
    def record(self):
        return [0.0]

    def close(self):
        pass


def make(pending=None, heard="move the open bugs to sprint 13"):
    client, statuses = FakeClient(), []
    voice = VoiceListener(client, FakeState(pending), FakeTranscriber(heard), FakeMic(), on_status=statuses.append)
    return voice, client, statuses


def wait(client):
    assert client.done.wait(2), "the worker thread didn't send anything"


@pytest.mark.parametrize("text", ["approve", "Approve.", "approve it", "Yes, approve.", "approved", "I approve"])
def test_approval_words(text):
    assert is_approval(text)


@pytest.mark.parametrize("text", ["", "approve the bugs for Alana", "move it to sprint 13", "don't approve"])
def test_not_approval_words(text):
    assert not is_approval(text)


def test_long_blink_with_a_plan_approves_it():
    voice, client, statuses = make(pending=PLAN)
    voice.handle(EyeEvent(E.CANCELLED, duration=CANCEL_AT))
    wait(client)
    assert client.sent == [("approve", "p-w-1")]


def test_long_blink_without_a_plan_listens_and_sends_a_request():
    voice, client, statuses = make(pending=None)
    voice.handle(EyeEvent(E.CANCELLED, duration=CANCEL_AT + 0.1))
    wait(client)
    assert client.sent == [("request", "move the open bugs to sprint 13")]
    assert "Listening…" in statuses


def test_short_cancel_is_not_a_long_blink():
    voice, client, _ = make(pending=PLAN)
    voice.handle(EyeEvent(E.CANCELLED, duration=0.3))   # a natural blink
    assert not client.done.wait(0.2)


def test_saying_approve_approves_the_pending_plan():
    voice, client, _ = make(pending=PLAN, heard="Approve.")
    voice.talk()
    wait(client)
    assert client.sent == [("approve", "p-w-1")]


def test_saying_approve_without_a_plan_goes_as_a_request():
    # forge-app then answers "nothing to approve"
    assert handle_text(FakeClient(), "approve", None) == {"intent": "request", "instruction": "approve"}


def test_listener_only_wants_cancelled():
    assert listener.TYPES == {E.CANCELLED}


def test_live_state_reports_only_changes():
    plans = iter([None, PLAN, PLAN, None])
    seen = []
    state = LiveState(on_change=seen.append, fetch=lambda: next(plans))
    for _ in range(4):
        state.poll()
    assert seen == [PLAN, None]


def test_live_state_keeps_the_last_plan_when_the_network_fails():
    calls = iter([PLAN])

    def fetch():
        try:
            return next(calls)
        except StopIteration:
            raise OSError("no network")

    state = LiveState(fetch=fetch)
    state.poll()
    assert state.poll() == PLAN and state.pending == PLAN


def test_fetch_pending_picks_the_newest_work_item(monkeypatch):
    tables = {
        "proposals": [["p-old", "w-old", "old plan"], ["p-new", "w-new", "new plan"]],
        "work_items": [["w-old", [100]], ["w-new", [200]]],
    }
    monkeypatch.setattr(live_state, "sql", lambda q: tables["proposals" if "FROM proposals" in q else "work_items"])
    assert live_state.fetch_pending() == {"id": "p-new", "summary": "new plan"}


def test_fetch_pending_without_plans(monkeypatch):
    monkeypatch.setattr(live_state, "sql", lambda q: [])
    assert live_state.fetch_pending() is None


# --- wake phrase "Hey glasses" ---

from eyeclick.bridge import wake  # noqa: E402


@pytest.mark.parametrize(
    "text, command",
    [
        ("Hey glasses, move the open bugs to sprint 13.", "move the open bugs to sprint 13"),
        ("Hey, glasses. Approve.", "Approve"),
        ("hey glass assign PROJ-14 to Alana", "assign PROJ-14 to Alana"),
        ("Hi glasses!", ""),
        ("Hey glasses.", ""),
        ("um, hey glasses, approve", "approve"),
    ],
)
def test_wake_phrase_and_command(text, command):
    assert wake.command_after(text) == command


@pytest.mark.parametrize("text", ["", "Hey, how are you doing today?", "I think the glasses look great on you"])
def test_no_wake_phrase(text):
    assert wake.command_after(text) is None


class WakeMic(FakeMic):
    """next_utterance() returns each queued utterance once, then stops the loop."""

    def __init__(self, stop, utterances):
        self.stop, self.utterances = stop, list(utterances)

    def next_utterance(self, should_stop):
        if not self.utterances:
            self.stop.set()
            return None
        return self.utterances.pop(0)


class ByAudio:
    """Fake transcriber: the 'audio' is already the text."""

    def transcribe(self, audio):
        return audio


def run_wake(utterances, pending=None, then_heard=""):
    stop, client, beeps = threading.Event(), FakeClient(), []
    voice = VoiceListener(client, FakeState(pending), FakeTranscriber(then_heard), WakeMic(stop, utterances))
    voice.transcriber = ByAudio() if not then_heard else voice.transcriber
    voice.run_wake_loop(stop, ByAudio(), on_wake=lambda: beeps.append(True))
    return client.sent, beeps


def test_wake_with_command_sends_it():
    sent, beeps = run_wake(["we should move the meeting", "Hey glasses, move the open bugs to sprint 13"])
    assert sent == [("request", "move the open bugs to sprint 13")]
    assert beeps == [True]


def test_wake_approve_approves_the_pending_plan():
    sent, _ = run_wake(["Hey glasses, approve"], pending=PLAN)
    assert sent == [("approve", "p-w-1")]


def test_wake_alone_then_records_the_command():
    sent, beeps = run_wake(["Hey glasses"], then_heard="assign the open bugs to Alana")
    assert sent == [("request", "assign the open bugs to Alana")]
    assert beeps == [True]


def test_without_the_phrase_nothing_is_sent():
    sent, beeps = run_wake(["move everything to sprint 13", "approve"], pending=PLAN)
    assert sent == [] and beeps == []
