"""Wake phrase "Hey glasses": what turns on the Jira command.  (bridge)

With --voice the microphone is always on (stt.Microphone.next_utterance). Each utterance is
transcribed with the small, fast WAKE_MODEL and only goes on if it contains the phrase:

    "Hey glasses, move the open bugs to sprint 13"   -> beep, the rest is the command
    "Hey glasses" ... (beep) ... "move the open bugs"  -> beep, then it records the command
    "Hey glasses, approve"                            -> approves the pending plan
    anything without the phrase                       -> ignored, nothing leaves the laptop

Whisper doesn't always write the phrase the same way, so command_after() accepts the
usual variants ("Hey, glasses.", "Hi glasses", "Hey glass", "Hey classes").
"""
import re

PHRASE = "Hey glasses"
WAKE_MODEL = "tiny.en"      # ~0.3 s per utterance: it only has to spot the phrase

_WAKE = re.compile(r"\b(?:hey|hi|hay|okay|ok)\W*(?:glasses|glass|classes|glass's)\b\W*", re.I)


def command_after(text):
    """None if the wake phrase isn't in `text`; otherwise what was said after it ('' if nothing)."""
    match = _WAKE.search(text or "")
    if match is None:
        return None
    return text[match.end():].strip(" \t,.!?;:-")
