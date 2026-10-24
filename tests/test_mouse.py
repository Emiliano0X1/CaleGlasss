"""Pruebas de mouse.py con un mouse falso (sin pynput).  (SWE 2)"""
from eyeclick.actions.mouse import MouseActions
from eyeclick.config import CLICK_COOLDOWN
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent


class FakeMouse:
    def __init__(self):
        self.position = (0, 0)
        self.clicks = []        # (botón, posición al hacer clic)

    def click(self, button):
        self.clicks.append((button, self.position))


def make():
    m = FakeMouse()
    return MouseActions(controller=m, buttons=("L", "R")), m


def cierre(actions, mouse, t, tipo, se_movio_a=(500, 500)):
    """Cierra en (100, 100), el giroscopio mueve el cursor y abre con un clic de `tipo`."""
    mouse.position = (100, 100)
    actions.handle(EyeEvent(E.EYE_CLOSED, t))
    mouse.position = se_movio_a
    actions.handle(EyeEvent(tipo, t + 0.8, 0.8))


def test_clic_izquierdo_en_la_posicion_guardada():
    a, m = make()
    cierre(a, m, 0.0, E.CLICK_LEFT)
    assert m.clicks == [("L", (100, 100))]


def test_clic_derecho():
    a, m = make()
    cierre(a, m, 0.0, E.CLICK_RIGHT)
    assert m.clicks == [("R", (100, 100))]


def test_cancelado_no_hace_clic():
    a, m = make()
    a.handle(EyeEvent(E.EYE_CLOSED, 0.0))
    a.handle(EyeEvent(E.CANCELLED, 0.2, 0.2))
    a.handle(EyeEvent(E.CLICK_LEFT, 0.9, 0.9))     # clic sin su EYE_CLOSED
    assert m.clicks == []


def test_cooldown():
    a, m = make()
    cierre(a, m, 0.0, E.CLICK_LEFT)                 # clic en t=0.8
    a.handle(EyeEvent(E.EYE_CLOSED, 0.85))
    a.handle(EyeEvent(E.CLICK_LEFT, 0.8 + CLICK_COOLDOWN / 2))
    assert len(m.clicks) == 1
    cierre(a, m, 1.0 + CLICK_COOLDOWN, E.CLICK_LEFT)
    assert len(m.clicks) == 2


def test_pausa_no_hace_clic():
    a, m = make()
    assert a.toggle_pause() is True
    cierre(a, m, 0.0, E.CLICK_LEFT)
    assert m.clicks == []
    assert a.toggle_pause() is False
    cierre(a, m, 2.0, E.CLICK_LEFT)
    assert len(m.clicks) == 1


def test_pausar_a_mitad_de_un_cierre_no_hace_clic():
    a, m = make()
    a.handle(EyeEvent(E.EYE_CLOSED, 0.0))
    a.set_paused(True)
    a.set_paused(False)
    a.handle(EyeEvent(E.CLICK_LEFT, 0.8, 0.8))
    assert m.clicks == []
