"""Indicador flotante pequeño, sin bordes y siempre encima.  (SWE 2, suscriptor del bus)

Se queda para cuando el monitor está minimizado y la persona usa otras apps.
Colores (los mismos del monitor):
    gris abierto | amarillo cerrado | azul IZQUIERDO | morado DERECHO | verde clic | rojo SIN OJO

Funciona con los eventos del bus (text_for), con tres reglas para no quedarse pegado:
    - Los estados de un momento ("clic ✓", "calibrado", "ACTIVO") vuelven a "abierto"
      después de unos segundos.
    - "NO VEO EL OJO" no tiene evento de salida (al volver a ver el ojo
      abierto no llega nada), así que si hay fuente se revisa latest_view() y se
      regresa a "abierto" cuando el ojo se ve abierto.
    - En pausa muestra "PAUSA" todo el tiempo e ignora los eventos (no hay clics).
      app.py avisa con set_paused().
    - Mientras se arrastra, el estado de reposo es "DRAG ready" / "DRAGGING" en vez de
      "abierto" (app.py avisa con set_drag()).

    - Dictando, el estado de reposo es "LISTENING" / "TYPING..." (set_dictation()).

Botón "mic" a la derecha (si se pasa on_dictate): se mira y se parpadea, como cualquier
clic. En Windows la ventana es WS_EX_NOACTIVATE: el clic NO le quita el foco a la app
donde estabas escribiendo, así el texto dictado cae ahí y no en el indicador.

Se puede arrastrar con el mouse para moverlo (no tiene barra de título).
"""
import logging
import sys
import time
import tkinter as tk

from eyeclick.events import EventType as E

log = logging.getLogger(__name__)

TYPES = None

GRAY, RED = "#555", "#c0392b"
COLORS = {
    "LEFT": "#2f6fde",
    "RIGHT": "#8a3fd1",
    "click ✓": "#2e9e5b",
    "closed...": "#d9a400",
    "calibrated": "#2e9e5b",
    "ACTIVE": "#2e9e5b",
    "PAUSED": "#d35400",
    "double click ✓": "#2e9e5b",
    "grabbed": "#2e9e5b",
    "dropped ✓": "#2e9e5b",
    "drag: blink to grab": "#d9a400",
    "DRAG ready": "#d9a400",
    "DRAGGING": "#d35400",
}
DRAG_IDLE = {"armed": "DRAG ready", "holding": "DRAGGING"}
GYRO_TEXT = "GYRO: hold still"
DICTATION_IDLE = {"listening": "LISTENING", "transcribing": "TYPING...", "typing": "TYPING...",
                  "preview": "blink to type"}
PREVIEW_HINT = "left blink = type  ·  right blink = discard"
COLORS.update({GYRO_TEXT: "#d9a400", "gyro calibrated ✓": "#2e9e5b",
               "gyro not calibrated: hold still after shaking": "#c0392b"})
COLORS.update({"LISTENING": "#c0392b", "TYPING...": "#d9a400", "typed ✓": "#2e9e5b",
               "blink to type": "#2e9e5b"})
MIC_BG, MIC_ON = "#333", "#c0392b"
IDLE = "open"
FLASH_S = 0.8           # cuánto duran "clic ✓" y "ACTIVO"
CALIBRATED_S = 1.5
TICK_MS = 200
GEOMETRY = "260x56+20+20"
GEOMETRY_MIC = "340x56+20+20"


def text_for(ev):
    """Evento -> (texto, warn, segundos visible o None, se_queda_hasta_ver_el_ojo) o None."""
    t = ev.type
    if t == E.EYE_CLOSED:
        return "closed...", False, None, False
    if t == E.STAGE_LEFT:
        return "LEFT", False, None, False
    if t == E.STAGE_RIGHT:
        return "RIGHT", False, None, False
    if t in (E.CLICK_LEFT, E.CLICK_RIGHT):
        return "click ✓", False, FLASH_S, False
    if t == E.STAGE_DRAG:
        return "DRAGGING", False, None, False
    if t == E.DRAG_END:
        return "dropped ✓", False, FLASH_S, False
    if t == E.CANCELLED:
        return IDLE, False, None, False
    if t == E.EYE_LOST:
        return "CAN'T SEE EYE", True, None, True
    if t == E.CALIBRATED:
        return "calibrated", False, CALIBRATED_S, False
    return None


