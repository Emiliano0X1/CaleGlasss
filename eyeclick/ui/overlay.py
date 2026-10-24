"""Indicador flotante pequeño, sin bordes y siempre encima.  (SWE 2, suscriptor del bus)

Se queda para cuando el monitor está minimizado y la persona usa otras apps.
Colores (los mismos del monitor):
    gris abierto | amarillo cerrado | azul IZQUIERDO | morado DERECHO | verde clic | rojo SIN OJO

TODO (SWE 2):
- [ ] Crear como tk.Toplevel(root) (la ventana principal es el monitor).
- [ ] handle(): mapear eventos a textos/colores
      (EYE_CLOSED 'cerrado...', STAGE_LEFT 'IZQUIERDO', STAGE_RIGHT 'DERECHO',
       CLICK_* 'clic ✓', CANCELLED 'abierto', EYE_LOST 'NO VEO EL OJO' warn).
- [ ] Mostrar 'PAUSA' / 'ACTIVO' al pausar.
"""
import tkinter as tk

TYPES = None

GRAY, RED = "#555", "#c0392b"
COLORS = {
    "IZQUIERDO": "#2f6fde",
    "DERECHO": "#8a3fd1",
    "clic ✓": "#2e9e5b",
    "cerrado...": "#d9a400",
}


class Overlay:
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry("220x56+20+20")
        self.label = tk.Label(self.win, text="abierto", font=("Helvetica", 18, "bold"),
                              fg="white", bg=GRAY)
        self.label.pack(fill="both", expand=True)

    def show(self, text, warn=False):
        self.label.config(text=text, bg=RED if warn else COLORS.get(text, GRAY))

    def handle(self, ev):
        # TODO (SWE 2)
        raise NotImplementedError
