"""Pruebas del overlay.  (SWE 2)

text_for() se prueba sin ventana; lo demás se salta si no hay pantalla.
"""
import time

import numpy as np
import pytest

from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent, EyeView
from eyeclick.ui import overlay as o


@pytest.mark.parametrize("ev, texto, warn", [
    (EyeEvent(E.EYE_CLOSED), "closed...", False),
    (EyeEvent(E.STAGE_LEFT), "LEFT", False),
    (EyeEvent(E.STAGE_RIGHT), "RIGHT", False),
    (EyeEvent(E.CLICK_LEFT), "click ✓", False),
    (EyeEvent(E.CLICK_RIGHT), "click ✓", False),
    (EyeEvent(E.CANCELLED, duration=0.2), "open", False),
    (EyeEvent(E.STAGE_DRAG, duration=3.0), "DRAGGING", False),
    (EyeEvent(E.DRAG_END, duration=3.5), "dropped ✓", False),
    (EyeEvent(E.EYE_LOST), "CAN'T SEE EYE", True),
    (EyeEvent(E.CALIBRATED), "calibrated", False),
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
    assert texto(ov) == "click ✓" and ov.label.cget("bg") == o.COLORS["click ✓"]
    ov._revert_at = time.monotonic() - 0.01
    ov._tick()
    assert texto(ov) == o.IDLE
    ov.close()


def test_sin_ojo_espera_ver_el_ojo_abierto(root):
    src = FakeSource("lost")
    ov = o.Overlay(root, src)
    ov.handle(EyeEvent(E.EYE_LOST))
    ov._tick()
    assert texto(ov) == "CAN'T SEE EYE" and ov.label.cget("bg") == o.RED
    src.status = "open"
    ov._tick()
    assert texto(ov) == o.IDLE
    ov.close()


def test_pausa_ignora_eventos(root):
    ov = o.Overlay(root)
    ov.set_paused(True)
    ov.handle(EyeEvent(E.STAGE_LEFT))
    ov._tick()
    assert texto(ov) == "PAUSED"
    ov.set_paused(False)
    assert texto(ov) == "ACTIVE"
    ov.handle(EyeEvent(E.STAGE_LEFT))
    assert texto(ov) == "LEFT"
    ov.close()


def test_sigue_visible_con_el_monitor_minimizado(root):
    ov = o.Overlay(root)
    root.update()
    root.iconify()
    root.update()
    assert ov.win.winfo_viewable()
    ov.close()


def test_boton_mic_y_estado_del_dictado(root):
    pedidos = []
    ov = o.Overlay(root, on_dictate=lambda: pedidos.append(1))
    root.update()
    ov.mic.event_generate("<ButtonRelease-1>")
    assert pedidos == [1]
    ov.set_dictation("listening")
    assert texto(ov) == "LISTENING" and ov.mic.cget("bg") == o.MIC_ON
    ov.set_dictation("idle", "typed ✓")
    assert texto(ov) == "typed ✓" and ov.mic.cget("bg") == o.MIC_BG
    ov._revert_at = time.monotonic() - 0.01
    ov._tick()
    assert texto(ov) == o.IDLE
    ov.close()



def test_preview_del_dictado_automatico(root):
    ov = o.Overlay(root, on_dictate=lambda: None)
    ov.set_dictation("preview", "hello there")
    root.update()
    assert texto(ov) == "blink to type"
    assert "hello there" in ov.preview.cget("text") and ov.preview.winfo_ismapped()
    assert ov.win.winfo_height() > 56
    ov.handle(EyeEvent(E.EYE_CLOSED))                       # el parpadeo para confirmar
    ov.set_dictation("idle", "typed ✓")
    root.update()
    assert texto(ov) == "typed ✓" and not ov.preview.winfo_ismapped()
    ov.close()
