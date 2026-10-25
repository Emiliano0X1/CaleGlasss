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
Arrastrar: F10 y el botón Drag llaman request_drag().
Dictado: F11 y el botón "mic" del indicador flotante llaman request_dictation().
Con DICTATION_AUTO arranca solo al hablar con el foco en un cuadro de texto y queda en
preview: mientras tanto mouse.intercept manda el parpadeo al dictado (izquierdo = escribir,
derecho = descartar) en vez de hacer clic. En pausa no arranca solo.
F9/F10/F11 llegan en el hilo de pynput, así que solo dejan la petición en una cola y
el tick del hilo principal la aplica (tkinter no es seguro entre hilos).
Lo que hace el mouse (doble clic, agarrar, soltar) llega por on_action y se muestra
DESPUÉS de repartir los eventos, para que no lo tape el "click ✓" del mismo clic.
Sacudir la cabeza recalibra el giroscopio del ESP32 (sin su página). GyroWatch ve los
avisos que el ESP32 manda con el cursor y aquí se muestran; mientras calibra (hasta
GYRO_TIMEOUT_S) los parpadeos no hacen clic: al sacudir la cabeza es fácil cerrar el ojo.

Agregar una pieza nueva (voz, agente...) = crear un suscriptor o fuente y registrarlo aquí.
"""
import logging
import queue
import time
import tkinter as tk

from eyeclick.actions import dictation, feedback, gyro_watch, logger, mouse
from eyeclick.bus import Bus
from eyeclick.config import CAMERA_INDEX, DICTATION_AUTO, DISPATCH_MS
from eyeclick.events import EventType as E
from eyeclick.ui import monitor, overlay

log = logging.getLogger(__name__)

GYRO_TIMEOUT_S = 12.0   # sin "listo" del ESP32 en este tiempo: no se quedó quieto


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
    def __init__(self, mock=False, video=None, camera=None, demo=False):
        self.bus = Bus()
        self.source = make_source(self.bus.publish, mock, video, camera)
        self._requests = queue.SimpleQueue()    # "pause" / "drag" / "dictate", desde cualquier hilo
        self._dictation_states = queue.SimpleQueue()    # (estado, nota) desde el hilo del dictado
        self._gyro_signals = queue.SimpleQueue()        # "start" / "done" desde el hilo de pynput
        self._gyro_until = None                         # calibrando el giroscopio hasta...
        self.gyro = gyro_watch.GyroWatch(self._gyro_signals.put_nowait)
        self._notes = []                        # avisos del mouse para mostrar tras dispatch()
        self._after_id = None
        self._keys = None
        self._closed = False

        self.root = tk.Tk()
        self.root.title("EyeClick")
        self.logger = logger.EventLogger()
        self.mouse = mouse.MouseActions(on_action=self._notes.append)
        self.mouse.intercept = self._dictation_blink
        self.feedback = feedback.Feedback()
        self.dictation = dictation.Dictation(on_state=lambda *s: self._dictation_states.put_nowait(s))
        self.overlay = overlay.Overlay(self.root, self.source, on_dictate=self.request_dictation)
        self.monitor = monitor.Monitor(self.root, self.source, on_pause=self.request_pause,
                                       on_drag=self.request_drag, demo=demo)

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
            self._start_hotkeys()
            self.dictation.preload()
            if DICTATION_AUTO:
                self.dictation.start_auto()
            self.gyro.start()
            self._tick()
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def request_pause(self):
        """Se puede llamar desde cualquier hilo."""
        self._requests.put_nowait("pause")

    def request_drag(self):
        """Se puede llamar desde cualquier hilo."""
        self._requests.put_nowait("drag")

    def request_dictation(self):
        """Se puede llamar desde cualquier hilo."""
        self._requests.put_nowait("dictate")

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        log.info("Cerrando EyeClick")
        self._safe(self.source.stop)
        self._safe(self.dictation.close)
        self._safe(self.gyro.stop)
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
                request = self._requests.get_nowait()
            except queue.Empty:
                break
            if request == "pause":
                self._toggle_pause()
            elif request == "drag":
                self.mouse.toggle_drag()
            else:
                self.dictation.toggle()
        while True:
            try:
                state, note = self._dictation_states.get_nowait()
            except queue.Empty:
                break
            self._show_dictation(state, note)
        self._check_gyro()
        self.bus.dispatch()
        if self._notes:
            notes, self._notes[:] = self._notes[:], []
            drag = self.mouse.drag
            for note in notes:
                self._safe(lambda: self.overlay.set_drag(drag, note))
                self._safe(lambda: self.monitor.set_drag(drag, note))
        self._after_id = self.root.after(DISPATCH_MS, self._tick)

    def _show_dictation(self, state, note):
        self._safe(lambda: self.overlay.set_dictation(state, note))
        self._safe(lambda: self.monitor.set_dictation(state, note))
        auto = self.dictation.auto      # arrancó solo: ya estaba hablando, sin bips
        if state == "listening" and not auto:
            self._safe(lambda: self.feedback.beep(1200, 70))    # "habla ya"
        elif state == "transcribing" and not auto:
            self._safe(lambda: self.feedback.beep(700, 70))     # "te escuché"
        elif state == "preview":
            self._safe(lambda: self.feedback.beep(990, 120))    # "¿lo escribo?"

    def _check_gyro(self):
        now = time.monotonic()
        while True:
            try:
                signal = self._gyro_signals.get_nowait()
            except queue.Empty:
                break
            if signal == "start":
                self._gyro_until = now + GYRO_TIMEOUT_S
                self._show_gyro("calibrating", None)
            elif self._gyro_until is not None:
                self._gyro_until = None
                self._show_gyro(None, "gyro calibrated ✓")
                self._safe(lambda: self.feedback.beep(990, 120))
        if self._gyro_until is not None and now > self._gyro_until:
            self._gyro_until = None
            self._show_gyro(None, "gyro not calibrated: hold still after shaking")

    def _show_gyro(self, state, note):
        self._safe(lambda: self.overlay.set_gyro(state, note))
        self._safe(lambda: self.monitor.set_gyro(state, note))

    def _dictation_blink(self, ev):
        """mouse.intercept: calibrando el giroscopio no hay clics; con un dictado en
        preview, el parpadeo es la respuesta."""
        if self._gyro_until is not None:
            return True
        if self.dictation.state != "preview":
            return False
        if ev.type == E.CLICK_LEFT:
            self.dictation.confirm()
        else:
            self.dictation.discard()
        return True

    def _toggle_pause(self):
        paused = self.mouse.toggle_pause()
        self.dictation.suspended = paused
        if paused:
            self.dictation.discard()
        self._safe(lambda: self.overlay.set_paused(paused))
        self._safe(lambda: self.monitor.set_paused(paused))

    def _start_hotkeys(self):
        """F9 = pausa, F10 = arrastrar, F11 = dictar. Sin pynput o sin permisos, la app sigue sin ellas."""
        try:
            from pynput import keyboard

            def on_press(key):
                if key == keyboard.Key.f9:
                    self.request_pause()
                elif key == keyboard.Key.f10:
                    self.request_drag()
                elif key == keyboard.Key.f11:
                    self.request_dictation()

            self._keys = keyboard.Listener(on_press=on_press, daemon=True)
            self._keys.start()
        except Exception:
            log.warning("F9/F10/F11 no disponibles; usa los botones del monitor", exc_info=True)

    @staticmethod
    def _safe(fn):
        try:
            fn()
        except Exception:
            log.exception("Error al cerrar")


def start(mock=False, video=None, camera=None, demo=False):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    App(mock=mock, video=video, camera=camera, demo=demo).run()
