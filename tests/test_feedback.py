"""Pruebas de feedback.py sin hardware de audio.  (SWE 2)"""
import numpy as np

from eyeclick.actions.feedback import DOUBLE, SOUNDS, TYPES, Feedback, _build
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent


class FakeOutput:
    def __init__(self):
        self.played = []

    def play(self, samples):
        self.played.append(samples)


class BrokenOutput:
    def __init__(self):
        self.calls = 0

    def play(self, samples):
        self.calls += 1
        raise RuntimeError("sin bocinas")


def test_cada_evento_suena_lo_esperado():
    out = FakeOutput()
    fb = Feedback(out)
    for etype in SOUNDS:
        fb.handle(EyeEvent(etype))
    assert len(out.played) == len(SOUNDS)
    for samples, spec in zip(out.played, SOUNDS.values()):
        assert np.array_equal(samples, _build(spec))


def test_bips_de_izquierdo_y_derecho_son_distintos():
    assert not np.array_equal(_build(SOUNDS[E.STAGE_LEFT]), _build(SOUNDS[E.STAGE_RIGHT]))
    assert SOUNDS[E.CLICK_LEFT] == SOUNDS[E.CLICK_RIGHT] == DOUBLE


def test_eventos_sin_sonido_no_suenan():
    out = FakeOutput()
    fb = Feedback(out)
    for etype in (E.EYE_CLOSED, E.CANCELLED, E.CALIBRATED):
        assert etype not in TYPES
        fb.handle(EyeEvent(etype))
    assert out.played == []


def test_silenciado_no_suena():
    out = FakeOutput()
    fb = Feedback(out)
    fb.set_muted(True)
    fb.handle(EyeEvent(E.CLICK_LEFT))
    assert out.played == []


def test_sin_audio_no_truena_y_solo_intenta_una_vez():
    out = BrokenOutput()
    fb = Feedback(out)
    fb.handle(EyeEvent(E.STAGE_LEFT))
    fb.handle(EyeEvent(E.STAGE_RIGHT))
    assert out.calls == 1


def test_tono_sin_chasquido():
    samples = _build(SOUNDS[E.STAGE_LEFT])
    assert samples.dtype == np.float32
    assert abs(samples[0]) < 1e-3 and abs(samples[-1]) < 1e-2
