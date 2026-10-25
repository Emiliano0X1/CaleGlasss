"""Monitor del ojo: ventana principal de la app.  (SWE 2, suscriptor del bus)

Todo en tkinter (en Mac una ventana de OpenCV no convive con tkinter).

Diseño "CALEglass": todo se dibuja en un Canvas de 1366x768 (coordenadas del
diseño) que se escala para llenar la ventana. Si existe ui/assets/glasses.png
(la imagen de los lentes del diseño) se dibuja detrás de los paneles.

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
    Pausa (F9) | máscara (esquina del video) | Grabar video (para --video) | Demo (pantalla completa)
    Contador = reiniciar contadores (para la prueba de "2 minutos sin clics falsos")

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
Igual con arrastrar: el botón Drag llama on_drag() y app.py avisa con set_drag().
El dictado se arranca desde el indicador flotante (no roba el foco); aquí solo se
muestra su estado con set_dictation().

TODO (SWE 2):
- [ ] Probar con MockSource (--mock) cuando sources/mock.py esté listo.
- [ ] Probar Grabar con --camera y reproducir el resultado con --video.
"""
import logging
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont

import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageTk

from eyeclick.config import DRAG_AT, LEFT_AT, MONITOR_MS, RIGHT_AT
from eyeclick.events import EventType as E

log = logging.getLogger(__name__)

TYPES = None

# --- paleta del diseño ---
BG, INK, CALE, PANEL = "#4BB5D1", "#FFFCF3", "#93D1DE", "#7F7682"
YELLOW, PINK, SKY = "#FFEE78", "#EDA7C3", "#BEF2FF"
DARK, RED, GREEN = "#2B2830", "#E5484D", "#7BD88F"
GRAY = PANEL
BLUE, PURPLE = SKY, PINK            # izquierdo / derecho (mismos colores en barra y estado)
LIGHT = {YELLOW, PINK, SKY, GREEN}  # fondos claros: texto oscuro encima

STAGE_W, STAGE_H = 1366, 768        # tamaño del diseño; todo se escala desde aquí
EYE_BOX = (184, 345, 699, 646)  # el video llena este marco blanco (esquinas redondeadas)
EYE_R = 30                      # radio de las esquinas del marco
ASSETS = Path(__file__).parent / "assets"
GLASSES = ASSETS / "glasses.png"
FONT_FILE = ASSETS / "open-sauce.two-light.ttf"
FAMILIES = ("Open Sauce Two Light", "Open Sauce Two", "Segoe UI", "Helvetica Neue", "Helvetica", "Arial")

BAR_END = DRAG_AT + 0.75   # la barra sigue un poco después: el tramo verde es "arrastrando"
FROZEN_S = 1.0          # sin vista nueva durante esto = cámara congelada
FLASH_S = 0.7           # cuánto se muestra "clic ✓" después de un clic
MIN_FPS = 15
FONTS = {               # nombre: (px en el diseño, peso, inclinación)
    "cale": (162, "normal", "roman"), "stats": (19, "normal", "roman"),
    "eye": (33, "normal", "italic"), "row": (28, "normal", "roman"),
    "btn": (21, "normal", "roman"), "status": (28, "bold", "roman"),
    "msg": (22, "bold", "roman"), "small": (15, "normal", "roman"),
    "umbral": (18, "normal", "italic"),
}
DRAG_TEXT = {"armed": "DRAG: blink to grab", "holding": "DRAGGING: blink to drop"}
DICTATION_TEXT = {"listening": "LISTENING: speak now", "transcribing": "TYPING...", "typing": "TYPING...",
                  "preview": "LEFT blink = type · RIGHT = discard"}
