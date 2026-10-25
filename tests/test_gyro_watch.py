"""Avisos del ESP32 por el cursor (gyro_watch.py) y cómo los muestra la app."""
import queue

from eyeclick.actions.gyro_watch import MAX_GAP_S, BlipDetector


def feed(det, moves, t0=0.0, dt=0.03, injected=False):
    """moves: lista de (x, y); devuelve los avisos que salieron."""
    out = []
    for i, (x, y) in enumerate(moves):
        kind = det.feed(x, y, t0 + i * dt, injected)
        if kind:
            out.append(kind)
    return out


def blip(x, y, dx, dy):
    """Lo que manda cursorBlip del firmware: sale, vuelve, sale al revés, vuelve."""
    return [(x + dx, y + dy), (x, y), (x - dx, y - dy), (x, y)]


def test_aviso_de_inicio_y_de_fin():
    det = BlipDetector()
    assert feed(det, [(500, 500)] + blip(500, 500, 0, 40)) == ["start"]     # una vez, no dos
    assert feed(det, blip(500, 500, 40, 0), t0=2.0) == ["done"]


def test_con_aceleracion_de_windows_y_redondeo():
    det = BlipDetector()
    assert feed(det, [(500, 500), (500, 571), (500, 501)]) == ["start"]      # 71 px y vuelve a 1 px


def test_pegado_al_borde_una_mitad_basta():
    det = BlipDetector()
    # en el borde de abajo la bajada no se mueve; la subida sí se ve
    assert feed(det, [(500, 1079), (500, 1079), (500, 1079), (500, 1039), (500, 1079)]) == ["start"]


def test_movimiento_normal_no_es_aviso():
    det = BlipDetector()
    head = [(500 + 3 * i, 500 + 2 * i) for i in range(30)]                   # girar en diagonal
    shake = [(500 + (40 if i % 2 else -40), 500 + i % 3) for i in range(30)]  # sacudir: casi nunca exacto
    assert feed(det, head + shake) == []
    assert feed(det, [(500, 500), (500, 540), (503, 500)]) == []             # vuelve, pero no al mismo píxel
    assert feed(det, [(500, 500), (500, 505), (500, 500)]) == []             # muy chico


def test_vuelta_tardia_no_cuenta():
    det = BlipDetector()
    assert feed(det, [(500, 500), (500, 540), (500, 500)], dt=MAX_GAP_S + 0.1) == []


def test_movimientos_de_eyeclick_se_ignoran():
    """Al hacer clic, EyeClick salta a la posición guardada y vuelve: es inyectado."""
    det = BlipDetector()
    det.feed(500, 500, 0.0)
    assert det.feed(500, 540, 0.01, injected=True) is None
    assert det.feed(500, 500, 0.02, injected=True) is None


class FakeShow:
    def __init__(self):
        self.calls = []

    def set_gyro(self, state, note=None):
        self.calls.append((state, note))


def test_la_app_muestra_calibrando_y_bloquea_clics(monkeypatch):
    from eyeclick import app as app_mod
    from eyeclick.events import EventType as E
    from eyeclick.events import EyeEvent

    a = app_mod.App.__new__(app_mod.App)            # sin ventanas: solo la lógica del giroscopio
    a._gyro_signals, a._gyro_until = queue.SimpleQueue(), None
    a.overlay, a.monitor = FakeShow(), FakeShow()
    beeps = []
    a.feedback = type("F", (), {"beep": lambda self, f, ms=80: beeps.append(f)})()
    a.dictation = type("D", (), {"state": "idle"})()
    now = [100.0]
    monkeypatch.setattr(app_mod.time, "monotonic", lambda: now[0])

    a._gyro_signals.put("start")
    a._check_gyro()
    assert a.monitor.calls[-1] == ("calibrating", None)
    assert a._dictation_blink(EyeEvent(E.CLICK_LEFT)) is True          # parpadeo ignorado
    a._gyro_signals.put("done")
    a._check_gyro()
    assert a.monitor.calls[-1] == (None, "gyro calibrated ✓") and beeps
    assert a._dictation_blink(EyeEvent(E.CLICK_LEFT)) is False         # clics normales otra vez

    a._gyro_signals.put("start")
    a._check_gyro()
    now[0] += app_mod.GYRO_TIMEOUT_S + 1
    a._check_gyro()
    assert a.overlay.calls[-1][0] is None and "not calibrated" in a.overlay.calls[-1][1]
