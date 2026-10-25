"""Pruebas del monitor.  (SWE 2)

Las funciones (contadores, estado, imagen, grabación) se prueban sin ventana.
La prueba de la ventana real se salta si no hay pantalla.
"""
import time

import numpy as np
import pytest

from eyeclick.config import LEFT_AT, RIGHT_AT, VIEW_H, VIEW_W
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent, EyeView
from eyeclick.ui import monitor as m


def view(status="open", closed_for=0.0, t=100.0, mask=None, thr=50):
    return EyeView(frame=np.zeros((VIEW_H, VIEW_W, 3), np.uint8), status=status,
                   closed_for=closed_for, t=t, mask=mask, thr=thr)


# --- contadores ---
def test_contadores():
    counts = {"left": 0, "right": 0, "ignored": 0, "lost": 0}
    for ev in (EyeEvent(E.CLICK_LEFT), EyeEvent(E.CLICK_RIGHT), EyeEvent(E.CLICK_LEFT),
               EyeEvent(E.CANCELLED, duration=0.2),     # parpadeo natural
               EyeEvent(E.CANCELLED, duration=1.0),     # se perdió la imagen: no es parpadeo
               EyeEvent(E.EYE_LOST), EyeEvent(E.EYE_CLOSED)):
        m.count_event(counts, ev)
    assert counts == {"left": 2, "right": 1, "ignored": 1, "lost": 1}


# --- estado grande ---
@pytest.mark.parametrize("v, texto", [
    (None, "WAITING FOR CAMERA"),
    (view("open"), "open"),
    (view("lost"), "NO EYE"),
    (view("closed", 0.2), "closed"),
    (view("closed", LEFT_AT + 0.1), "LEFT"),
    (view("closed", RIGHT_AT + 0.1), "RIGHT"),
    (view("closed", 3.5), "DRAGGING: open eye to drop"),
])
def test_estado(v, texto):
    assert m.status_of(v, now=100.1)[0] == texto


def test_camara_congelada_y_flash():
    assert m.status_of(view(t=100.0), now=100.0 + m.FROZEN_S + 0.1)[0] == "CAMERA FROZEN"
    assert m.status_of(view(), now=100.1, flash="click ✓") == ("click ✓", m.GREEN)


def test_estado_de_arrastre_con_el_ojo_abierto():
    assert m.status_of(view("open"), now=100.1, drag="armed") == (m.DRAG_TEXT["armed"], m.YELLOW)
    assert m.status_of(view("open"), now=100.1, drag="holding")[0] == m.DRAG_TEXT["holding"]
    assert m.status_of(view("closed", LEFT_AT + 0.1), now=100.1, drag="holding")[0] == "LEFT"


# --- imagen ---
def test_compose_bgr_a_rgb_sin_tocar_la_vista():
    v = view()
    v.frame[:, :, 0] = 255                              # azul en BGR
    img = m.compose(v)
    assert img.size == (VIEW_W, VIEW_H)
    assert img.getpixel((5, 5)) == (0, 0, 255)          # azul en RGB
    assert v.frame[5, 5, 0] == 255                      # la vista original sigue igual


def test_compose_mascara_y_escala():
    mask = np.full((60, 80), 255, np.uint8)
    img = m.compose(view(mask=mask), show_mask=True, scale=2)
    assert img.size == (VIEW_W * 2, VIEW_H * 2)
    assert img.getpixel((VIEW_W * 2 - 20, 20)) == (255, 255, 255)   # esquina con máscara
    assert m.compose(view(mask=mask)).getpixel((VIEW_W - 10, 10)) == (0, 0, 0)  # oculta


# --- grabación ---
class FakeCamera:
    fps = 30.0

    def __init__(self):
        self.frame = np.zeros((480, 640, 3), np.uint8)

    def latest(self):
        return self.frame, 1.0


class FakeWriter:
    def __init__(self, path, fps, size):
        self.args, self.frames, self.released = (path, fps, size), 0, False

    def write(self, frame):
        self.frames += 1

    def release(self):
        self.released = True


def test_grabacion_a_reloj_fijo():
    rec = m.Recorder(FakeCamera(), open_writer=FakeWriter)
    rec.start(now=10.0)
    writer = rec.out
    assert writer.args[1:] == (30.0, (640, 480))
    rec.poll(10.0)
    rec.poll(11.0)          # la UI se atrasó 1 s: igual hay ~30 frames por segundo
    assert writer.frames == 31
    assert rec.stop().endswith(".mp4") and writer.released and not rec.active


def test_grabacion_sin_imagen_falla_claro():
    cam = FakeCamera()
    cam.frame = None
    with pytest.raises(RuntimeError):
        m.Recorder(cam, open_writer=FakeWriter).start(now=0.0)


# --- ventana real ---
class FakeSource:
    def __init__(self):
        self.v, self.thr_calls, self.recal = view(t=time.monotonic()), [], 0

    def latest_view(self):
        return self.v

    def set_threshold(self, value):
        self.thr_calls.append(value)

    def recalibrate(self):
        self.recal += 1



def test_ventana(root):
    src, pauses = FakeSource(), []
    mon = m.Monitor(root, src, on_pause=lambda: pauses.append(1))
    mon._refresh()
    assert mon.status.cget("text") == "open"
    assert int(mon.thr.get()) == 50

    src.v = view("closed", RIGHT_AT + 0.1, t=time.monotonic())
    mon._refresh()
    assert mon.status.cget("text") == "RIGHT"
    mon.handle(EyeEvent(E.CLICK_RIGHT, duration=1.5))
    assert mon.count_labels["right"].cget("text") == "1"

    mon.pause_btn.invoke()
    assert pauses == [1]
    mon.set_paused(True)
    assert mon.stage.itemcget(mon.pause_lbl.item, "state") == "normal"
    mon.set_paused(False)
    assert mon.stage.itemcget(mon.pause_lbl.item, "state") == "hidden"
    assert str(mon.rec_btn.cget("state")) == "disabled"     # FakeSource no tiene cámara

    mon._layout(2.0, 0, 0)                                  # ventana más grande: todo se escala
    assert mon._photo_size == ((m.EYE_BOX[2] - m.EYE_BOX[0]) * 2, (m.EYE_BOX[3] - m.EYE_BOX[1]) * 2)
    assert mon.count_labels["right"].cget("text") == "1"    # sobrevive al redibujo
    mon._refresh()                                          # dibuja el video al tamaño nuevo
    fullscreen = []                                         # sin pantalla completa real en las pruebas
    mon.root.attributes = lambda *args: fullscreen.append(args)
    mon._toggle_demo()
    assert fullscreen == [("-fullscreen", True)]
    assert mon.demo
    mon._toggle_demo()
    mon.close()


def test_estado_del_dictado():
    assert m.status_of(view("open"), now=100.1, dictation="listening") == (m.DICTATION_TEXT["listening"], m.PINK)
    assert m.status_of(view("open"), now=100.1, dictation="transcribing", drag="armed")[0] == "TYPING..."
    assert m.status_of(view("open"), now=100.1, dictation="idle")[0] == "open"



def test_preview_en_el_monitor():
    assert m.status_of(view("open"), now=100.1, dictation="preview") == (m.DICTATION_TEXT["preview"], m.GREEN)
