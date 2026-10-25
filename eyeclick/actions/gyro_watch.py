"""Avisos del ESP32 por el cursor: "calibrando el giroscopio" y "listo".  (SWE 2)

El ESP32 (firmware/Calemouse) se recalibra solo al sacudir la cabeza unos segundos,
sin entrar a su página. Pero solo es un mouse BLE: no puede mandarle texto a EyeClick.
Así que avisa con el propio cursor (cursorBlip en el firmware):
    al empezar: baja SIGNAL_PX y vuelve al mismo píxel, luego sube y vuelve   -> "start"
    al terminar: igual pero a la derecha/izquierda                            -> "done"
Un movimiento de cabeza normal casi nunca va en un solo eje y regresa EXACTO al píxel
anterior en el siguiente reporte. Los movimientos inyectados (los de EyeClick al hacer
clic en la posición guardada, que también van y vuelven) se ignoran: solo cuentan los
del mouse de verdad (el ESP32).

BlipDetector es puro (se prueba con posiciones inventadas); GyroWatch lo conecta a un
listener de pynput en su hilo y llama on_signal("start" | "done") desde ese hilo:
app.py lo pasa por una cola al hilo principal.
"""
import logging
import time

log = logging.getLogger(__name__)

MIN_PX = 15             # el ESP32 manda 40; con la aceleración de Windows puede variar
TOLERANCE = 1           # px de diferencia al volver (redondeo de la aceleración)
MAX_GAP_S = 0.2         # el ESP32 vuelve a los 30 ms
REPEAT_S = 1.0          # cada aviso va y vuelve dos veces: contar solo una


class BlipDetector:
    def __init__(self):
        self.pos = None
        self.out = None             # (dx, dy, t) del último movimiento en un solo eje
        self.last = {}              # tipo -> t del último aviso

    def feed(self, x, y, t, injected=False):
        """Posición nueva del cursor -> "start", "done" o None."""
        prev, self.pos = self.pos, (x, y)
        if prev is None or injected:
            self.out = None
            return None
        dx, dy = x - prev[0], y - prev[1]
        out, self.out = self.out, None
        if out is not None and t - out[2] <= MAX_GAP_S and _returns(out, dx, dy):
            kind = "start" if out[0] == 0 else "done"
            if t - self.last.get(kind, -1e9) > REPEAT_S:
                self.last[kind] = t
                return kind
            return None
        if (dx == 0) != (dy == 0) and max(abs(dx), abs(dy)) >= MIN_PX:
            self.out = (dx, dy, t)
        return None


def _returns(out, dx, dy):
    ox, oy, _ = out
    return abs(dx + ox) <= TOLERANCE and abs(dy + oy) <= TOLERANCE and (dx == 0) == (ox == 0)


class GyroWatch:
    def __init__(self, on_signal):
        self.on_signal = on_signal
        self.detector = BlipDetector()
        self._listener = None

    def start(self):
        try:
            from pynput import mouse
            self._listener = mouse.Listener(on_move=self._on_move, daemon=True)
            self._listener.start()
        except Exception:
            log.warning("No se pueden ver los avisos del ESP32 (sacudir para calibrar)", exc_info=True)
        return self

    def stop(self):
        if self._listener is not None:
            self._listener.stop()

    def _on_move(self, x, y, injected=False):
        kind = self.detector.feed(x, y, time.monotonic(), injected)
        if kind is not None:
            log.info("ESP32: %s", "calibrando giroscopio" if kind == "start" else "giroscopio calibrado")
            self.on_signal(kind)
