"""Registro de eventos en events_log.csv.  (SWE 2, suscriptor del bus)

Una fila por evento: [time.time(), ev.type.value, round(ev.duration, 3)].
Se revisa después de la prueba con usuario (clics falsos, duraciones reales).

TODO (SWE 2):
- [ ] Abrir el archivo en modo 'a' con newline='' y escribir encabezado si está vacío.
- [ ] handle(): escribir la fila y hacer flush (por si la app se cae).
- [ ] close(): cerrar el archivo (lo llama app.py al salir).
"""
import csv  # noqa: F401
import time  # noqa: F401

LOG_FILE = "events_log.csv"
TYPES = None    # le interesan todos los eventos


class EventLogger:
    def __init__(self, path=LOG_FILE):
        self.path = path
        self._f = None
        self._w = None

    def handle(self, ev):
        # TODO (SWE 2)
        raise NotImplementedError

    def close(self):
        if self._f:
            self._f.close()
