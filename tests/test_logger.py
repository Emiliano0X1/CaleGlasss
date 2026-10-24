"""Pruebas de logger.py con un archivo temporal.  (SWE 2)"""
import csv

from eyeclick.actions.logger import HEADER, EventLogger
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent


def read_rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_escribe_encabezado_y_filas(tmp_path):
    path = tmp_path / "events_log.csv"
    lg = EventLogger(path)
    lg.handle(EyeEvent(E.EYE_CLOSED, t=10.0))
    lg.handle(EyeEvent(E.CLICK_LEFT, t=10.8, duration=0.8))
    lg.close()
    rows = read_rows(path)
    assert rows[0] == HEADER
    assert [r[2] for r in rows[1:]] == ["eye_closed", "click_left"]
    assert rows[2][3] == "0.800" and rows[2][4] == "10.800"


def test_filas_visibles_antes_de_cerrar(tmp_path):
    """flush en cada fila: si la app se cae, el CSV ya tiene los eventos."""
    path = tmp_path / "events_log.csv"
    lg = EventLogger(path)
    lg.handle(EyeEvent(E.CLICK_RIGHT, duration=1.5))
    assert len(read_rows(path)) == 2
    lg.close()


def test_varias_corridas_acumulan_sin_repetir_encabezado(tmp_path):
    path = tmp_path / "events_log.csv"
    for _ in range(2):
        lg = EventLogger(path)
        lg.handle(EyeEvent(E.CANCELLED, duration=0.2))
        lg.close()
    rows = read_rows(path)
    assert rows.count(HEADER) == 1
    assert len(rows) == 3


def test_ruta_invalida_no_truena(tmp_path):
    lg = EventLogger(tmp_path / "no_existe" / "events_log.csv")
    lg.handle(EyeEvent(E.CLICK_LEFT))
    lg.handle(EyeEvent(E.CLICK_RIGHT))
    lg.close()
    lg.close()      # cerrar dos veces tampoco truena
