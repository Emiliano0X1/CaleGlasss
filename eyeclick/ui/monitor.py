"""Monitor del ojo: ventana principal de la app.  (SWE 2, suscriptor del bus)

Todo en tkinter (en Mac una ventana de OpenCV no convive con tkinter).

Qué muestra:
    - Video del ojo (EyeView.frame, ya anotado por SWE 1) + miniatura de la máscara opcional.
    - Barra de progreso mientras está cerrado, marcas en LEFT_AT y RIGHT_AT
      (tramo izquierdo azul, derecho morado). Se vacía al abrir.
    - Estado en letras grandes (mismos colores que el overlay).
    - Contadores: clics izq., clics der., parpadeos ignorados, veces sin ojo.
    - Métricas: FPS, área de pupila vs calibrada, umbral.
    - Instrucciones de calibración en grande (EyeView.message).

Controles:
    slider umbral -> source.set_threshold | Recalibrar -> source.recalibrate
    Pausa (F9) | casilla máscara | Grabar video (para --video) | Modo demo (todo más grande)
    Reiniciar contadores (para la prueba de "2 minutos sin clics falsos")

Cómo se actualiza:
    1. Cada MONITOR_MS: source.latest_view(); si el t es igual al anterior, no redibujar.
    2. BGR -> RGB -> PIL.Image -> ImageTk.PhotoImage -> Label.
    3. GUARDAR la referencia a la PhotoImage en self (si no, sale en blanco).
    4. Estado/barra/métricas salen de la EyeView; contadores salen de handle(evento).
    5. Si t lleva > 1 s sin cambiar: "CÁMARA CONGELADA" en rojo.

Grabar usa los frames CRUDOS de la cámara (source.camera.latest()), no la vista
anotada, para que el video sirva con --video. Solo existe con PipelineSource; con
--mock el botón queda desactivado. Los frames se escriben a reloj fijo (los FPS de
la cámara): si la UI se atrasa se repite el último frame, así las duraciones de
los parpadeos en el video son las reales.

La pausa la decide app.py (MouseActions); el monitor solo pide el cambio con
on_pause() y app.py le avisa el estado nuevo con set_paused().

TODO (SWE 2):
- [ ] Probar con MockSource (--mock) cuando sources/mock.py esté listo.
- [ ] Probar Grabar con --camera y reproducir el resultado con --video.
"""
import logging
import time
import tkinter as tk
from datetime import datetime
from tkinter import font as tkfont

import numpy as np
from PIL import Image, ImageTk

from eyeclick.config import CANCEL_AT, LEFT_AT, MONITOR_MS, RIGHT_AT, VIEW_H, VIEW_W
from eyeclick.events import EventType as E
from eyeclick.ui.overlay import COLORS, GRAY, RED

log = logging.getLogger(__name__)

TYPES = None

BLUE, PURPLE = COLORS["IZQUIERDO"], COLORS["DERECHO"]
GREEN, YELLOW = COLORS["clic ✓"], COLORS["cerrado..."]
BG, PANEL, FG, DIM = "#1e1e1e", "#2a2a2a", "#eeeeee", "#9a9a9a"

FROZEN_S = 1.0          # sin vista nueva durante esto = cámara congelada
FLASH_S = 0.7           # cuánto se muestra "clic ✓" después de un clic
MIN_FPS = 15
DEMO_SCALE = 2          # el video se ve al doble en modo demo
DEMO_FONT = 1.8
BAR_H = 26
FONTS = {"status": (28, "bold"), "msg": (16, "bold"), "count": (13, "normal"), "small": (10, "normal")}
COUNTERS = [
    ("left", "Clics izquierdos"),
    ("right", "Clics derechos"),
    ("ignored", "Parpadeos ignorados"),
    ("lost", "Ojo perdido"),
]


def count_event(counts, ev):
    """Actualiza los contadores con un evento del bus."""
    if ev.type == E.CLICK_LEFT:
        counts["left"] += 1
    elif ev.type == E.CLICK_RIGHT:
        counts["right"] += 1
    elif ev.type == E.CANCELLED and ev.duration < LEFT_AT:
        counts["ignored"] += 1
    elif ev.type == E.EYE_LOST:
        counts["lost"] += 1


def status_of(view, now, flash=None):
    """(texto, color) del estado grande."""
    if view is None:
        return "ESPERANDO CÁMARA", GRAY
    if now - view.t > FROZEN_S:
        return "CÁMARA CONGELADA", RED
    if flash:
        return flash, GREEN
    if view.status == "lost":
        return "SIN OJO", RED
    if view.status == "closed":
        d = view.closed_for
        if d >= CANCEL_AT:
            return "descanso", GRAY
        if d >= RIGHT_AT:
            return "DERECHO", PURPLE
        if d >= LEFT_AT:
            return "IZQUIERDO", BLUE
        return "cerrado", YELLOW
    return "abierto", GRAY


