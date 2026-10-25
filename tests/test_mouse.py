"""Pruebas de mouse.py con un mouse falso (sin pynput).  (SWE 2)"""
from eyeclick.actions.mouse import MouseActions
from eyeclick.config import CLICK_COOLDOWN, DOUBLE_RADIUS, DOUBLE_WINDOW
from eyeclick.events import EventType as E
from eyeclick.events import EyeEvent


class FakeMouse:
    def __init__(self):
        self._pos = (0, 0)
        self.clicks = []        # (botón, posición al hacer clic) o (botón, posición, veces)
        self.held = None        # botón apretado
        self.log = []           # ("press" | "release" | "move", ...) para el arrastre

    @property
    def position(self):
        return self._pos

    @position.setter
    def position(self, pos):
        self._pos = pos
        if self.held:
            self.log.append(("move", pos))

    def click(self, button, count=1):
        self.clicks.append((button, self.position) if count == 1 else (button, self.position, count))

    def press(self, button):
        self.held = button
        self.log.append(("press", button, self.position))

    def release(self, button):
        assert self.held == button
        self.held = None
        self.log.append(("release", button, self.position))


def make():
    m = FakeMouse()
    notes = []
    return MouseActions(controller=m, buttons=("L", "R"), on_action=notes.append), m, notes


def cierre(actions, mouse, t, tipo, se_movio_a=(500, 500), en=(100, 100)):
    """Cierra en `en`, el giroscopio mueve el cursor y abre con un clic de `tipo`."""
    mouse.position = en
    actions.handle(EyeEvent(E.EYE_CLOSED, t))
    mouse.position = se_movio_a
    actions.handle(EyeEvent(tipo, t + 0.8, 0.8))


def test_clic_izquierdo_en_la_posicion_guardada():
    a, m, _ = make()
    cierre(a, m, 0.0, E.CLICK_LEFT)
    assert m.clicks == [("L", (100, 100))]


def test_el_cursor_vuelve_a_donde_lo_dejo_el_giroscopio():
    a, m, _ = make()
    cierre(a, m, 0.0, E.CLICK_LEFT, se_movio_a=(500, 500))
    assert m.position == (500, 500)


def test_clic_derecho():
    a, m, _ = make()
    cierre(a, m, 0.0, E.CLICK_RIGHT)
    assert m.clicks == [("R", (100, 100))]


def test_cancelado_no_hace_clic():
    a, m, _ = make()
    a.handle(EyeEvent(E.EYE_CLOSED, 0.0))
    a.handle(EyeEvent(E.CANCELLED, 0.2, 0.2))
    a.handle(EyeEvent(E.CLICK_LEFT, 0.9, 0.9))     # clic sin su EYE_CLOSED
    assert m.clicks == []


def test_cooldown():
    a, m, _ = make()
    cierre(a, m, 0.0, E.CLICK_LEFT)                 # clic en t=0.8
    a.handle(EyeEvent(E.EYE_CLOSED, 0.85))
    a.handle(EyeEvent(E.CLICK_LEFT, 0.8 + CLICK_COOLDOWN / 2))
    assert len(m.clicks) == 1
    cierre(a, m, 1.0 + CLICK_COOLDOWN, E.CLICK_LEFT)
    assert len(m.clicks) == 2


def test_pausa_no_hace_clic():
    a, m, _ = make()
    assert a.toggle_pause() is True
    cierre(a, m, 0.0, E.CLICK_LEFT)
    assert m.clicks == []
    assert a.toggle_pause() is False
    cierre(a, m, 2.0, E.CLICK_LEFT)
    assert len(m.clicks) == 1


def test_pausar_a_mitad_de_un_cierre_no_hace_clic():
    a, m, _ = make()
    a.handle(EyeEvent(E.EYE_CLOSED, 0.0))
    a.set_paused(True)
    a.set_paused(False)
    a.handle(EyeEvent(E.CLICK_LEFT, 0.8, 0.8))
    assert m.clicks == []


# --- doble clic ---

def test_dos_clics_izquierdos_seguidos_hacen_doble_clic():
    a, m, notes = make()
    cierre(a, m, 0.0, E.CLICK_LEFT)                         # clic en t=0.8
    cierre(a, m, 0.8 + DOUBLE_WINDOW - 0.8 - 0.1, E.CLICK_LEFT, en=(110, 95))
    assert m.clicks == [("L", (100, 100)), ("L", (100, 100), 2)]   # donde fue el primero
    assert m.position == (500, 500)
    assert notes == ["double click ✓"]


def test_tercer_clic_empieza_de_nuevo():
    a, m, _ = make()
    for t in (0.0, 1.0, 2.0):
        cierre(a, m, t, E.CLICK_LEFT)
    assert [len(c) for c in m.clicks] == [2, 3, 2]          # simple, doble, simple


def test_lejos_o_tarde_no_es_doble_clic():
    a, m, _ = make()
    cierre(a, m, 0.0, E.CLICK_LEFT)
    cierre(a, m, 1.0, E.CLICK_LEFT, en=(100 + DOUBLE_RADIUS + 5, 100))
    cierre(a, m, 1.0 + DOUBLE_WINDOW + 0.5, E.CLICK_LEFT, en=(100 + DOUBLE_RADIUS + 5, 100))
    assert all(len(c) == 2 for c in m.clicks) and len(m.clicks) == 3


