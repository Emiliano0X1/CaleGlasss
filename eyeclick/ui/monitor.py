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

Cómo se actualiza:
    1. Cada MONITOR_MS: source.latest_view(); si el t es igual al anterior, no redibujar.
    2. BGR -> RGB -> PIL.Image -> ImageTk.PhotoImage -> Label.
    3. GUARDAR la referencia a la PhotoImage en self (si no, sale en blanco).
    4. Estado/barra/métricas salen de la EyeView; contadores salen de handle(evento).
    5. Si t lleva > 1 s sin cambiar: "CÁMARA CONGELADA" en rojo.

TODO (SWE 2):
- [ ] Layout: video a la izquierda, barra debajo, estado/contadores/métricas a la derecha.
- [ ] _refresh() con root.after(MONITOR_MS) y los pasos 1-5.
- [ ] handle(): contadores (CLICK_LEFT, CLICK_RIGHT, CANCELLED con duración < LEFT_AT, EYE_LOST).
- [ ] Controles de arriba.
- [ ] Botón Grabar: cv2.VideoWriter con los frames crudos (pedir a SWE 1 si hace falta exponerlos).
- [ ] Modo demo.
- [ ] Probar primero con MockSource (--mock).
"""
import tkinter as tk  # noqa: F401

from PIL import Image, ImageTk  # noqa: F401

from eyeclick.config import LEFT_AT, MONITOR_MS, RIGHT_AT  # noqa: F401

TYPES = None


class Monitor:
    def __init__(self, root, source, on_pause, demo=False):
        self.root = root
        self.source = source            # cualquier fuente: pipeline o mock
        self.on_pause = on_pause
        self.demo = demo
        self.counts = {"left": 0, "right": 0, "ignored": 0, "lost": 0}
        self._photo = None              # referencia a la PhotoImage (¡no borrar!)
        self._last_t = 0.0
        # TODO (SWE 2): construir widgets y llamar self._refresh()

    def _refresh(self):
        # TODO (SWE 2)
        raise NotImplementedError

    def handle(self, ev):
        # TODO (SWE 2)
        raise NotImplementedError
