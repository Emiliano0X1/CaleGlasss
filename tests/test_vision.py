"""Pruebas de visión con ojos sintéticos (sin cámara).  (SWE 1)

Ojo abierto: piel clara, iris gris y pupila negra grande (la cámara está a 2-3 cm).
Ojo cerrado: piel con sombra y una línea delgada de pestañas.
Imagen plana: lo que se ve con la cámara tapada o sin señal.
"""
import math
import time

import cv2
import numpy as np
import pytest

from eyeclick.config import VIEW_H, VIEW_W
from eyeclick.events import EventType as E
from eyeclick.vision import calibration, detector
from eyeclick.vision.annotate import MASK_H, MASK_W, annotate, small_mask
from eyeclick.vision.calibration import Calibration, Calibrator
from eyeclick.vision.camera import VideoFileSource
from eyeclick.vision.pipeline import PipelineSource

H, W = 480, 640
PUPIL_R = 80
DT = 1 / 30


def _eye(is_open, seed):
    rng = np.random.default_rng(seed)
    img = np.tile(np.linspace(140, 190, W), (H, 1))            # piel con sombra
    if is_open:
        cv2.circle(img, (W // 2, H // 2), 150, 110, -1)       # iris
        cv2.circle(img, (W // 2, H // 2), PUPIL_R, 25, -1)    # pupila
        cv2.circle(img, (W // 2 + 30, H // 2 - 30), 8, 250, -1)  # reflejo del LED
    else:
        cv2.line(img, (100, H // 2), (W - 100, H // 2 + 20), 60, 3)  # pestañas
    img += rng.normal(0, 6, img.shape)
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


OPEN = [_eye(True, s) for s in range(4)]
CLOSED = [_eye(False, s) for s in range(4)]
FLAT = np.full((H, W, 3), 128, np.uint8)


def _calibrate():
    cal = Calibrator()
    t, i = 0.0, 0
    while not cal.done:
        phase_open = t < calibration.READY_SECONDS + calibration.OPEN_SECONDS
        cal.feed((OPEN if phase_open else CLOSED)[i % 4], t)
        t, i = t + DT, i + 1
        assert t < 20, "la calibración no termina"
    return cal


@pytest.fixture(scope="module")
def calib():
    cal = _calibrate()
    assert cal.warning == ""
    return cal.result


def test_find_pupil_encuentra_la_pupila():
    contour, area, gray, mask = detector.find_pupil(OPEN[0], 60, 200, 100000)
    assert contour is not None
    assert area == pytest.approx(math.pi * PUPIL_R ** 2, rel=0.1)
    assert gray.shape == (H, W) and mask.shape == (H, W)


def test_find_pupil_ignora_las_pestanas():
    contour, area, _, _ = detector.find_pupil(CLOSED[0], 80, 200, 100000)
    assert contour is None and area == 0


def test_calibracion(calib):
    assert 25 < calib.thr < 110                       # entre la pupila y el iris
    assert calib.open_area == pytest.approx(math.pi * PUPIL_R ** 2, rel=0.15)
    assert 0 < calib.min_std < calib.closed_std < calib.open_std


def test_calibracion_mensajes():
    cal = Calibrator()
    cal.feed(OPEN[0], 0.0)
    assert cal.message.startswith(calibration.OPEN_MSG)
    cal.feed(OPEN[0], calibration.READY_SECONDS + calibration.OPEN_SECONDS + 0.01)
    assert cal.message.startswith(calibration.CLOSED_MSG)
    assert not cal.done


def test_calibracion_sin_cerrar_el_ojo_avisa():
    cal = Calibrator()
    t = 0.0
    while not cal.done:
        cal.feed(OPEN[int(t * 30) % 4], t)            # nunca cierra el ojo
        t += DT
    assert "cerrado" in cal.warning


def test_calibration_guarda_y_carga(tmp_path, calib):
    path = tmp_path / "calib.json"
    calib.save(path)
    assert Calibration.load(path) == calib
    assert Calibration.load(tmp_path / "no_existe.json") is None
    (tmp_path / "roto.json").write_text("{nope")
    assert Calibration.load(tmp_path / "roto.json") is None


def test_classify(calib):
    st = detector.classify(OPEN[1], calib)
    assert st.status == "open"
    assert st.center == pytest.approx((W / 2, H / 2), abs=3)
    assert detector.classify(CLOSED[1], calib).status == "closed"
    assert detector.classify(FLAT, calib).status == "lost"
    assert detector.classify(None, calib).status == "lost"


def test_classify_plan_b(calib, monkeypatch):
    monkeypatch.setattr(detector, "USE_STD_ONLY", True)
    assert detector.classify(OPEN[2], calib).status == "open"
    assert detector.classify(CLOSED[2], calib).status == "closed"
    assert detector.classify(FLAT, calib).status == "lost"


@pytest.mark.parametrize("frame", [OPEN[0], CLOSED[0], FLAT, None])
def test_annotate_tamano(frame, calib):
    st = detector.classify(frame, calib)
    view = annotate(frame, st, calib)
    assert view.shape == (VIEW_H, VIEW_W, 3) and view.dtype == np.uint8
    if frame is not None:
        assert frame.shape == (H, W, 3)               # no toca el original


def test_annotate_lost_pinta_borde_rojo(calib):
    view = annotate(FLAT, detector.classify(FLAT, calib), calib)
    assert tuple(view[2, VIEW_W // 2]) == (0, 0, 220)


def test_small_mask(calib):
    st = detector.classify(OPEN[0], calib)
    assert small_mask(st.mask).shape == (MASK_H, MASK_W)
    assert small_mask(None) is None


# --- pipeline ---

class FakeCamera:
    fps = 30.0

    def __init__(self, frame=None):
        self.frame = frame
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def latest(self):
        return self.frame, time.monotonic()


def _pipeline(tmp_path, calib):
    calib.save(tmp_path / "calib.json")
    events = []
    p = PipelineSource(FakeCamera(), events.append, calib_path=tmp_path / "calib.json")
    p._load_calibration()
    return p, events


def _feed(p, pattern, t0=0.0):
    """pattern: lista de (frames, 'open'|'closed'). Devuelve el t final."""
    t, i = t0, 0
    for n, status in pattern:
        for _ in range(n):
            p._step((OPEN if status == "open" else CLOSED)[i % 4], t)
            t, i = t + DT, i + 1
    return t


def test_pipeline_clic_izquierdo(tmp_path, calib):
    p, events = _pipeline(tmp_path, calib)
    _feed(p, [(15, "open"), (24, "closed"), (15, "open")])
    assert [e.type for e in events] == [E.CALIBRATED, E.EYE_CLOSED, E.STAGE_LEFT, E.CLICK_LEFT]
    view = p.latest_view()
    assert view.status == "open" and view.frame.shape == (VIEW_H, VIEW_W, 3)
    assert view.open_area == calib.open_area and view.thr == calib.thr


def test_pipeline_espera_ojo_abierto_al_empezar(tmp_path, calib):
    p, events = _pipeline(tmp_path, calib)
    _feed(p, [(30, "closed"), (15, "open")])          # arranca con el ojo cerrado
    assert [e.type for e in events] == [E.CALIBRATED]


def test_pipeline_recalibrar_no_hace_clics(tmp_path, calib):
    p, events = _pipeline(tmp_path, calib)
    t = _feed(p, [(15, "open"), (20, "closed")])     # cierre en curso
    p.recalibrate()
    p._apply_requests()
    assert events[-1].type == E.CANCELLED
    n = len(events)
    ready = calibration.READY_SECONDS
    t = _feed(p, [(round((ready + calibration.OPEN_SECONDS) / DT) + 2, "open"),
                  (round((ready + calibration.CLOSED_SECONDS) / DT) + 2, "closed")], t)
    assert [e.type for e in events[n:]] == [E.CALIBRATED]
    assert p.latest_view().message == "Calibrado"
    _feed(p, [(30, "closed"), (15, "open")], t)       # sigue cerrado tras calibrar: sin clic
    assert [e.type for e in events[n:]] == [E.CALIBRATED]
    assert Calibration.load(tmp_path / "calib.json") == p.calib


def test_pipeline_set_threshold(tmp_path, calib):
    p, _ = _pipeline(tmp_path, calib)
    p.set_threshold(300)
    p._apply_requests()
    assert p.calib.thr == 255
    assert Calibration.load(tmp_path / "calib.json").thr == 255


def test_pipeline_sin_calib_json_calibra(tmp_path):
    events = []
    p = PipelineSource(FakeCamera(), events.append, calib_path=tmp_path / "calib.json")
    p._load_calibration()
    assert events == [] and p._calibrator is not None
    _feed(p, [(5, "open")])
    assert p.latest_view().message.startswith(calibration.OPEN_MSG)


def test_pipeline_hilo_arranca_y_para(tmp_path, calib):
    calib.save(tmp_path / "calib.json")
    events = []
    cam = FakeCamera(OPEN[0])
    p = PipelineSource(cam, events.append, calib_path=tmp_path / "calib.json")
    p.start()
    try:
        deadline = time.monotonic() + 2
        while p.latest_view() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert p.latest_view() is not None and p.latest_view().status == "open"
    finally:
        p.stop()
    assert cam.started and cam.stopped
    assert events[0].type == E.CALIBRATED


def test_pipeline_sin_frames_es_lost(tmp_path, calib, monkeypatch):
    monkeypatch.setattr("eyeclick.vision.pipeline.STALE_S", 0.05)
    calib.save(tmp_path / "calib.json")
    events = []
    p = PipelineSource(FakeCamera(None), events.append, calib_path=tmp_path / "calib.json")
    p.start()
    try:
        deadline = time.monotonic() + 2
        while E.EYE_LOST not in [e.type for e in events] and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        p.stop()
    assert E.EYE_LOST in [e.type for e in events]
    assert p.latest_view().status == "lost"


# --- video ---

def test_video_file_source(tmp_path):
    path = str(tmp_path / "ojo.avi")
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 20, (160, 120))
    if not out.isOpened():
        pytest.skip("no hay codec MJPG")
    for i in range(10):
        out.write(np.full((120, 160, 3), i * 20, np.uint8))
    out.release()

    src = VideoFileSource(path)
    src.start()
    try:
        assert src.fps == pytest.approx(20)
        deadline = time.monotonic() + 2
        while src.latest()[0] is None and time.monotonic() < deadline:
            time.sleep(0.01)
        frame, t1 = src.latest()
        assert frame.shape == (120, 160, 3)
        time.sleep(0.7)                               # > 10 frames a 20 FPS: ya dio la vuelta
        assert src.latest()[1] > t1
    finally:
        src.stop()


def test_video_inexistente():
    with pytest.raises(RuntimeError):
        VideoFileSource("no_existe.mp4").start()
