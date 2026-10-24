"""Pruebas del overlay.  (SWE 2)

text_for() se prueba sin ventana; lo demás se salta si no hay pantalla.
"""
import time

import numpy as np
import pytest

from eyeclick.config import CANCEL_AT
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent, EyeView
from eyeclick.ui import overlay as o


@pytest.mark.parametrize("ev, texto, warn", [
    (EyeEvent(E.EYE_CLOSED), "cerrado...", False),
    (EyeEvent(E.STAGE_LEFT), "IZQUIERDO", False),
    (EyeEvent(E.STAGE_RIGHT), "DERECHO", False),
    (EyeEvent(E.CLICK_LEFT), "clic ✓", False),
    (EyeEvent(E.CLICK_RIGHT), "clic ✓", False),
    (EyeEvent(E.CANCELLED, duration=0.2), "abierto", False),
    (EyeEvent(E.CANCELLED, duration=CANCEL_AT), "descanso", False),
    (EyeEvent(E.EYE_LOST), "NO VEO EL OJO", True),
    (EyeEvent(E.CALIBRATED), "calibrado", False),
])
def test_text_for(ev, texto, warn):
    assert o.text_for(ev)[:2] == (texto, warn)


class FakeSource:
    def __init__(self, status="lost"):
        self.status = status

    def latest_view(self):
        return EyeView(frame=np.zeros((2, 2, 3), np.uint8), status=self.status)



def texto(ov):
    return ov.label.cget("text")


def test_clic_vuelve_a_abierto(root):
    ov = o.Overlay(root)
    ov.handle(EyeEvent(E.CLICK_LEFT))
    assert texto(ov) == "clic ✓" and ov.label.cget("bg") == o.COLORS["clic ✓"]
    ov._revert_at = time.monotonic() - 0.01
    ov._tick()
    assert texto(ov) == o.IDLE
    ov.close()


def test_sin_ojo_espera_ver_el_ojo_abierto(root):
    src = FakeSource("lost")
    ov = o.Overlay(root, src)
    ov.handle(EyeEvent(E.EYE_LOST))
    ov._tick()
    assert texto(ov) == "NO VEO EL OJO" and ov.label.cget("bg") == o.RED
    src.status = "open"
    ov._tick()
    assert texto(ov) == o.IDLE
    ov.close()


def test_pausa_ignora_eventos(root):
    ov = o.Overlay(root)
    ov.set_paused(True)
    ov.handle(EyeEvent(E.STAGE_LEFT))
    ov._tick()
    assert texto(ov) == "PAUSA"
    ov.set_paused(False)
    assert texto(ov) == "ACTIVO"
    ov.handle(EyeEvent(E.STAGE_LEFT))
    assert texto(ov) == "IZQUIERDO"
    ov.close()


def test_sigue_visible_con_el_monitor_minimizado(root):
    ov = o.Overlay(root)
    root.update()
    root.iconify()
    root.update()
    assert ov.win.winfo_viewable()
    ov.close()
