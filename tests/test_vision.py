"""Pruebas de visión con ojos sintéticos (sin cámara).  (SWE 1)

Ojo abierto: piel clara, iris gris y pupila negra grande (la cámara está a 2-3 cm).
Ojo cerrado: piel con sombra y una línea delgada de pestañas.
Ceja: mancha oscura y redonda muy por encima del ojo (no debe contar como ojo abierto).
Imagen plana: lo que se ve con la cámara tapada o sin señal.

El detector trabaja a la mitad de resolución (detector.WORK_W = 320): las áreas
y coordenadas que devuelve están en esa escala (WORK).
"""
import math
import time
from dataclasses import replace

import cv2
import numpy as np
import pytest

from eyeclick.config import VIEW_H, VIEW_W
from eyeclick.events import EventType as E
from eyeclick.vision import calibration, detector, model
from eyeclick.vision.annotate import MASK_H, MASK_W, annotate, small_mask
from eyeclick.vision.calibration import Calibration, Calibrator
from eyeclick.vision.camera import VideoFileSource
from eyeclick.vision.pipeline import PipelineSource

H, W = 480, 640
PUPIL_R = 80
WORK = detector.WORK_W / W
DT = 1 / 30


def _eye(is_open, seed, brow=False):
    rng = np.random.default_rng(seed)
    img = np.tile(np.linspace(140, 190, W), (H, 1))            # piel con sombra
    if is_open:
        cv2.circle(img, (W // 2, H // 2), 150, 110, -1)       # iris
        cv2.circle(img, (W // 2, H // 2), PUPIL_R, 25, -1)    # pupila
        cv2.circle(img, (W // 2 + 30, H // 2 - 30), 8, 250, -1)  # reflejo del LED
    else:
        cv2.line(img, (100, H // 2), (W - 100, H // 2 + 20), 60, 3)  # pestañas
    if brow:
        cv2.ellipse(img, (W // 2, 40), (110, 60), 0, 0, 360, 25, -1)   # ceja
    img += rng.normal(0, 6, img.shape)
    return cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


OPEN = [_eye(True, s) for s in range(4)]
CLOSED = [_eye(False, s) for s in range(4)]
BROW = _eye(False, 0, brow=True)
FLAT = np.full((H, W, 3), 128, np.uint8)


def _calibrate(closed=CLOSED):
    """Alimenta las dos fases y espera el cálculo (corre en otro hilo)."""
    cal = Calibrator()
    t, i = 0.0, 0
    while cal.message != calibration.WORKING_MSG:
        phase_open = t < calibration.READY_SECONDS + calibration.OPEN_SECONDS
        cal.feed((OPEN if phase_open else closed)[i % len(closed)], t)
        t, i = t + DT, i + 1
        assert t < 20, "la calibración no termina"
    assert cal.wait(10)
    return cal


@pytest.fixture(scope="module", autouse=True)
def sin_modelo():
    """Estas pruebas son del detector clásico: la red (model.py) no participa.
    La red tiene las suyas en test_model.py."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(model, "logit", lambda frame: None)
        yield


@pytest.fixture(scope="module")
def calib(sin_modelo):
    cal = _calibrate()
    assert cal.warning == ""
    return cal.result


def test_find_pupil_encuentra_la_pupila():
    contour, area, gray, mask = detector.find_pupil(OPEN[0], 60)
    assert contour is not None
    assert area == pytest.approx(math.pi * (PUPIL_R * WORK) ** 2, rel=0.1)
    assert gray.shape == (H * WORK, W * WORK) and mask.shape == gray.shape


def test_find_pupil_ignora_las_pestanas():
    contour, area, _, _ = detector.find_pupil(CLOSED[0], 80)
    assert contour is None and area == 0


def test_find_pupil_con_reflejo_mide_toda_la_pupila():
    # el reflejo del LED queda adentro de la pupila: se rellena y no la parte
    contour, area, _, _ = detector.find_pupil(OPEN[0], 60)
    assert area > 0.95 * math.pi * (PUPIL_R * WORK) ** 2


def test_calibracion(calib):
    assert 25 < calib.thr < 140                       # sobre la pupila, bajo la piel
    assert calib.cx == pytest.approx(W * WORK / 2, abs=3)
    assert calib.cy == pytest.approx(H * WORK / 2, abs=3)
    assert calib.ref_level > 0
    assert 0 < calib.min_std < calib.closed_std < calib.open_std


def test_calibracion_elige_el_umbral_alto_con_margen(monkeypatch):
    # hasta 30 el ojo cerrado se ve cerrado; desde 31 se ve abierto -> 30 menos el margen
    def fake(thr, ref, opened, closed):
        closed_rate = 0.0 if thr <= 30 else 0.9
        return 1.0 - closed_rate, Calibration(thr=thr), 1.0, closed_rate
    monkeypatch.setattr(Calibrator, "_try", staticmethod(fake))
    gray = np.tile(np.arange(10, 70, dtype=np.uint8), (60, 1))     # percentil 1 ~10, mediana ~40
    result = Calibrator()._compute([gray], [gray])
    assert result.thr == 30 - calibration.SAFETY_STEPS


def test_calibracion_sin_umbral_que_separe_usa_el_centro(monkeypatch):
    scores = {thr: 0.5 for thr in range(10, 40)}
    scores[12] = 0.7                                               # pico suelto: ruido
    fake = lambda thr, ref, opened, closed: (scores.get(thr, 0.0), Calibration(thr=thr), 0.9, 0.4)  # noqa: E731
    monkeypatch.setattr(Calibrator, "_try", staticmethod(fake))
    gray = np.tile(np.arange(10, 70, dtype=np.uint8), (60, 1))
    assert 20 <= Calibrator()._compute([gray], [gray]).thr <= 30


def test_ceja_no_cuenta_como_ojo_abierto(calib):
    assert detector.classify(BROW, calib).status == "closed"
    sin_filtro = replace(calib, cx=-1.0, cy=-1.0)
    assert detector.classify(BROW, sin_filtro).status == "open"      # sin el filtro, sí la tomaría


def test_contorno_dibujado_no_incluye_pestanas(calib):
    top_limpio = detector.classify(OPEN[0], calib).contour.reshape(-1, 2)[:, 1].min()
    img = OPEN[0].copy()
    cv2.rectangle(img, (W // 2 - 30, 10), (W // 2 + 30, H // 2), (25, 25, 25), -1)   # pestañas pegadas arriba
    st = detector.classify(img, calib)
    assert st.status == "open"
    r = math.sqrt(calib.open_area / math.pi)
    # sin el recorte subiría hasta y=5; con él, a lo sumo (REFINE - 1) radios sobre el iris
    assert st.contour.reshape(-1, 2)[:, 1].min() >= top_limpio - (detector.REFINE - 1) * r - 2


def test_calibracion_mensajes():
    cal = Calibrator()
    cal.feed(OPEN[0], 0.0)
    assert cal.message.startswith(calibration.OPEN_MSG)
    cal.feed(OPEN[0], calibration.READY_SECONDS + calibration.OPEN_SECONDS + 0.01)
    assert cal.message.startswith(calibration.CLOSED_MSG)
    assert not cal.done


def test_calibracion_sin_cerrar_el_ojo_avisa():
    cal = _calibrate(closed=OPEN)                      # nunca cierra el ojo
    assert "closed" in cal.warning


def test_calibration_guarda_y_carga(tmp_path, calib):
    path = tmp_path / "calib.json"
    calib.save(path)
    assert Calibration.load(path) == calib
    assert Calibration.load(tmp_path / "no_existe.json") is None
    (tmp_path / "roto.json").write_text("{nope")
    assert Calibration.load(tmp_path / "roto.json") is None
    (tmp_path / "viejo.json").write_text('{"thr": 20, "open_area": 16004.0, "min_std": 5.9}')
    assert Calibration.load(tmp_path / "viejo.json") is None      # otras unidades: recalibrar


def test_classify(calib):
    st = detector.classify(OPEN[1], calib)
    assert st.status == "open"
    assert st.center == pytest.approx((W * WORK / 2, H * WORK / 2), abs=3)
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
    assert p._calibrator.wait(10)                     # el cálculo corre en otro hilo
    t = _feed(p, [(1, "closed")], t)
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


def test_iris_pegado_a_pestanas_gruesas_sigue_abierto(calib):
    # el párpado tapa la parte de arriba del iris y la línea de pestañas se pega al blob
    img = OPEN[0].copy()
    cv2.line(img, (W // 2 - 230, H // 2 - 70), (W // 2 + 230, H // 2 - 70), (25, 25, 25), 26)
    assert detector.classify(img, calib).status == "open"


def test_sombra_en_la_esquina_no_se_rescata(calib):
    img = CLOSED[0].copy()
    # sombra de la esquina: mancha del tamaño del iris lejos del centro, con una cola larga
    cv2.circle(img, (130, H // 2), 75, (25, 25, 25), -1)
    cv2.line(img, (130, H // 2 + 40), (600, H // 2 + 40), (25, 25, 25), 46)
    assert detector._circularity(*_biggest_blob(img, calib)) < detector.MIN_CIRCULARITY  # no es redonda
    assert detector.classify(img, calib).status == "closed"


def _biggest_blob(img, calib):
    gray = detector.preprocess(img)
    _, mask = cv2.threshold(gray, detector.effective_thr(calib.thr, gray, calib.ref_level), 255, cv2.THRESH_BINARY_INV)
    cs, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cs, key=cv2.contourArea)
    return c, cv2.contourArea(c)
