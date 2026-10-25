"""Orquestador: arma las piezas según el modo y las conecta.  (SWE 2)

start() hace, en orden:
    1. Crear el Bus.
    2. Elegir la fuente según el modo (make_source):
         mock   -> sources.mock.MockSource(bus.publish)
         video  -> vision.pipeline.PipelineSource(VideoFileSource(ruta), bus.publish)
         camera -> vision.pipeline.PipelineSource(CameraSource(N), bus.publish)
       app.py NO sabe qué fuente es: solo usa la interfaz de fuente.
    3. Crear tk.Tk(), los suscriptores (logger, mouse, feedback, overlay, monitor)
       y registrarlos en el bus. El logger va primero para que registre todo
       aunque otro suscriptor falle.
    4. Arrancar la fuente (la calibración la lanza la propia fuente).
    5. root.after(DISPATCH_MS) en bucle llamando bus.dispatch(); root.mainloop().
    6. Al cerrar la ventana, presionar Esc o Ctrl+C: detener la fuente, cerrar el
       log y destruir las ventanas, EN ESE ORDEN (shutdown).

Pausa: F9 (en todos los modos) y el botón del monitor llaman request_pause().
F9 llega en el hilo de pynput, así que request_pause() solo deja la petición en
una cola y el tick del hilo principal la aplica (tkinter no es seguro entre hilos).

Agregar una pieza nueva (voz, agente...) = crear un suscriptor o fuente y registrarlo aquí.

Voice bridge (--voice, eyeclick/bridge/): "Hey glasses, ..." starts a Jira command (the mic
is always on, it beeps through feedback when it hears the phrase); its listener is one more
subscriber (long blink = approve the pending plan or listen for a request); F10 = talk
(fallback); each tick copies Bridge.note() to the overlay's second line. Without --voice
nothing of it is loaded.
"""
import logging
import queue
import tkinter as tk

from eyeclick.actions import feedback, logger, mouse
from eyeclick.bus import Bus
from eyeclick.config import CAMERA_INDEX, DISPATCH_MS
from eyeclick.ui import monitor, overlay

log = logging.getLogger(__name__)


def make_source(publish, mock=False, video=None, camera=None):
    """Imports aquí adentro: --mock no necesita cargar OpenCV ni la cámara."""
    if mock:
        from eyeclick.sources.mock import MockSource
        return MockSource(publish)
    from eyeclick.vision.pipeline import PipelineSource
    if video:
        from eyeclick.vision.camera import VideoFileSource
        return PipelineSource(VideoFileSource(video), publish)
    from eyeclick.vision.camera import CameraSource
    return PipelineSource(CameraSource(CAMERA_INDEX if camera is None else camera), publish)


class App:
    def __init__(self, mock=False, video=None, camera=None, demo=False, voice=False):
        self.bus = Bus()
        self.source = make_source(self.bus.publish, mock, video, camera)
        self._pause_requests = queue.SimpleQueue()
        self._after_id = None
        self._keys = None
        self._closed = False

        self.root = tk.Tk()
        self.root.title("EyeClick")
        self.logger = logger.EventLogger()
        self.mouse = mouse.MouseActions()
        self.feedback = feedback.Feedback()
        self.overlay = overlay.Overlay(self.root, self.source)
        self.monitor = monitor.Monitor(self.root, self.source, on_pause=self.request_pause, demo=demo)
        self.bridge = None
        if voice:
            from eyeclick.bridge import Bridge   # here: --voice loads httpx, sounddevice and Whisper
            from eyeclick.bridge import listener
            self.bridge = Bridge(beep=self.feedback.beep)
            self.bus.subscribe(self.bridge.listener, listener.TYPES)

        for sub, types in (
            (self.logger, logger.TYPES),
            (self.mouse, mouse.TYPES),
            (self.feedback, feedback.TYPES),
            (self.overlay, overlay.TYPES),
            (self.monitor, monitor.TYPES),
        ):
            self.bus.subscribe(sub, types)

        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.root.bind("<Escape>", lambda _e: self.shutdown())

    def run(self):
        try:
            self.source.start()
            if self.bridge is not None:
                self.bridge.start()
            self._start_hotkeys()
            self._tick()
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def request_pause(self):
        """Se puede llamar desde cualquier hilo."""
        self._pause_requests.put_nowait(True)

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        log.info("Cerrando EyeClick")
        self._safe(self.source.stop)
        if self.bridge is not None:
            self._safe(self.bridge.stop)
        self._safe(self.monitor.close)      # termina de escribir el video si se estaba grabando
        self._safe(self.overlay.close)
        if self._keys is not None:
            self._safe(self._keys.stop)
        self._safe(self.logger.close)
        self._safe(self.feedback.close)
        if self._after_id is not None:
            self._safe(lambda: self.root.after_cancel(self._after_id))
        self._safe(self.root.destroy)

    # --- hilo principal ---
    def _tick(self):
        if self._closed:
            return
        while True:
            try:
                self._pause_requests.get_nowait()
            except queue.Empty:
                break
            self._toggle_pause()
        self.bus.dispatch()
        if self.bridge is not None:
            self.overlay.set_note(self.bridge.note())
        self._after_id = self.root.after(DISPATCH_MS, self._tick)

    def _toggle_pause(self):
        paused = self.mouse.toggle_pause()
        self._safe(lambda: self.overlay.set_paused(paused))
        self._safe(lambda: self.monitor.set_paused(paused))

    def _start_hotkeys(self):
        """F9 = pausa en todos los modos. Sin pynput o sin permisos, la app sigue sin F9."""
        try:
            from pynput import keyboard

            def on_press(key):
                if key == keyboard.Key.f9:
                    self.request_pause()
                elif key == keyboard.Key.f10 and self.bridge is not None:
                    self.bridge.talk()      # pynput's thread: talk() only starts a worker

            self._keys = keyboard.Listener(on_press=on_press, daemon=True)
            self._keys.start()
        except Exception:
            log.warning("F9 no disponible; usa el botón Pausa del monitor", exc_info=True)

    @staticmethod
    def _safe(fn):
        try:
            fn()
        except Exception:
            log.exception("Error al cerrar")


def start(mock=False, video=None, camera=None, demo=False, voice=False):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    App(mock=mock, video=video, camera=camera, demo=demo, voice=voice).run()