def test_clic_derecho_no_cuenta_para_doble():
    a, m, _ = make()
    cierre(a, m, 0.0, E.CLICK_RIGHT)
    cierre(a, m, 1.0, E.CLICK_LEFT)
    assert m.clicks == [("R", (100, 100)), ("L", (100, 100))]


# --- arrastrar ---

def test_arrastrar_agarra_y_suelta_con_parpadeos():
    a, m, notes = make()
    assert a.toggle_drag() == "armed"
    cierre(a, m, 0.0, E.CLICK_LEFT, en=(100, 100), se_movio_a=(120, 100))
    assert a.drag == "holding" and m.held == "L"
    assert m.log[0] == ("press", "L", (100, 100))
    m.position = (400, 300)                                 # la cabeza arrastra
    cierre(a, m, 2.0, E.CLICK_LEFT, en=(400, 300), se_movio_a=(410, 300))
    assert a.drag is None and m.held is None
    assert ("release", "L", (400, 300)) in m.log
    assert m.position == (410, 300) and m.clicks == []
    assert notes == ["drag: blink to grab", "grabbed", "dropped ✓"]


def test_cancelar_arrastre_suelta_el_boton():
    a, m, notes = make()
    a.toggle_drag()
    cierre(a, m, 0.0, E.CLICK_LEFT)
    assert a.toggle_drag() is None and m.held is None
    assert notes[-1] == "drag cancelled"
    a.toggle_drag()
    assert a.toggle_drag() is None                          # armado y cancelado: nada que soltar
    assert [e[0] for e in m.log].count("release") == 1


def test_clic_derecho_o_pausa_cancelan_el_arrastre():
    a, m, _ = make()
    a.toggle_drag()
    cierre(a, m, 0.0, E.CLICK_LEFT)
    cierre(a, m, 2.0, E.CLICK_RIGHT)
    assert a.drag is None and m.held is None and m.clicks == []
    a.toggle_drag()
    cierre(a, m, 4.0, E.CLICK_LEFT)
    a.set_paused(True)
    assert a.drag is None and m.held is None
    assert a.toggle_drag() is None                          # en pausa no se arma


def test_soltar_no_cuenta_para_doble_clic():
    a, m, _ = make()
    a.toggle_drag()
    cierre(a, m, 0.0, E.CLICK_LEFT)
    cierre(a, m, 1.0, E.CLICK_LEFT)                         # suelta
    cierre(a, m, 2.0, E.CLICK_LEFT)                         # clic simple, no doble
    assert m.clicks == [("L", (100, 100))]



def test_intercept_se_come_el_clic():
    a, m, _ = make()
    a.intercept = lambda ev: ev.type == E.CLICK_LEFT
    cierre(a, m, 0.0, E.CLICK_LEFT)
    assert m.clicks == [] and a.saved is None
    cierre(a, m, 2.0, E.CLICK_RIGHT)
    assert m.clicks == [("R", (100, 100))]



# --- arrastrar con el ojo cerrado más de DRAG_AT ---

def test_ojo_cerrado_3s_arrastra_y_suelta_al_abrir():
    a, m, notes = make()
    m.position = (100, 100)
    a.handle(EyeEvent(E.EYE_CLOSED, 0.0))
    m.position = (110, 100)                                  # la cabeza se movió un poco
    a.handle(EyeEvent(E.STAGE_DRAG, 3.0, 3.0))
    assert m.held == "L" and m.log[0] == ("press", "L", (100, 100))   # agarra donde cerró
    assert m.position == (110, 100)
    m.position = (400, 300)                                  # arrastra con la cabeza
    a.handle(EyeEvent(E.DRAG_END, 4.0, 4.0))
    assert m.held is None and m.log[-1] == ("release", "L", (400, 300))
    assert m.clicks == [] and notes == ["dragging", "dropped ✓"]


def test_pausa_suelta_el_arrastre_del_ojo():
    a, m, _ = make()
    a.handle(EyeEvent(E.EYE_CLOSED, 0.0))
    a.handle(EyeEvent(E.STAGE_DRAG, 3.0, 3.0))
    a.set_paused(True)
    assert m.held is None
    a.set_paused(False)
    a.handle(EyeEvent(E.DRAG_END, 4.0, 4.0))                 # ya estaba suelto: nada
    assert [e[0] for e in m.log].count("release") == 1


def test_arrastre_del_ojo_sin_cierre_guardado_no_hace_nada():
    a, m, _ = make()
    a.handle(EyeEvent(E.STAGE_DRAG, 3.0, 3.0))               # el cierre empezó en pausa
    a.handle(EyeEvent(E.DRAG_END, 4.0, 4.0))
    assert m.log == [] and m.held is None


def test_con_drag_f10_activo_el_ojo_no_arrastra_otra_vez():
    a, m, _ = make()
    a.toggle_drag()
    cierre(a, m, 0.0, E.CLICK_LEFT)                          # F10: agarrado
    a.handle(EyeEvent(E.EYE_CLOSED, 2.0))
    a.handle(EyeEvent(E.STAGE_DRAG, 5.0, 3.0))
    assert [e[0] for e in m.log].count("press") == 1