COUNTERS = [
    ("left", "Left clicks"),
    ("right", "Right clicks"),
    ("ignored", "Ignored blinks"),
    ("lost", "Eye lost"),
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


def status_of(view, now, flash=None, drag=None, dictation=None, gyro=None):
    """(texto, color) del estado grande. Con el ojo abierto mandan el dictado y el arrastre."""
    if view is None:
        return "WAITING FOR CAMERA", GRAY
    if now - view.t > FROZEN_S:
        return "CAMERA FROZEN", RED
    if flash:
        failed = "not calibrated" in flash or flash.startswith("could not")
        return flash, RED if failed else GREEN
    if gyro:
        return "GYRO: hold still...", YELLOW
    if view.status == "lost":
        return "NO EYE", RED
    if view.status == "closed":
        d = view.closed_for
        if d >= DRAG_AT:
            return "DRAGGING: open eye to drop", GREEN
        if d >= RIGHT_AT:
            return "RIGHT", PURPLE
        if d >= LEFT_AT:
            return "LEFT", BLUE
        return "closed", YELLOW
    if dictation in DICTATION_TEXT:
        color = {"listening": PINK, "preview": GREEN}.get(dictation, YELLOW)
        return DICTATION_TEXT[dictation], color
    if drag in DRAG_TEXT:
        return DRAG_TEXT[drag], YELLOW
    return "open", GRAY


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




def _round_rect(c, x1, y1, x2, y2, r, **kw):
    """Rectángulo redondeado en un Canvas (polígono suavizado)."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def _blend(color, k=0.45):
    """Mezcla un color con el fondo (para la parte vacía de la barra)."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(BG[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * k + y * (1 - k)):02x}" for x, y in zip(a, b))


def _load_font_file(path):
    """Registra el .ttf solo para este proceso (Windows) para que tkinter lo vea.
    En otros sistemas, o si falla, se usa la siguiente fuente de FAMILIES."""
    try:
        import ctypes
        ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0)     # 0x10 = FR_PRIVATE
    except Exception:
        log.info("Fuente %s no disponible; se usa otra", path.name)


def _rounded_mask(size, r):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=r, fill=255)
    return mask


def _shade(size, top, bottom):
    """Capa negra semitransparente arriba y abajo del video, para leer el texto encima."""
    w, h = size
    alpha = Image.new("L", size, 0)
    d = ImageDraw.Draw(alpha)
    for y in range(top):
        d.line((0, y, w, y), fill=round(110 * (1 - y / top)))
    for y in range(bottom):
        d.line((0, h - 1 - y, w, h - 1 - y), fill=round(150 * (1 - y / bottom)))
    shade = Image.new("RGBA", size, (0, 0, 0, 0))
    shade.putalpha(alpha)
    return shade


class _Slider:
    """Slider vertical redondeado dibujado en el Canvas (arriba = 255, abajo = 0).
    get()/set() como tk.Scale; command(valor) solo cuando lo mueve el usuario."""

    def __init__(self, command, on_drag, lo=0, hi=255):
        self.command, self.on_drag, self.lo, self.hi = command, on_drag, lo, hi
        self.value = lo
        self.canvas = None

    def get(self):
        return self.value

    def set(self, value):
        self.value = max(self.lo, min(self.hi, int(value)))
        self._draw_knob()

    def attach(self, canvas, box, knob_h, r):
        self.canvas, self.box, self.knob_h, self.r = canvas, box, knob_h, r
        _round_rect(canvas, *box, r, fill=PANEL, outline="", tags=("slider",))
        self._draw_knob()
        canvas.tag_bind("slider", "<ButtonPress-1>", self._press)
        canvas.tag_bind("slider", "<B1-Motion>", self._move)
        canvas.tag_bind("slider", "<ButtonRelease-1>", self._release)
        canvas.tag_bind("slider", "<Enter>", lambda _e: canvas.config(cursor="sb_v_double_arrow"))
        canvas.tag_bind("slider", "<Leave>", lambda _e: canvas.config(cursor=""))

    def _draw_knob(self):
        if self.canvas is None:
            return
        x1, y1, x2, y2 = self.box
        span = (y2 - y1) - self.knob_h
        top = y1 + span * (self.hi - self.value) / (self.hi - self.lo)
        self.canvas.delete("slider_knob")
        _round_rect(self.canvas, x1, top, x2, top + self.knob_h, self.r, fill=YELLOW, outline="",
                    tags=("slider", "slider_knob"))

    def _value_at(self, y):
        x1, y1, x2, y2 = self.box
        span = (y2 - y1) - self.knob_h
        frac = (y - y1 - self.knob_h / 2) / span if span > 0 else 0
        return round(self.hi - max(0.0, min(1.0, frac)) * (self.hi - self.lo))

    def _press(self, event):
        self.on_drag(True)
        self._move(event)

    def _move(self, event):
        value = self._value_at(event.y)
        if value != self.value:
            self.set(value)
            self.command(value)

    def _release(self, _event):
        self.on_drag(False)


