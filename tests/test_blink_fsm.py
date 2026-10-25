"""Pruebas de la máquina de estados (sin cámara).  (SWE 1, ambos)

Correr con:  python -m pytest

TODO:
- [ ] Agregar casos raros que salgan en la prueba con usuario.
"""
from eyeclick.config import DRAG_AT, FRAMES_TO_CHANGE, LEFT_AT, LOST_FRAMES, MIN_BLINK, RIGHT_AT
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


def test_mas_de_3s_arrastra_hasta_abrir():
    assert run(4.0) == [E.EYE_CLOSED, E.STAGE_LEFT, E.STAGE_RIGHT, E.STAGE_DRAG, E.DRAG_END]


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


def test_umbrales_en_orden():
    assert MIN_BLINK < LEFT_AT < RIGHT_AT < DRAG_AT


def test_entre_min_blink_y_left_at_no_hace_clic():
    assert run((MIN_BLINK + LEFT_AT) / 2) == [E.EYE_CLOSED, E.CANCELLED]


def test_lost_corto_con_ojo_cerrado_sigue_contando():
    events = []
    fsm = BlinkFSM(events.append)
    # cerrado 0.47 s, luego LOST_FRAMES - 1 frames 'lost' que cruzan los 0.5 s, luego cerrado
    seq = ["open"] * 15 + ["closed"] * 14 + ["lost"] * (LOST_FRAMES - 1) + ["closed"] * 10 + ["open"] * 15
    for i, s in enumerate(seq):
        fsm.update(s, i * DT)
    assert [e.type for e in events] == [E.EYE_CLOSED, E.STAGE_LEFT, E.CLICK_LEFT]
    lost_start, lost_end = 29 * DT, (29 + LOST_FRAMES - 1) * DT
    assert lost_start <= events[1].t < lost_end     # STAGE_LEFT salió durante el 'lost'


def test_reset_cancela_el_cierre_en_curso():
    events = []
    fsm = BlinkFSM(events.append)
    for i, s in enumerate(["open"] * 5 + ["closed"] * 20):
        fsm.update(s, i * DT)
    fsm.reset(25 * DT)
    for i, s in enumerate(["open"] * 15, start=26):
        fsm.update(s, i * DT)
    assert [e.type for e in events] == [E.EYE_CLOSED, E.STAGE_LEFT, E.CANCELLED]
    assert fsm.closed_for(41 * DT) == 0.0



def _closed_then(tail, closed_s=4.0):
    events = []
    fsm = BlinkFSM(events.append)
    seq = ["open"] * 5 + ["closed"] * round(closed_s / DT) + tail
    for i, s in enumerate(seq):
        fsm.update(s, i * DT)
    return events, fsm, len(seq)


def test_perder_el_ojo_arrastrando_suelta():
    events, _, _ = _closed_then(["lost"] * (LOST_FRAMES + 3) + ["open"] * 10)
    types = [e.type for e in events]
    assert types[:4] == [E.EYE_CLOSED, E.STAGE_LEFT, E.STAGE_RIGHT, E.STAGE_DRAG]
    assert types.count(E.DRAG_END) == 1 and E.CANCELLED not in types
    assert types.index(E.DRAG_END) < types.index(E.EYE_LOST)


def test_reset_arrastrando_suelta():
    events, fsm, n = _closed_then([])
    fsm.reset(n * DT)
    assert [e.type for e in events][-1] == E.DRAG_END
    assert events[-1].duration >= DRAG_AT


def test_drag_end_trae_la_duracion():
    events, _, _ = _closed_then(["open"] * 5, closed_s=3.6)
    end = events[-1]
    assert end.type == E.DRAG_END and abs(end.duration - 3.6) < 0.1
