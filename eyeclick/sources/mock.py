"""Simulador del ojo: F8 sostenida = ojo cerrado, F7 sostenida = sin ojo.  (SWE 2)

F9 (pausa) NO va aquí: lo escucha app.py en todos los modos.

Cumple la MISMA interfaz de fuente que vision/pipeline.py:
    start(), stop(), latest_view() -> EyeView | None,
    recalibrate(), set_threshold(valor)

Un hilo alimenta la misma BlinkFSM de SWE 1 60 veces por segundo, así los eventos
son idénticos a los reales. latest_view() devuelve una EyeView falsa (imagen gris
con una "pupila" y el estado escrito) para poder probar el monitor sin cámara.
La imagen se dibuja con Pillow: --mock no necesita OpenCV.

Las teclas se escuchan con pynput en todo el sistema, así F8 funciona aunque el
foco esté en otra app (que es justo donde se quiere hacer clic). Sin pynput o sin
permisos (Mac: Monitoreo de entrada), el simulador arranca igual y lo avisa.

recalibrate() imita al pipeline: durante CALIBRATE_S no alimenta la FSM (cancela
un cierre en curso), muestra el mensaje y al final publica CALIBRATED.
"""
import logging
import threading
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from eyeclick.config import VIEW_H, VIEW_W
from eyeclick.events import EventType, EyeEvent, EyeView
from eyeclick.logic.blink_fsm import BlinkFSM

log = logging.getLogger(__name__)

HZ = 60
CALIBRATE_S = 1.0
OPEN_AREA = 1500.0
MASK_W, MASK_H = 80, 60
BG_GRAY = 80


def _font(size):
    try:
        return ImageFont.load_default(size)
    except TypeError:               # Pillow < 10.1 no acepta tamaño
        return ImageFont.load_default()


FONT_BIG, FONT_SMALL = _font(28), _font(14)


def pupil_radius(thr):
    """Radio de la pupila falsa: crece con el umbral, para que el slider se note."""
    return int(np.clip(8 + thr * 0.25, 8, 70))


def fake_view(status, closed_for, thr, fps, message, t):
    """EyeView falsa: gris, pupila oscura si está abierto, estado escrito."""
    img = Image.new("RGB", (VIEW_W, VIEW_H), (BG_GRAY,) * 3)
    d = ImageDraw.Draw(img)
    cx, cy, r = VIEW_W // 2, VIEW_H // 2, pupil_radius(thr)
    if status == "open":
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(20, 20, 20), outline=(0, 200, 0), width=2)
    elif status == "closed":
        d.line((cx - 70, cy, cx + 70, cy), fill=(30, 30, 30), width=6)     # párpado
    label = {"open": "ABIERTO", "closed": f"CERRADO {closed_for:.1f} s", "lost": "SIN OJO"}[status]
    d.text((10, 8), label, fill="white", font=FONT_BIG, stroke_width=2, stroke_fill="black")
    d.text((10, VIEW_H - 24), "SIMULADOR  F8 cerrar  F7 sin ojo", fill="white", font=FONT_SMALL,
           stroke_width=1, stroke_fill="black")
    frame = np.asarray(img)[:, :, ::-1].copy()          # RGB -> BGR, como la cámara

    mask = None
    area = 0.0
    if status == "open":
        m = Image.new("L", (MASK_W, MASK_H), 0)
        mr = r * MASK_W / VIEW_W
        ImageDraw.Draw(m).ellipse((MASK_W / 2 - mr, MASK_H / 2 - mr, MASK_W / 2 + mr, MASK_H / 2 + mr), fill=255)
        mask = np.asarray(m).copy()
        area = float(np.pi * r * r)
    elif status == "closed":
        mask = np.zeros((MASK_H, MASK_W), np.uint8)
    return EyeView(frame=frame, status=status, mask=mask, closed_for=closed_for, pupil_area=area,
                   open_area=OPEN_AREA, thr=thr, fps=fps, message=message, t=t)


def _pynput_listener(on_press, on_release):
    from pynput import keyboard
    keys = {keyboard.Key.f8: "f8", keyboard.Key.f7: "f7"}
    listener = keyboard.Listener(on_press=lambda k: on_press(keys.get(k)),
                                 on_release=lambda k: on_release(keys.get(k)), daemon=True)
    listener.start()
    return listener


class MockSource:
    def __init__(self, publish, make_listener=_pynput_listener):
        self.publish = publish
        self.make_listener = make_listener      # se reemplaza en las pruebas
        self.fsm = BlinkFSM(publish)
        self._closed = False
        self._lost = False
        self._thr = 50
        self._view: EyeView | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._listener = None
        self._want_recalibrate = False
        self._calibrate_until = None
        self.fps = 0.0

    # --- interfaz de fuente ---
    def start(self):
        try:
            self._listener = self.make_listener(self._on_press, self._on_release)
        except Exception:
            log.warning("Sin teclado global (pynput): F8/F7 no funcionan", exc_info=True)
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="mock", daemon=True)
        self._thread.start()
        self.publish(EyeEvent(EventType.CALIBRATED))
        log.info("Simulador listo: mantén F8 para cerrar el ojo, F7 para 'sin ojo'")

    def stop(self):
        self._running = False
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def latest_view(self) -> EyeView | None:
        with self._lock:
            return self._view

    def recalibrate(self):
        with self._lock:
            self._want_recalibrate = True

    def set_threshold(self, value):
        with self._lock:
            self._thr = int(np.clip(int(value), 0, 255))

    # --- también se pueden usar directo (pruebas, botones) ---
    def set_closed(self, closed):
        self._closed = closed

    def set_lost(self, lost):
        self._lost = lost

    # --- teclas (hilo de pynput) ---
    def _on_press(self, key):
        if key == "f8":
            self._closed = True
        elif key == "f7":
            self._lost = True

    def _on_release(self, key):
        if key == "f8":
            self._closed = False
        elif key == "f7":
            self._lost = False

    # --- hilo ---
    def _loop(self):
        period = 1.0 / HZ
        next_t = time.monotonic()
        n, t_fps = 0, next_t
        while self._running:
            t = time.monotonic()
            try:
                self.step(t)
            except Exception:
                log.exception("Error en el simulador")
            n += 1
            if t - t_fps >= 1.0:
                self.fps, n, t_fps = n / (t - t_fps), 0, t
            next_t += period
            time.sleep(max(0.0, next_t - time.monotonic()))

    def step(self, t):
        """Un tick del simulador. Público para probarlo sin hilo ni reloj real."""
        with self._lock:
            recalibrate, self._want_recalibrate = self._want_recalibrate, False
            thr = self._thr
        if recalibrate:
            self.fsm.reset(t)
            self._calibrate_until = t + CALIBRATE_S

        status = "lost" if self._lost else "closed" if self._closed else "open"
        message = ""
        if self._calibrate_until is not None:
            if t < self._calibrate_until:
                message = "Calibrando (simulado)..."
            else:
                self._calibrate_until = None
                self.publish(EyeEvent(EventType.CALIBRATED, t))
        if self._calibrate_until is None:
            self.fsm.update(status, t)

        view = fake_view(status, self.fsm.closed_for(t), thr, self.fps, message, t)
        with self._lock:
            self._view = view
