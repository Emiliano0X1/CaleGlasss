"""Orquestador: arma las piezas según el modo y las conecta.  (SWE 2)

start() hace, en orden:
    1. Crear el Bus.
    2. Elegir la fuente según el modo:
         mock   -> sources.mock.MockSource(bus.publish)
         video  -> vision.pipeline.PipelineSource(VideoFileSource(ruta), bus.publish)
         camera -> vision.pipeline.PipelineSource(CameraSource(N), bus.publish)
       app.py NO sabe qué fuente es: solo usa la interfaz de fuente.
    3. Crear tk.Tk(), los suscriptores (mouse, feedback, logger, overlay, monitor)
       y registrarlos en el bus con bus.subscribe().
    4. Arrancar la fuente (la calibración la lanza la propia fuente).
    5. root.after(DISPATCH_MS) en bucle llamando bus.dispatch(); root.mainloop().
    6. Al cerrar la ventana o presionar Esc: detener la fuente, cerrar el log
       y destruir las ventanas, EN ESE ORDEN.

Agregar una pieza nueva (voz, agente...) = crear un suscriptor o fuente y registrarlo aquí.

TODO (SWE 2):
- [ ] Implementar pasos 1-6.
- [ ] Conectar F9 / botón Pausa a MouseActions.toggle_pause().
- [ ] Pasar demo=True al monitor.
- [ ] Cierre limpio (fase 3:30 - 5:00).
"""
import tkinter as tk  # noqa: F401

from eyeclick.config import CAMERA_INDEX, DISPATCH_MS  # noqa: F401


def start(mock=False, video=None, camera=None, demo=False):
    # TODO (SWE 2)
    raise NotImplementedError("app.start() todavía no está implementado (SWE 2)")
