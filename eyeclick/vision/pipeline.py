"""Fuente real del ojo: frame -> detector -> FSM -> bus + EyeView.  (SWE 1)

Cumple la "interfaz de fuente" (la misma que sources/mock.py):
    start(), stop(), latest_view() -> EyeView | None,
    recalibrate(), set_threshold(valor)

Su hilo repite en cada frame NUEVO (mismo t = saltar):
    1. Tomar el último frame de la cámara o del video.
    2. Si está calibrando: Calibrator.feed(); al terminar publicar CALIBRATED.
    3. Clasificarlo con detector.classify().
    4. Pasar el estado a BlinkFSM.update() (publica eventos en el bus).
    5. Dibujar con annotate() y guardar la EyeView como último valor (con lock).

recalibrate() y set_threshold() se llaman desde el hilo principal (botones del
monitor): solo dejan una marca, y el hilo del pipeline aplica el cambio antes
del siguiente frame.

Para no generar clics falsos:
    - Durante la calibración la FSM no recibe nada (el usuario cierra el ojo 3 s).
      Si había un cierre en curso al pedir recalibrar, se cancela.
    - Al arrancar y tras calibrar, la FSM empieza cuando se ve el ojo abierto.
    - Si la cámara deja de mandar frames STALE_S, se alimenta 'lost' (-> EYE_LOST).
"""
import logging
import threading
import time
from dataclasses import replace

from eyeclick.events import EventType, EyeEvent, EyeView
from eyeclick.logic.blink_fsm import BlinkFSM
from eyeclick.vision.annotate import annotate, small_mask
from eyeclick.vision.calibration import CALIB_FILE, Calibration, Calibrator
from eyeclick.vision.detector import classify

log = logging.getLogger(__name__)

STALE_S = 0.5           # sin frames nuevos durante esto = 'lost'
LOST_DT = 1 / 30        # ritmo al que se alimenta 'lost' mientras no llegan frames
POLL_S = 0.003          # espera entre consultas a la cámara
NOTE_S = 6.0            # segundos que se muestra el resultado de la calibración
HINT_AFTER = 10.0       # segundos sin ver el ojo abierto -> sugerir recalibrar
HINT_MSG = "Can't see your eye open: did the light change? Press Recalibrate"
WAIT_OPEN_MSG = "Open your eye to start"


class PipelineSource:
    def __init__(self, camera, publish, calib_path=CALIB_FILE):
        """camera: CameraSource o VideoFileSource. publish: bus.publish."""
        self.camera = camera
        self.publish = publish
        self.calib_path = calib_path
        self.fsm = BlinkFSM(publish)
        self.calib = None
        self._view: EyeView | None = None
        self._lock = threading.Lock()
        self._want_recalibrate = False
        self._want_thr: int | None = None
        self._running = False
        self._thread = None
        self._calibrator: Calibrator | None = None
        self._wait_open = True          # no alimentar la FSM hasta ver el ojo abierto
        self._last_open = time.monotonic()
        self._note, self._note_until = "", 0.0

    # --- interfaz de fuente ---
    def start(self):
        self._load_calibration()
        self.camera.start()
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="pipeline", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.camera.stop()

    def latest_view(self) -> EyeView | None:
        with self._lock:
            return self._view

    def recalibrate(self):
        with self._lock:
            self._want_recalibrate = True

    def set_threshold(self, value):
        with self._lock:
            self._want_thr = int(value)

    # --- hilo ---
    def _loop(self):
        last_t = None
        last_new = time.monotonic()     # último frame nuevo (o el arranque)
        last_lost = 0.0
        while self._running:
            try:
                self._apply_requests()
                frame, t = self.camera.latest()
                now = time.monotonic()
                if frame is not None and t != last_t:
                    last_t, last_new = t, now
                    self._step(frame, t)
                elif now - last_new > STALE_S and now - last_lost >= LOST_DT:
                    last_lost = now
                    self._step(None, now)
                else:
                    time.sleep(POLL_S)
            except Exception:
                log.exception("Error en el pipeline; se sigue con el siguiente frame")
                time.sleep(0.1)

    def _load_calibration(self):
        self.calib = Calibration.load(self.calib_path)
        if self.calib is None:
            self.calib = Calibration()      # solo para dibujar mientras calibra
            self._calibrator = Calibrator()
        else:
            self.publish(EyeEvent(EventType.CALIBRATED))

    def _apply_requests(self):
        with self._lock:
            recalibrate, self._want_recalibrate = self._want_recalibrate, False
            thr, self._want_thr = self._want_thr, None
        if recalibrate:
            self.fsm.reset(time.monotonic())
            self._calibrator = Calibrator()
        if thr is not None:
            self.calib = replace(self.calib, thr=max(0, min(255, thr)))
            self._save()

    def _step(self, frame, t):
        """Un frame (o None si no llegan) por los pasos 2-5."""
        if self._calibrator is not None:
            self._calibrator.feed(frame, t)
            if self._calibrator.done:
                self._finish_calibration(t)

        state = classify(frame, self.calib)
        if state.status == "open":
            self._last_open = t
            self._wait_open = False
        # mientras espera el ojo abierto solo se frena 'closed'; 'lost' sí llega (EYE_LOST)
        if self._calibrator is None and not (self._wait_open and state.status == "closed"):
            self.fsm.update(state.status, t)

        view = EyeView(
            frame=annotate(frame, state, self.calib),
            status=state.status,
            mask=small_mask(state.mask),
            closed_for=self.fsm.closed_for(t),
            pupil_area=state.area,
            open_area=self.calib.open_area,
            thr=self.calib.thr,
            fps=self.camera.fps,
            message=self._message(t),
            t=t,
        )
        with self._lock:
            self._view = view

    def _finish_calibration(self, t):
        cal, self._calibrator = self._calibrator, None
        self.calib = cal.result
        self._save()
        self._note, self._note_until = cal.warning or "Calibrado", t + NOTE_S
        self._wait_open, self._last_open = True, t
        if cal.warning:
            log.warning("Calibración: %s", cal.warning)
        log.info("Calibración: %s", self.calib)
        self.publish(EyeEvent(EventType.CALIBRATED, t))

    def _message(self, t):
        if self._calibrator is not None:
            return self._calibrator.message
        if t < self._note_until:
            return self._note
        if self._wait_open:
            return WAIT_OPEN_MSG
        if t - self._last_open > HINT_AFTER:
            return HINT_MSG
        return ""

    def _save(self):
        try:
            self.calib.save(self.calib_path)
        except OSError:
            log.warning("No se pudo guardar %s", self.calib_path, exc_info=True)
