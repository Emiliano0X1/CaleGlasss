"""Pruebas de la red abierto/cerrado (model.py) y de cómo la usan calibración y detector.

Los videos no están en git, así que la red real solo se prueba en que carga y responde;
la lógica de calibración y clasificación se prueba con una red falsa.
"""
import numpy as np
import pytest

from eyeclick.vision import calibration, detector, model
from eyeclick.vision.calibration import Calibration, Calibrator

H, W = 480, 640


def frame(value):
    rng = np.random.default_rng(int(value))
    return np.clip(rng.normal(value, 20, (H, W, 3)), 0, 255).astype(np.uint8)


OPEN, CLOSED = frame(80), frame(160)    # la red falsa: oscuro = abierto


@pytest.fixture
def fake_net(monkeypatch):
    monkeypatch.setattr(model, "logit", lambda f: (128.0 - float(f.mean())) / 10.0)


def calibrate(open_frame, closed_frame):
    cal = Calibrator()
    t = 0.0
    while cal.message != calibration.WORKING_MSG:
        open_phase = t < calibration.READY_SECONDS + calibration.OPEN_SECONDS
        cal.feed(open_frame if open_phase else closed_frame, t)
        t += 1 / 30
    assert cal.wait(10)
    return cal


@pytest.mark.skipif(not model.MODEL_FILE.exists(), reason="sin eye_model.onnx")
def test_la_red_real_carga_y_responde():
    assert model.available()
    score = model.logit(frame(100))
    assert isinstance(score, float) and np.isfinite(score)
    assert model.prepare(frame(100)).shape == (1, 3, model.IN_H, model.IN_W)
    assert model.prepare(frame(100)[..., 0]).shape == (1, 3, model.IN_H, model.IN_W)   # gris


def test_calibracion_usa_la_red_si_separa(fake_net):
    cal = calibrate(OPEN, CLOSED)
    r = cal.result
    lo, hi = (128 - 160) / 10, (128 - 80) / 10
    assert r.use_model and r.model_cut == pytest.approx(lo + calibration.MODEL_K * (hi - lo), abs=0.2)
    assert cal.warning == ""                            # los avisos de la pupila no aplican
    assert detector.classify(OPEN, r).status == "open"
    assert detector.classify(CLOSED, r).status == "closed"
    st = detector.classify(OPEN, r)
    assert st.score is not None


def test_si_la_red_no_separa_se_queda_el_clasico(fake_net):
    cal = calibrate(frame(120), frame(125))             # casi iguales para la red
    assert not cal.result.use_model
    assert "Model unsure" in cal.warning


def test_sin_modelo_no_cambia_nada(monkeypatch):
    monkeypatch.setattr(model, "logit", lambda f: None)
    cal = calibrate(OPEN, CLOSED)
    assert not cal.result.use_model


def test_con_use_model_pero_sin_archivo_usa_el_clasico(monkeypatch):
    monkeypatch.setattr(model, "logit", lambda f: None)
    calib = Calibration(use_model=True, model_cut=0.0)
    assert detector.classify(OPEN, calib).score is None     # no revienta: método clásico


def test_imagen_plana_sigue_siendo_lost(fake_net):
    r = calibrate(OPEN, CLOSED).result
    flat = np.full((H, W, 3), 128, np.uint8)
    assert detector.classify(flat, r).status == "lost"