class Overlay:
    def __init__(self, root, source=None, on_dictate=None):
        self.root = root
        self.source = source            # opcional: para salir de "NO VEO EL OJO"
        self.paused = False
        self.drag = None
        self.dictation = "idle"
        self.gyro = None                # "calibrating" mientras el ESP32 se calibra
        self._revert_at = None          # cuándo volver a IDLE
        self._sticky = False            # esperando ver el ojo abierto
        self._after_id = None
        self._drag = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(GEOMETRY if on_dictate is None else GEOMETRY_MIC)
        self.mic = None
        if on_dictate is not None:
            self.mic = tk.Label(self.win, text="mic", width=4, font=("Helvetica", 18, "bold"),
                                fg="white", bg=MIC_BG, cursor="hand2")
            self.mic.pack(side="right", fill="y")
            self.mic.bind("<ButtonRelease-1>", lambda _e: on_dictate())
        self.label = tk.Label(self.win, text=IDLE, font=("Helvetica", 18, "bold"),
                              fg="white", bg=GRAY)
        self.label.pack(fill="both", expand=True)
        # texto del dictado automático esperando confirmación (abajo, solo en preview)
        self.preview = tk.Label(self.win, font=("Helvetica", 13), fg="white", bg="#222",
                                justify="left", anchor="w", padx=8, pady=6)
        self._width = int((GEOMETRY if on_dictate is None else GEOMETRY_MIC).split("x")[0])
        _no_activate(self.win)
        self.label.bind("<ButtonPress-1>", self._start_drag)
        self.label.bind("<B1-Motion>", self._on_drag)
        self._tick()

    def show(self, text, warn=False, hold=None, sticky=False):
        if text == IDLE:
            text = ((GYRO_TEXT if self.gyro else None) or DICTATION_IDLE.get(self.dictation)
                    or DRAG_IDLE.get(self.drag, IDLE))
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
            self.show("PAUSED")
        else:
            self.show("ACTIVE", hold=FLASH_S)

    def set_drag(self, drag, note=None):
        self.drag = drag
        if self.paused:
            return
        if note:
            self.show(note, hold=FLASH_S)
        else:
            self.show(IDLE)

    def set_gyro(self, state, note=None):
        self.gyro = state
        if self.paused:
            return
        if note:
            self.show(note, hold=FLASH_S * 3)
        else:
            self.show(IDLE)

    def set_dictation(self, state, note=None):
        self.dictation = state
        if self.mic is not None:
            self.mic.config(bg=MIC_ON if state != "idle" else MIC_BG)
        self._show_preview(note if state == "preview" else None)
        if state == "preview":
            note = None                 # el texto va abajo, no como aviso
        if self.paused:
            return                  # en pausa se queda "PAUSED"; el botón mic sí cambia de color
        if note:
            self.show(note, hold=FLASH_S * 2)
        else:
            self.show(IDLE)

    def _show_preview(self, text):
        h = 56
        if text:
            self.preview.config(text=f"\u201c{text}\u201d\n{PREVIEW_HINT}", wraplength=self._width - 16)
            # el texto va debajo de la fila de arriba (mic + estado), no a su lado
            self.preview.pack(side="bottom", fill="x", before=self.mic or self.label)
            self.win.update_idletasks()
            h += self.preview.winfo_reqheight()
        else:
            self.preview.pack_forget()
        self.win.geometry(f"{self._width}x{h}")

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


_KEEP = []


def _no_activate(win):
    """Windows: que hacer clic en el indicador no le quite el foco a la otra app.

    WS_EX_NOACTIVATE no basta: Tk contesta WM_MOUSEACTIVATE con "activar". Se reemplaza el
    procedimiento de la ventana (y de su hijo, que recibe el clic primero) para contestar
    MA_NOACTIVATE; todo lo demás pasa a Tk igual que antes.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        win.update_idletasks()
        user32 = ctypes.windll.user32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        GWL_EXSTYLE, GWLP_WNDPROC = -20, -4
        WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x08000000, 0x00000080
        WM_MOUSEACTIVATE, MA_NOACTIVATE = 0x0021, 3

        child = win.winfo_id()
        top = user32.GetParent(child) or child
        user32.SetWindowLongW(top, GWL_EXSTYLE,
                              user32.GetWindowLongW(top, GWL_EXSTYLE) | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        procs = []
        for hwnd in {top, child}:
            old = [None]

            def proc(h, msg, wp, lp, old=old):
                if msg == WM_MOUSEACTIVATE:
                    return MA_NOACTIVATE
                return user32.CallWindowProcW(old[0], h, msg, wp, lp)

            cb = WNDPROC(proc)
            old[0] = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))
            procs.append(cb)
        _KEEP.extend(procs)     # vivos mientras exista el proceso: Windows los llama hasta el final
    except Exception:
        log.warning("No se pudo hacer el indicador no-activable", exc_info=True)