def compose(view, show_mask=False, scale=1):
    """EyeView -> PIL.Image RGB, con la máscara en la esquina superior derecha si se pide."""
    frame = view.frame
    if frame.ndim == 2:
        frame = np.stack([frame] * 3, axis=-1)
    rgb = np.ascontiguousarray(frame[:, :, ::-1])       # BGR -> RGB (y copia: no tocar la vista)
    mask = view.mask
    if show_mask and mask is not None:
        h, w = mask.shape[:2]
        if h < rgb.shape[0] and w < rgb.shape[1]:
            rgb[: h + 2, -(w + 2):] = 255                # marco blanco
            rgb[1 : h + 1, -(w + 1) : -1] = mask[..., None] if mask.ndim == 2 else mask[:, :, ::-1]
    img = Image.fromarray(rgb)
    if scale != 1:
        img = img.resize((img.width * scale, img.height * scale), Image.BILINEAR)
    return img


class Recorder:
    """Graba los frames crudos de la cámara a reloj fijo, para usarlos con --video."""

    def __init__(self, camera, open_writer=None):
        self.camera = camera
        self.open_writer = open_writer or _cv2_writer
        self.out = None
        self.path = None
        self.started = 0.0
        self.frames = 0
        self.fps = 30.0

    @property
    def active(self):
        return self.out is not None

    def start(self, now):
        frame, _ = self.camera.latest()
        if frame is None:
            raise RuntimeError("La cámara todavía no entrega imágenes")
        h, w = frame.shape[:2]
        self.fps = float(round(getattr(self.camera, "fps", 0) or 30.0))
        self.path = datetime.now().strftime("ojo_%Y%m%d_%H%M%S.mp4")
        self.out = self.open_writer(self.path, self.fps, (w, h))
        self.started, self.frames = now, 0

    def poll(self, now):
        if self.out is None:
            return
        frame, _ = self.camera.latest()
        if frame is None:
            return
        due = int((now - self.started) * self.fps) + 1
        while self.frames < due:
            self.out.write(frame)
            self.frames += 1

    def stop(self):
        if self.out is not None:
            self.out.release()
            self.out = None
        return self.path


def _cv2_writer(path, fps, size):
    import cv2      # aquí y no arriba: --mock no necesita OpenCV
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    if not out.isOpened():
        raise RuntimeError(f"No se pudo crear {path}")
    return out