class _Text:
    """Texto dibujado en el Canvas con interfaz de Label (config/cget), para que el
    resto del monitor (y las pruebas) no dependan de cómo se dibuja."""

    def __init__(self, text="", fill=INK):
        self.text, self.fill, self.bg = text, fill, None
        self.visible = True
        self.canvas = self.item = self.bg_item = None

    def attach(self, canvas, item, bg_item=None):
        self.canvas, self.item, self.bg_item = canvas, item, bg_item
        self._apply()

    def config(self, text=None, fill=None, bg=None):
        if text is not None:
            self.text = text
        if fill is not None:
            self.fill = fill
        if bg is not None:
            self.bg = bg
        self._apply()

    configure = config

    def cget(self, key):
        return {"text": self.text, "fill": self.fill, "bg": self.bg}[key]

    def show(self, visible):
        self.visible = visible
        self._apply()

    def _apply(self):
        if self.canvas is None:
            return
        state = "normal" if self.visible else "hidden"
        self.canvas.itemconfigure(self.item, text=self.text, fill=self.fill, state=state)
        if self.bg_item is not None and self.bg is not None:
            self.canvas.itemconfigure(self.bg_item, fill=self.bg, state=state)


class _Button(_Text):
    """Botón de texto plano del panel (como en el diseño), con invoke() y state."""

    def __init__(self, text, command):
        super().__init__(text)
        self.command, self.state, self.active = command, "normal", False

    def attach(self, canvas, item, bg_item=None):
        super().attach(canvas, item, bg_item)
        tag = f"btn{id(self)}"
        canvas.addtag_withtag(tag, item)
        canvas.tag_bind(tag, "<Button-1>", lambda _e: self.invoke())
        canvas.tag_bind(tag, "<Enter>", lambda _e: canvas.config(
            cursor="hand2" if self.state == "normal" else ""))
        canvas.tag_bind(tag, "<Leave>", lambda _e: canvas.config(cursor=""))

    def invoke(self):
        if self.state == "normal":
            self.command()

    def config(self, text=None, state=None, active=None, **kw):
        if state is not None:
            self.state = state
        if active is not None:
            self.active = active
        fill = "#B9B2BC" if self.state != "normal" else (YELLOW if self.active else INK)
        super().config(text=text, fill=fill)

    def cget(self, key):
        return self.state if key == "state" else super().cget(key)


