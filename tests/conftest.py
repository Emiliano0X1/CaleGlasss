"""Fixtures de tkinter compartidas por las pruebas de la UI.

Se crea UN solo tk.Tk() por sesión: en Windows, crear varios en el mismo proceso
a veces falla con "Can't find a usable tk.tcl". Cada prueba recibe su propia
ventana Toplevel, que sirve igual que una raíz para Monitor y Overlay.
"""
import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_session():
    try:
        r = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"sin pantalla: {e}")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def root(tk_session):
    win = tk.Toplevel(tk_session)
    yield win
    win.destroy()