class Monitor:
    def __init__(self, root, source, on_pause, demo=False):
        self.root = root
        self.source = source            # cualquier fuente: pipeline o mock
        self.on_pause = on_pause
        self.demo = demo
        self.counts = {key: 0 for key, _ in COUNTERS}
        self._photo = None              # referencia a la PhotoImage (¡no borrar!)
        self._photo_size = None
        self._last_t = None
        self._flash, self._flash_until = None, 0.0
        self._paused = False
        self._dragging = False
        self._thr_pending = None        # (valor, hasta) mientras la fuente aplica el slider
        self._after_id = None
        self._last_error = None
        self._scale = 1
        camera = getattr(source, "camera", None)
        self.recorder = Recorder(camera) if hasattr(camera, "latest") else None
        self.show_mask = tk.BooleanVar(master=root, value=False)
        self.fonts = {name: tkfont.Font(root=root, family="Helvetica", size=size, weight=weight)
                      for name, (size, weight) in FONTS.items()}
        self._build()
        self._apply_demo()
        self._refresh()

    # --- interfaz para app.py ---
    def handle(self, ev):
        count_event(self.counts, ev)
        for key, _ in COUNTERS:
            self.count_labels[key].config(text=str(self.counts[key]))
        if ev.type in (E.CLICK_LEFT, E.CLICK_RIGHT):
            self._flash = "clic ✓" if ev.type == E.CLICK_LEFT else "clic derecho ✓"
            self._flash_until = time.monotonic() + FLASH_S

    def set_paused(self, paused):
        self._paused = paused
        self.pause_btn.config(text="Reanudar (F9)" if paused else "Pausa (F9)")
        if paused:
            self.pause_lbl.pack(fill="x", after=self.message)
        else:
            self.pause_lbl.pack_forget()

    def close(self):
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self.recorder is not None and self.recorder.active:
            log.info("Video guardado en %s", self.recorder.stop())

    # --- construcción ---
    def _build(self):
        f = self.fonts
        self.root.configure(bg=BG)

        left = tk.Frame(self.root, bg=BG)
        left.grid(row=0, column=0, padx=12, pady=12, sticky="n")
        self.video = tk.Label(left, bg="black", bd=0)
        self.video.pack()
        self.bar = tk.Canvas(left, bg=BG, highlightthickness=0)
        self.bar.pack(fill="x", pady=(8, 0))

        right = tk.Frame(self.root, bg=BG)
        right.grid(row=0, column=1, padx=(0, 12), pady=12, sticky="n")
        self.status = tk.Label(right, font=f["status"], fg="white", bg=GRAY, width=16, pady=8)
        self.status.pack(fill="x")
        self.message = tk.Label(right, font=f["msg"], fg=YELLOW, bg=BG, wraplength=340, justify="left")
        self.message.pack(fill="x", pady=(6, 0))
        self.pause_lbl = tk.Label(right, font=f["msg"], fg=RED, bg=BG, text="PAUSA: no hace clics")
        # se muestra solo en pausa (set_paused), debajo del mensaje

        counters = tk.Frame(right, bg=PANEL, padx=10, pady=8)
        counters.pack(fill="x", pady=(6, 0))
        self.count_labels = {}
        for row, (key, text) in enumerate(COUNTERS):
            tk.Label(counters, text=text, font=f["count"], fg=FG, bg=PANEL, anchor="w").grid(
                row=row, column=0, sticky="w")
            self.count_labels[key] = tk.Label(counters, text="0", font=f["count"], fg="white", bg=PANEL)
            self.count_labels[key].grid(row=row, column=1, sticky="e", padx=(16, 0))
        counters.columnconfigure(0, weight=1)

        self.metrics = tk.Label(right, font=f["small"], fg=DIM, bg=BG, anchor="w", justify="left")
        self.metrics.pack(fill="x", pady=(6, 0))

        controls = tk.Frame(right, bg=BG)
        controls.pack(fill="x", pady=(8, 0))
        tk.Label(controls, text="Umbral", font=f["small"], fg=FG, bg=BG).pack(anchor="w")
        self.thr = tk.Scale(controls, from_=0, to=255, orient="horizontal", command=self._on_threshold,
                            bg=BG, fg=FG, troughcolor=PANEL, highlightthickness=0, font=f["small"])
        self.thr.pack(fill="x")
        self.thr.bind("<ButtonPress-1>", lambda _e: self._set_dragging(True))
        self.thr.bind("<ButtonRelease-1>", lambda _e: self._set_dragging(False))
        tk.Checkbutton(controls, text="Mostrar máscara", variable=self.show_mask, font=f["small"],
                       fg=FG, bg=BG, selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                       command=self._redraw).pack(anchor="w")

        buttons = tk.Frame(controls, bg=BG)
        buttons.pack(fill="x", pady=(6, 0))
        btn = {"font": f["small"], "width": 19}
        tk.Button(buttons, text="Recalibrar", command=self.source.recalibrate, **btn).grid(row=0, column=0, pady=2)
        self.pause_btn = tk.Button(buttons, text="Pausa (F9)", command=self.on_pause, **btn)
        self.pause_btn.grid(row=0, column=1, padx=(6, 0), pady=2)
        self.rec_btn = tk.Button(buttons, text="Grabar", command=self._toggle_record, **btn)
        self.rec_btn.grid(row=1, column=0, pady=2)
        if self.recorder is None:
            self.rec_btn.config(state="disabled", text="Grabar (sin cámara)")
        self.demo_btn = tk.Button(buttons, command=self._toggle_demo, **btn)
        self.demo_btn.grid(row=1, column=1, padx=(6, 0), pady=2)
        tk.Button(buttons, text="Reiniciar contadores", command=self._reset_counts, **btn).grid(
            row=2, column=0, pady=2)
        self.rec_lbl = tk.Label(controls, font=f["small"], fg=DIM, bg=BG, anchor="w")
        self.rec_lbl.pack(fill="x", pady=(4, 0))

    # --- actualización ---
    def _refresh(self):
        self._after_id = self.root.after(MONITOR_MS, self._refresh)
        try:
            now = time.monotonic()
            view = self.source.latest_view()
            if view is not None and view.t != self._last_t:
                self._last_t = view.t
                self._draw(view)
            flash = self._flash if now < self._flash_until else None
            text, color = status_of(view, now, flash)
            self.status.config(text=text, bg=color)
            if self.recorder is not None and self.recorder.active:
                self.recorder.poll(now)
                self.rec_lbl.config(text=f"● REC {now - self.recorder.started:.0f} s", fg=RED)
            self._last_error = None
        except Exception as e:
            if repr(e) != self._last_error:     # no llenar el log con el mismo error a 30 Hz
                self._last_error = repr(e)
                log.exception("Error al actualizar el monitor")

    def _draw(self, view):
        img = compose(view, self.show_mask.get(), self._scale)
        if self._photo is not None and self._photo_size == img.size:
            self._photo.paste(img)
        else:
            self._photo = ImageTk.PhotoImage(img, master=self.root)
            self._photo_size = img.size
            self.video.config(image=self._photo)
        self._draw_bar(view.closed_for if view.status == "closed" else 0.0)
        self.message.config(text=view.message)
        self._sync_threshold(view.thr)
        low = 0 < view.fps < MIN_FPS
        self.metrics.config(
            text=f"FPS {view.fps:.0f}{'  (bajo)' if low else ''}    "
                 f"pupila {view.pupil_area:.0f} / {view.open_area:.0f}    umbral {view.thr}",
            fg=RED if low else DIM)

    def _draw_bar(self, d):
        c, w, h = self.bar, VIEW_W * self._scale, BAR_H * self._scale
        c.delete("all")

        def x(s):
            return round(w * min(s, CANCEL_AT) / CANCEL_AT)

        for a, b, color in ((0.0, LEFT_AT, YELLOW), (LEFT_AT, RIGHT_AT, BLUE), (RIGHT_AT, CANCEL_AT, PURPLE)):
            c.create_rectangle(x(a), 0, x(b), h, fill=PANEL, outline="")
            if d > a:
                c.create_rectangle(x(a), 0, x(min(d, b)), h, fill=color, outline="")
        for s in (LEFT_AT, RIGHT_AT):
            c.create_line(x(s), 0, x(s), h + 4, fill=FG)
            c.create_text(x(s), h + 4, text=f"{s:g} s", anchor="n", fill=FG, font=self.fonts["small"])
        if d > 0:
            c.create_text(w - 6, h // 2, text=f"{d:.1f} s", anchor="e", fill="white", font=self.fonts["small"])

    def _redraw(self):
        self._last_t = None     # forzar redibujo con el siguiente refresh

    # --- umbral ---
    def _set_dragging(self, dragging):
        self._dragging = dragging

    def _on_threshold(self, value):
        value = int(float(value))
        if self._thr_pending is None and value == self._view_thr():
            return              # lo movió _sync_threshold, no el usuario
        self._thr_pending = (value, time.monotonic() + 1.0)
        self.source.set_threshold(value)

    def _view_thr(self):
        view = self.source.latest_view()
        return None if view is None else view.thr

    def _sync_threshold(self, thr):
        if self._thr_pending is not None:
            value, until = self._thr_pending
            if thr == value or time.monotonic() > until:
                self._thr_pending = None
            return
        if not self._dragging and int(self.thr.get()) != thr:
            self.thr.set(thr)

    # --- botones ---
    def _toggle_record(self):
        if self.recorder.active:
            path = self.recorder.stop()
            self.rec_btn.config(text="Grabar")
            self.rec_lbl.config(text=f"Guardado: {path}", fg=DIM)
            log.info("Video guardado en %s", path)
            return
        try:
            self.recorder.start(time.monotonic())
        except Exception as e:
            log.warning("No se pudo grabar: %s", e)
            self.rec_lbl.config(text=f"No se pudo grabar: {e}", fg=RED)
            return
        self.rec_btn.config(text="Detener")

    def _toggle_demo(self):
        self.demo = not self.demo
        self._apply_demo()

    def _apply_demo(self):
        self._scale = DEMO_SCALE if self.demo else 1
        k = DEMO_FONT if self.demo else 1
        for name, (size, _) in FONTS.items():
            self.fonts[name].configure(size=round(size * k))
        self.message.config(wraplength=round(340 * k))
        label_h = self.fonts["small"].metrics("linespace") + 6     # espacio para "0.5 s" / "1.2 s"
        self.bar.config(width=VIEW_W * self._scale, height=BAR_H * self._scale + label_h)
        # imagen negra del tamaño nuevo: el video ocupa su lugar aunque todavía no haya vista
        self._photo = ImageTk.PhotoImage(Image.new("RGB", (VIEW_W * self._scale, VIEW_H * self._scale)),
                                         master=self.root)
        self._photo_size = (VIEW_W * self._scale, VIEW_H * self._scale)
        self.video.config(image=self._photo)
        self.demo_btn.config(text="Salir de demo" if self.demo else "Modo demo")
        self._draw_bar(0.0)
        self._redraw()

    def _reset_counts(self):
        for key in self.counts:
            self.counts[key] = 0
            self.count_labels[key].config(text="0")