class Monitor:
    def __init__(self, root, source, on_pause, on_drag=None, demo=False):
        self.root = root
        self.source = source            # cualquier fuente: pipeline o mock
        self.on_pause = on_pause
        self.on_drag = on_drag or (lambda: None)
        self.drag = None                # estado del arrastre que avisa app.py
        self.dictation = "idle"
        self.preview = None             # texto dictado esperando el parpadeo
        self.gyro = None                # "calibrating" mientras el ESP32 se calibra
        self.demo = False
        self.counts = {key: 0 for key, _ in COUNTERS}
        self._photo = None              # referencia a la PhotoImage (¡no borrar!)
        self._photo_size = None
        self._last_t = None
        self._flash, self._flash_until = None, 0.0
        self._paused = False
        self._dragging = False
        self._thr_pending = None        # (valor, hasta) mientras la fuente aplica el slider
        self._after_id = None
        self._layout_id = None
        self._last_error = None
        self._closed_for = 0.0
        self.k, self.ox, self.oy = 1.0, 0.0, 0.0
        camera = getattr(source, "camera", None)
        self.recorder = Recorder(camera) if hasattr(camera, "latest") else None
        self.show_mask = False
        _load_font_file(FONT_FILE)
        families = set(tkfont.families(root))
        family = next((f for f in FAMILIES if f in families), "TkDefaultFont")
        self.fonts = {name: tkfont.Font(root=root, family=family, size=-px, weight=w, slant=sl)
                      for name, (px, w, sl) in FONTS.items()}
        self._glasses_src = Image.open(GLASSES).convert("RGBA") if GLASSES.exists() else None
        self._glasses = None
        self._build()
        if demo:
            self._toggle_demo()
        self._refresh()

    # --- interfaz para app.py ---
    def handle(self, ev):
        count_event(self.counts, ev)
        for key, _ in COUNTERS:
            self.count_labels[key].config(text=str(self.counts[key]))
        if ev.type in (E.CLICK_LEFT, E.CLICK_RIGHT, E.DRAG_END):
            self._flash = {E.CLICK_LEFT: "click ✓", E.CLICK_RIGHT: "right click ✓"}.get(ev.type, "dropped ✓")
            self._flash_until = time.monotonic() + FLASH_S

    def set_paused(self, paused):
        self._paused = paused
        self.pause_btn.config(active=paused)
        self.pause_lbl.show(paused)

    def set_drag(self, drag, note=None):
        self.drag = drag
        self.drag_btn.config(active=drag is not None)
        if note:
            self._flash = note
            self._flash_until = time.monotonic() + FLASH_S

    def set_gyro(self, state, note=None):
        self.gyro = state
        if note:
            self._flash = note
            self._flash_until = time.monotonic() + FLASH_S * 3

    def set_dictation(self, state, note=None):
        self.dictation = state
        self.preview = note if state == "preview" else None
        self._redraw()
        if note and state != "preview":
            self._flash = note
            self._flash_until = time.monotonic() + FLASH_S * 2

    def close(self):
        for attr in ("_after_id", "_layout_id"):
            after_id = getattr(self, attr)
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attr, None)
        if self.recorder is not None and self.recorder.active:
            log.info("Video guardado en %s", self.recorder.stop())
        # Los botones guardan métodos de self (un ciclo): romperlo para que el monitor se
        # libere ya, en el hilo principal. Si lo libera el recolector desde otro hilo,
        # las imágenes de tkinter fallan con "main thread is not in main loop".
        for _, btn in self.buttons:
            btn.command = None
        self.mask_btn.command = None

    # --- construcción ---
    def _build(self):
        self.root.configure(bg=BG)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        k0 = min(1.0, sw * 0.9 / STAGE_W, sh * 0.85 / STAGE_H)
        self.stage = tk.Canvas(self.root, bg=BG, highlightthickness=0,
                               width=round(STAGE_W * k0), height=round(STAGE_H * k0))
        self.stage.pack(fill="both", expand=True)
        self.stage.bind("<Configure>", self._on_resize)

        self.status = _Text(fill=INK)
        self.message = _Text(fill=INK)
        self.pause_lbl = _Text("PAUSED: no clicks", fill=YELLOW)
        self.pause_lbl.visible = False
        self.metrics = _Text()
        self.rec_lbl = _Text()
        self.mask_btn = _Button("mask ○", self._toggle_mask)
        self.count_labels = {key: _Text("0") for key, _ in COUNTERS}
        self.buttons = [            # (x del diseño, botón); se reparten en _layout
            (15, _Button("Recalibrate", self.source.recalibrate)),
            (139, _Button("Pause", self.on_pause)),
            (180, _Button("Drag", lambda: self.on_drag())),
            (221, _Button("Record", self._toggle_record)),
            (311, _Button("Demo", self._toggle_demo)),
            (387, _Button("Reset", self._reset_counts)),
        ]
        self.pause_btn, self.drag_btn, self.rec_btn, self.demo_btn = (b for _, b in self.buttons[1:5])
        if self.recorder is None:
            self.rec_btn.config(state="disabled")

        self.thr = _Slider(self._on_threshold, self._set_dragging)
        self._layout(k0, 0, 0)

    def _on_resize(self, event):
        if self._layout_id is not None:
            self.root.after_cancel(self._layout_id)
        self._layout_id = self.root.after(40, self._fit, event.width, event.height)

    def _fit(self, w, h):
        self._layout_id = None
        k = min(w / STAGE_W, h / STAGE_H)
        ox, oy = (w - STAGE_W * k) / 2, (h - STAGE_H * k) / 2
        if abs(k - self.k) > 0.005 or abs(ox - self.ox) > 1 or abs(oy - self.oy) > 1:
            self._layout(k, ox, oy)

    def _p(self, x, y):
        return self.ox + x * self.k, self.oy + y * self.k

    def _layout(self, k, ox, oy):
        """Dibuja todo el diseño a escala k (al abrir y cada vez que cambia el tamaño)."""
        self.k, self.ox, self.oy = k, ox, oy
        c, p, f = self.stage, self._p, self.fonts
        for name, (px, _, _) in FONTS.items():
            f[name].configure(size=-max(6, round(px * k)))
        c.delete("all")

        c.create_text(*p(15, 3), text="CALEglass", font=f["cale"], fill=CALE, angle=-90, anchor="sw")
        if self._glasses_src is not None:
            size = (max(1, round(1989 * k)), max(1, round(1118 * k)))
            self._glasses = ImageTk.PhotoImage(self._glasses_src.resize(size, Image.LANCZOS),
                                               master=self.root)
            c.create_image(*p(58, -300), image=self._glasses, anchor="nw")

        # ojo: el video llena el marco (esquinas redondeadas); el texto va encima
        bx1, by1, bx2, by2 = EYE_BOX
        size = (max(1, round((bx2 - bx1) * k)), max(1, round((by2 - by1) * k)))
        self._photo_size = size
        self._round = _rounded_mask(size, max(1, round(EYE_R * k)))
        self._shade = _shade(size, max(1, round(50 * k)), max(1, round(80 * k)))
        self._photo = ImageTk.PhotoImage(self._frame_image(Image.new("RGB", size, "#3A3540")),
                                         master=self.root)
        self.video = c.create_image(*p(bx1, by1), image=self._photo, anchor="nw")
        _round_rect(c, *p(bx1, by1), *p(bx2, by2), EYE_R * k, outline=INK, width=max(1, 4 * k), fill="")
        self.metrics.attach(c, c.create_text(*p(201, 610), font=f["stats"], anchor="nw"))
        c.create_text(*p(684, 636), text="Right eye", font=f["eye"], fill=INK, anchor="se")
        self.mask_btn.attach(c, c.create_text(*p(206, 360), font=f["small"], anchor="nw"))
        self.rec_lbl.attach(c, c.create_text(*p(206, 382), font=f["small"], anchor="nw"))

        # barra de progreso del cierre (las "muestras de color" del diseño)
        self._bar_box = (*p(183.5, 668), *p(699, 688.4))
        self._draw_bar(self._closed_for)

        # estado, panel de contadores y botones
        pill = _round_rect(c, *p(737, 345), *p(1252, 400), 26 * k, fill=PANEL, outline="")
        self.status.attach(c, c.create_text(*p(994.5, 372.5), font=f["status"]), pill)
        _round_rect(c, *p(737, 412), *p(1252, 621), 34 * k, fill=PANEL, outline="")
        for i, (key, text) in enumerate(COUNTERS):
            y = 434 + 26 * i
            c.create_text(*p(759, y), text=text, font=f["row"], fill=INK, anchor="nw")
            self.count_labels[key].attach(c, c.create_text(*p(1211, y), font=f["row"], anchor="ne"))
        # botones repartidos a lo ancho del panel según lo que mide cada texto
        widths = [f["btn"].measure(btn.text) / k for _, btn in self.buttons]
        gap = (452 - sum(widths)) / (len(widths) - 1)
        x = 759
        for (_, btn), w in zip(self.buttons, widths):
            btn.attach(c, c.create_text(*p(x, 574), font=f["btn"], anchor="nw"))
            btn.config()
            x += w + gap
        self.message.attach(c, c.create_text(*p(737, 632), font=f["msg"], anchor="nw",
                                             width=515 * k))
        self.pause_lbl.attach(c, c.create_text(*p(737, 700), font=f["msg"], anchor="nw"))

        # slider del umbral (redondeado)
        self.thr.attach(c, (*p(1264, 412), *p(1280, 618)), 25 * k, 8 * k)
        c.create_text(*p(1286, 440), text="Threshold", font=f["umbral"], fill=INK, angle=-90, anchor="sw")
        self._redraw()

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
            text, color = status_of(view, now, flash, self.drag, self.dictation, self.gyro)
            self.status.config(text=text, bg=color, fill=DARK if color in LIGHT else INK)
            if self.recorder is not None and self.recorder.active:
                self.recorder.poll(now)
                self.rec_lbl.config(text=f"● REC {now - self.recorder.started:.0f} s", fill=RED)
            self._last_error = None
        except Exception as e:
            if repr(e) != self._last_error:     # no llenar el log con el mismo error a 30 Hz
                self._last_error = repr(e)
                log.exception("Error al actualizar el monitor")

    def _draw(self, view):
        self._photo.paste(self._frame_image(compose(view), view.mask if self.show_mask else None))
        self._closed_for = view.closed_for if view.status == "closed" else 0.0
        self._draw_bar(self._closed_for)
        self.message.config(text=view.message or (f"\u201c{self.preview}\u201d" if self.preview else ""))
        self._sync_threshold(view.thr)
        low = 0 < view.fps < MIN_FPS
        self.metrics.config(
            text=f"FPS {view.fps:.0f}  Pupil {view.pupil_area:.0f} /{view.open_area:.0f}"
                 f"  Threshold {view.thr}{'  (low)' if low else ''}",
            fill=RED if low else INK)

    def _frame_image(self, img, mask=None):
        """Video -> imagen del tamaño del marco: recortada para llenarlo, sombreada arriba y
        abajo para el texto, con la máscara en la esquina y las esquinas redondeadas."""
        size = self._photo_size
        out = ImageOps.fit(img, size, Image.BILINEAR).convert("RGBA")
        out.alpha_composite(self._shade)
        if mask is not None:
            thumb = Image.fromarray(mask if mask.ndim == 2 else mask[:, :, ::-1]).convert("RGB")
            h = max(1, round(size[1] * 0.3))
            thumb = thumb.resize((max(1, round(thumb.width * h / thumb.height)), h))
            pad = round(EYE_R * self.k * 0.7)
            out.paste(thumb, (size[0] - thumb.width - pad, pad))
        out.putalpha(self._round)
        return out

    def _draw_bar(self, d):
        c = self.stage
        x1, y1, x2, y2 = self._bar_box
        c.delete("bar")

        def x(s):
            return x1 + (x2 - x1) * min(s, BAR_END) / BAR_END

        for a, b, color in ((0.0, LEFT_AT, YELLOW), (LEFT_AT, RIGHT_AT, BLUE), (RIGHT_AT, DRAG_AT, PURPLE),
                            (DRAG_AT, BAR_END, GREEN)):
            c.create_rectangle(x(a), y1, x(b), y2, fill=_blend(color), outline="", tags="bar")
            if d > a:
                c.create_rectangle(x(a), y1, x(min(d, b)), y2, fill=color, outline="", tags="bar")
        if d > 0:
            c.create_text(x2 - 6 * self.k, (y1 + y2) / 2, text=f"{d:.1f} s", anchor="e", fill=DARK,
                          font=self.fonts["small"], tags="bar")

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
    def _toggle_mask(self):
        self.show_mask = not self.show_mask
        self.mask_btn.config(text="mask ●" if self.show_mask else "mask ○")
        self._redraw()

    def _toggle_record(self):
        if self.recorder.active:
            path = self.recorder.stop()
            self.rec_btn.config(active=False)
            self.rec_lbl.config(text=f"Saved: {Path(path).name}", fill=INK)
            log.info("Video guardado en %s", path)
            return
        try:
            self.recorder.start(time.monotonic())
        except Exception as e:
            log.warning("No se pudo grabar: %s", e)
            self.rec_lbl.config(text="Could not record", fill=RED)
            return
        self.rec_btn.config(active=True)

    def _toggle_demo(self):
        """Demo = pantalla completa; el diseño se escala solo al nuevo tamaño."""
        self.demo = not self.demo
        try:
            self.root.attributes("-fullscreen", self.demo)
        except tk.TclError:
            pass
        self.demo_btn.config(active=self.demo)

    def _reset_counts(self):
        for key in self.counts:
            self.counts[key] = 0
            self.count_labels[key].config(text="0")
