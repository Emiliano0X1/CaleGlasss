"""Pruebas del simulador sin teclado real (se inyecta un listener falso).  (SWE 2)"""
import time

from eyeclick.config import VIEW_H, VIEW_W
from eyeclick.events import EventType as E
from eyeclick.sources import mock as mk

DT = 1 / mk.HZ


class FakeListener:
    def __init__(self, on_press, on_release):
        self.press, self.release, self.stopped = on_press, on_release, False

    def stop(self):
        self.stopped = True


def make():
    events, holder = [], {}

    def listener(on_press, on_release):
        holder["l"] = FakeListener(on_press, on_release)
        return holder["l"]

    src = mk.MockSource(events.append, make_listener=listener)
    return src, events, holder


def run(src, status_seconds, t=0.0):
    """status_seconds: lista de (closed, lost, segundos). Avanza step() a 60 Hz."""
    for closed, lost, secs in status_seconds:
        src.set_closed(closed)
        src.set_lost(lost)
        for _ in range(round(secs / DT)):
            src.step(t)
            t += DT
    return t


def types(events):
    return [e.type for e in events]


def test_f8_corto_es_clic_izquierdo():
    src, events, _ = make()
    run(src, [(False, False, 0.3), (True, False, 0.8), (False, False, 0.3)])
    assert types(events) == [E.EYE_CLOSED, E.STAGE_LEFT, E.CLICK_LEFT]


def test_f8_largo_es_clic_derecho():
    src, events, _ = make()
    run(src, [(False, False, 0.3), (True, False, 1.6), (False, False, 0.3)])
    assert types(events) == [E.EYE_CLOSED, E.STAGE_LEFT, E.STAGE_RIGHT, E.CLICK_RIGHT]


def test_f7_es_ojo_perdido():
    src, events, _ = make()
    run(src, [(False, False, 0.3), (False, True, 0.5)])
    assert types(events) == [E.EYE_LOST]
    assert src.latest_view().status == "lost"


def test_recalibrar_cancela_y_publica_calibrated():
    src, events, _ = make()
    t = run(src, [(False, False, 0.3), (True, False, 0.3)])
    src.recalibrate()
    t = run(src, [(True, False, 0.5)], t)
    assert src.latest_view().message                    # muestra el mensaje mientras calibra
    run(src, [(False, False, mk.CALIBRATE_S)], t)
    assert types(events) == [E.EYE_CLOSED, E.CANCELLED, E.CALIBRATED]
    assert src.latest_view().message == ""


def test_vista_falsa_y_umbral():
    src, _, _ = make()
    src.set_threshold(999)
    src.step(0.0)
    v = src.latest_view()
    assert v.frame.shape == (VIEW_H, VIEW_W, 3) and v.thr == 255
    assert v.status == "open" and v.pupil_area > 0 and v.mask.shape == (mk.MASK_H, mk.MASK_W)
    src.set_threshold(10)
    src.step(DT)
    assert src.latest_view().pupil_area < v.pupil_area   # el slider se nota en la imagen


def test_teclas_start_stop():
    src, events, holder = make()
    src.start()
    try:
        listener = holder["l"]
        listener.press("f8")
        assert src._closed
        listener.release("f8")
        listener.press(None)                            # otras teclas no hacen nada
        assert not src._closed
        time.sleep(0.1)
        assert src.latest_view() is not None
    finally:
        src.stop()
    assert listener.stopped and src._thread is None
    assert events[0].type == E.CALIBRATED


def test_sin_pynput_arranca_igual():
    def broken(on_press, on_release):
        raise ImportError("sin pynput")

    src = mk.MockSource(lambda ev: None, make_listener=broken)
    src.start()
    try:
        time.sleep(0.05)
        assert src.latest_view() is not None
    finally:
        src.stop()
