"""Bridge tests: "Hey glasses" -> approval or request, and the live plan state.  (bridge)

No network, microphone or Whisper: the client, transcriber and microphone are fakes.
Bridge.heard() is what dictation calls with each transcript inside EyeClick; run_wake_loop()
is the standalone test (python -m eyeclick.bridge --wake) with its own microphone.
"""
import threading

import pytest

from eyeclick.bridge import ARM_S, Bridge, live_state
from eyeclick.bridge.listener import VoiceListener, handle_text, is_approval
from eyeclick.bridge.live_state import LiveState

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


def wait(client):
    assert client.done.wait(2), "the worker thread didn't send anything"


@pytest.mark.parametrize("text", ["approve", "Approve.", "approve it", "Yes, approve.", "approved", "I approve"])
def test_approval_words(text):
    assert is_approval(text)


@pytest.mark.parametrize("text", ["", "approve the bugs for Alana", "move it to sprint 13", "don't approve"])
def test_not_approval_words(text):
    assert not is_approval(text)


def test_saying_approve_without_a_plan_goes_as_a_request():
    # forge-app then answers "nothing to approve"
    assert handle_text(FakeClient(), "approve", None) == {"intent": "request", "instruction": "approve"}


# --- Bridge.heard(): dictation's voice_hook inside EyeClick ---

class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def bridge(pending=None):
    client, beeps, clock = FakeClient(), [], Clock()
    b = Bridge(beep=lambda *tone: beeps.append(tone), client=client, live_state=FakeState(pending), clock=clock)
    return b, client, beeps, clock


def test_heard_wake_with_command_sends_it_and_is_not_typed():
    b, client, beeps, _ = bridge()
    assert b.heard("Hey glasses, move the open bugs to sprint 13.") == "Sending to Jira…"
    wait(client)
    assert client.sent == [("request", "move the open bugs to sprint 13")]
    assert len(beeps) == 1


def test_heard_approve_approves_the_pending_plan():
    b, client, _, _ = bridge(pending=PLAN)
    assert b.heard("Hey glasses, approve.") == "Sending to Jira…"
    wait(client)
    assert client.sent == [("approve", "p-w-1")]


def test_heard_without_the_phrase_is_left_to_dictation():
    b, client, beeps, _ = bridge(pending=PLAN)
    assert b.heard("hello world") is None
    assert b.heard("approve") is None       # a plain "approve" is dictation, not an approval
    assert not client.done.wait(0.2) and beeps == []


def test_heard_wake_alone_then_the_next_utterance_is_the_command():
    b, client, beeps, clock = bridge()
    assert b.heard("Hey glasses.") == "Hey glasses ✓"
    assert b.note() == "Listening… say the command"
    clock.now += ARM_S - 1
    assert b.heard("Assign the open bugs to Ana.") == "Sending to Jira…"
    wait(client)
    assert client.sent == [("request", "Assign the open bugs to Ana.")]
    assert len(beeps) == 2
    assert b.heard("and this is dictation again") is None     # armed only once


def test_heard_wake_alone_expires():
    b, client, _, clock = bridge()
    b.heard("Hey glasses")
    clock.now += ARM_S + 0.1
    assert b.heard("move the bugs") is None
    assert b.note() != "Listening… say the command"
    assert not client.done.wait(0.2)


def test_heard_while_still_sending_is_not_typed_either():
    b, client, _, _ = bridge()
    b.listener._busy.acquire()               # the last send is still going
    assert b.heard("Hey glasses, move the bugs") == "Still sending the last one…"
    b.listener._busy.release()
    assert client.sent == []


def test_note_shows_the_pending_plan():
    b, _, _, _ = bridge(pending=PLAN)
    assert b.note() == 'Plan ready: "Hey glasses, approve"'
    b, _, _, _ = bridge()
    assert b.note() == 'Say "Hey glasses, ..."'


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
