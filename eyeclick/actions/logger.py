"""Registro de eventos en events_log.csv.  (SWE 2, suscriptor del bus)

Una fila por evento:
    time       -> time.time() (segundos epoch, para ordenar y restar)
    datetime   -> la misma hora legible (ISO, hora local)
    event      -> ev.type.value
    duration   -> segundos que el ojo estuvo cerrado (CLICK_* y CANCELLED), 3 decimales
    t          -> ev.t (time.monotonic del evento, para medir entre eventos sin saltos de reloj)

Se revisa después de la prueba con usuario (clics falsos, duraciones reales).
El archivo se abre en modo 'a' al primer evento: varias corridas se acumulan en
el mismo CSV y el encabezado solo se escribe si el archivo está vacío. Cada fila
se escribe con flush, por si la app se cae. Si no se puede escribir, se avisa una
vez en el log y el registro se desactiva en lugar de fallar en cada evento.

TODO (SWE 2):
- [x] Abrir el archivo en modo 'a' con newline='' y escribir encabezado si está vacío.
- [x] handle(): escribir la fila y hacer flush (por si la app se cae).
- [x] close(): cerrar el archivo (lo llama app.py al salir).
"""
import csv
import logging
import time
from datetime import datetime

log = logging.getLogger(__name__)

LOG_FILE = "events_log.csv"
HEADER = ["time", "datetime", "event", "duration", "t"]
TYPES = None    # le interesan todos los eventos


class EventLogger:
    def __init__(self, path=LOG_FILE):
        self.path = path
        self._f = None
        self._w = None
        self._broken = False

    def handle(self, ev):
        if self._broken:
            return
        try:
            if self._f is None:
                self._open()
            now = time.time()
            self._w.writerow([
                f"{now:.3f}",
                datetime.fromtimestamp(now).isoformat(timespec="milliseconds"),
                ev.type.value,
                f"{ev.duration:.3f}",
                f"{ev.t:.3f}",
            ])
            self._f.flush()
        except OSError:
            self._broken = True
            log.warning("No se pudo escribir %s; el registro queda desactivado.", self.path, exc_info=True)
            self.close()

    def close(self):
        if self._f:
            try:
                self._f.close()
            except OSError:
                pass
        self._f = self._w = None

    def _open(self):
        self._f = open(self.path, "a", newline="", encoding="utf-8")
        self._w = csv.writer(self._f)
        if self._f.tell() == 0:
            self._w.writerow(HEADER)
