"""Indicador flotante pequeño, sin bordes y siempre encima.  (SWE 2, suscriptor del bus)

Se queda para cuando el monitor está minimizado y la persona usa otras apps.
Colores (los mismos del monitor):
    gris abierto | amarillo cerrado | azul IZQUIERDO | morado DERECHO | verde clic | rojo SIN OJO

Funciona con los eventos del bus (text_for), con tres reglas para no quedarse pegado:
    - Los estados de un momento ("clic ✓", "calibrado", "ACTIVO") vuelven a "abierto"
      después de unos segundos.
    - "NO VEO EL OJO" y "descanso" no tienen evento de salida (al volver a ver el ojo
      abierto no llega nada), así que si hay fuente se revisa latest_view() y se
      regresa a "abierto" cuando el ojo se ve abierto.
    - En pausa muestra "PAUSA" todo el tiempo e ignora los eventos (no hay clics).
      app.py avisa con set_paused().

Se puede arrastrar con el mouse para moverlo (no tiene barra de título).
"""
import time
import tkinter as tk

from eyeclick.config import CANCEL_AT
from eyeclick.events import EventType as E

TYPES = None

GRAY, RED = "#555", "#c0392b"
COLORS = {
    "IZQUIERDO": "#2f6fde",
    "DERECHO": "#8a3fd1",
    "clic ✓": "#2e9e5b",
    "cerrado...": "#d9a400",
    "calibrado": "#2e9e5b",
    "ACTIVO": "#2e9e5b",
    "PAUSA": "#d35400",
}
IDLE = "abierto"
FLASH_S = 0.8           # cuánto duran "clic ✓" y "ACTIVO"
CALIBRATED_S = 1.5
TICK_MS = 200
GEOMETRY = "260x56+20+20"


def text_for(ev):
    """Evento -> (texto, warn, segundos visible o None, se_queda_hasta_ver_el_ojo) o None."""
    t = ev.type
    if t == E.EYE_CLOSED:
        return "cerrado...", False, None, False
    if t == E.STAGE_LEFT:
        return "IZQUIERDO", False, None, False
    if t == E.STAGE_RIGHT:
        return "DERECHO", False, None, False
    if t in (E.CLICK_LEFT, E.CLICK_RIGHT):
        return "clic ✓", False, FLASH_S, False
    if t == E.CANCELLED:
        if ev.duration >= CANCEL_AT:
            return "descanso", False, None, True        # sigue cerrado hasta que abra
        return IDLE, False, None, False
    if t == E.EYE_LOST:
        return "NO VEO EL OJO", True, None, True
    if t == E.CALIBRATED:
        return "calibrado", False, CALIBRATED_S, False
    return None


class Overlay:
    def __init__(self, root, source=None):
        self.root = root
        self.source = source            # opcional: para salir de "NO VEO EL OJO" / "descanso"
        self.paused = False
        self._revert_at = None          # cuándo volver a IDLE
        self._sticky = False            # esperando ver el ojo abierto
        self._after_id = None
        self._drag = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(GEOMETRY)
        self.label = tk.Label(self.win, text=IDLE, font=("Helvetica", 18, "bold"),
                              fg="white", bg=GRAY)
        self.label.pack(fill="both", expand=True)
        self.label.bind("<ButtonPress-1>", self._start_drag)
        self.label.bind("<B1-Motion>", self._on_drag)
        self._tick()

    def show(self, text, warn=False, hold=None, sticky=False):
        self.label.config(text=text, bg=RED if warn else COLORS.get(text, GRAY))
        self._revert_at = None if hold is None else time.monotonic() + hold
        self._sticky = sticky

    def handle(self, ev):
        if self.paused:
            return
        shown = text_for(ev)
        if shown is not None:
            self.show(*shown)

    def set_paused(self, paused):
        self.paused = paused
        if paused:
            self.show("PAUSA")
        else:
            self.show("ACTIVO", hold=FLASH_S)

    def close(self):
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    # --- vuelta a "abierto" ---
    def _tick(self):
        self._after_id = self.root.after(TICK_MS, self._tick)
        if self.paused:
            return
        if self._revert_at is not None and time.monotonic() >= self._revert_at:
            self.show(IDLE)
        elif self._sticky and self._eye_open():
            self.show(IDLE)

    def _eye_open(self):
        if self.source is None:
            return False
        view = self.source.latest_view()
        return view is not None and view.status == "open"

    # --- arrastrar ---
    def _start_drag(self, e):
        self._drag = (e.x, e.y)

    def _on_drag(self, e):
        dx, dy = self._drag
        self.win.geometry(f"+{e.x_root - dx}+{e.y_root - dy}")
