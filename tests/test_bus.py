"""Pruebas del bus.  (SWE 2)

TODO (SWE 2):
- [ ] Quitar el skip de abajo cuando bus.py esté implementado.
- [ ] Agregar: publish desde otro hilo llega en dispatch del hilo principal.
"""
import pytest

from eyeclick.bus import Bus
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent

pytestmark = pytest.mark.skip(reason="TODO SWE 2: implementar bus.py")


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
