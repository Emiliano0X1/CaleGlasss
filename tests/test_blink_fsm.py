"""Pruebas de la máquina de estados (sin cámara).  (SWE 1, ambos)

Correr con:  python -m pytest

TODO:
- [ ] Agregar casos raros que salgan en la prueba con usuario.
"""
from eyeclick.config import FRAMES_TO_CHANGE, LOST_FRAMES
from eyeclick.events import EventType as E
from eyeclick.logic.blink_fsm import BlinkFSM

DT = 1 / 30     # 30 FPS


def run(closed_seconds, tail="open"):
    """Simula: ojo abierto 0.5 s, cerrado `closed_seconds`, luego `tail` 0.5 s."""
    events = []
    fsm = BlinkFSM(events.append)
    t = 0.0
    seq = (["open"] * 15 + ["closed"] * round(closed_seconds / DT) + [tail] * 15)
    for status in seq:
        fsm.update(status, t)
        t += DT
    return [e.type for e in events]


def test_parpadeo_natural_no_hace_clic():
    assert run(0.2) == [E.EYE_CLOSED, E.CANCELLED]


def test_clic_izquierdo():
    assert run(0.8) == [E.EYE_CLOSED, E.STAGE_LEFT, E.CLICK_LEFT]


def test_clic_derecho():
    assert run(1.5) == [E.EYE_CLOSED, E.STAGE_LEFT, E.STAGE_RIGHT, E.CLICK_RIGHT]


def test_mas_de_3s_se_cancela():
    assert run(4.0) == [E.EYE_CLOSED, E.STAGE_LEFT, E.STAGE_RIGHT, E.CANCELLED]


def test_frame_suelto_cerrado_no_cambia_estado():
    events = []
    fsm = BlinkFSM(events.append)
    seq = ["open"] * 10 + ["closed"] * (FRAMES_TO_CHANGE - 1) + ["open"] * 10
    for i, s in enumerate(seq):
        fsm.update(s, i * DT)
    assert events == []


def test_lost_con_ojo_cerrado_cancela():
    events = run(0.3, tail="lost")
    assert events[:1] == [E.EYE_CLOSED]
    assert E.CANCELLED in events and E.EYE_LOST in events
    assert E.CLICK_LEFT not in events and E.CLICK_RIGHT not in events
    assert LOST_FRAMES == 5
