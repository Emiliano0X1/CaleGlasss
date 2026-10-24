"""Pruebas del bus.  (SWE 2)"""
import threading

import pytest

from eyeclick.bus import Bus
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent


class Recorder:
    def __init__(self):
        self.got = []

    def handle(self, ev):
        self.got.append(ev.type)


class Broken:
    def handle(self, ev):
        raise RuntimeError("falla a propósito")


def test_suscriptor_que_falla_no_frena_a_los_demas():
    bus, ok = Bus(), Recorder()
    bus.subscribe(Broken())
    bus.subscribe(ok)
    bus.publish(EyeEvent(E.CLICK_LEFT))
    bus.dispatch()
    assert ok.got == [E.CLICK_LEFT]


def test_filtra_por_tipo():
    bus, rec = Bus(), Recorder()
    bus.subscribe(rec, {E.CLICK_RIGHT})
    bus.publish(EyeEvent(E.CLICK_LEFT))
    bus.publish(EyeEvent(E.CLICK_RIGHT))
    bus.dispatch()
    assert rec.got == [E.CLICK_RIGHT]


def test_nada_llega_antes_de_dispatch_y_respeta_el_orden():
    bus, rec = Bus(), Recorder()
    bus.subscribe(rec)
    seq = [E.EYE_CLOSED, E.STAGE_LEFT, E.STAGE_RIGHT, E.CLICK_RIGHT]
    for t in seq:
        bus.publish(EyeEvent(t))
    assert rec.got == []
    assert bus.dispatch() == len(seq)
    assert rec.got == seq
    assert bus.dispatch() == 0


def test_publish_desde_otro_hilo_llega_en_dispatch():
    bus, rec = Bus(), Recorder()
    bus.subscribe(rec)
    hilos = [threading.Thread(target=lambda: [bus.publish(EyeEvent(E.EYE_CLOSED)) for _ in range(100)])
             for _ in range(4)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    bus.dispatch()
    assert len(rec.got) == 400


def test_evento_publicado_dentro_de_handle_va_al_siguiente_dispatch():
    bus, rec = Bus(), Recorder()

    class Echo:
        def handle(self, ev):
            bus.publish(EyeEvent(E.CANCELLED))

    bus.subscribe(Echo(), {E.EYE_CLOSED})
    bus.subscribe(rec)
    bus.publish(EyeEvent(E.EYE_CLOSED))
    bus.dispatch()
    assert rec.got == [E.EYE_CLOSED]
    bus.dispatch()
    assert rec.got == [E.EYE_CLOSED, E.CANCELLED]


def test_suscriptor_sin_handle_falla_al_registrar():
    with pytest.raises(TypeError):
        Bus().subscribe(object())
