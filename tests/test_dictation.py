"""Pruebas del dictado sin micrófono ni modelo: audio falso, transcriptor falso."""
import numpy as np

from eyeclick.actions import dictation as d

DT = d.BLOCK / d.SR


def run(end, levels):
    """Alimenta niveles RMS bloque a bloque; devuelve (resultado, segundos)."""
    for i, rms in enumerate(levels):
        r = end.feed(rms, DT)
        if r is not None:
            return r, round((i + 1) * DT, 1)
    return None, None


def test_termina_tras_hablar_y_callar():
    end = d.SpeechEnd(silence_s=1.5, wait_s=6, max_s=30)
    levels = [0.002] * 3 + [0.1] * 10 + [0.002] * 30       # ruido, 1 s de voz, silencio
    assert run(end, levels) == ("done", 2.8)


def test_nadie_habla_se_cancela():
    end = d.SpeechEnd(silence_s=1.5, wait_s=6, max_s=30)
    assert run(end, [0.002] * 100) == ("nothing", 6.0)


def test_bip_al_inicio_no_cuenta_como_ruido_alto():
    end = d.SpeechEnd(silence_s=1.5, wait_s=6, max_s=30)
    levels = [0.3, 0.002, 0.002] + [0.05] * 5 + [0.002] * 20  # el bip queda fuera por la mediana
    assert run(end, levels)[0] == "done"


def test_tope_de_tiempo():
    end = d.SpeechEnd(silence_s=1.5, wait_s=6, max_s=3)
    assert run(end, [0.002] * 3 + [0.1] * 100) == ("done", 3.0)


class FakeMic:
    def __init__(self, blocks):
        self.blocks, self.closed = blocks, False

    def __call__(self, callback):
        for b in self.blocks:
            callback(b)
        return self

    def stop(self):
        pass

    def close(self):
        self.closed = True


def block(level):
    return np.full(d.BLOCK, level, np.float32)


def make(blocks, text="hello world"):
    states, typed, mic = [], [], FakeMic(blocks)
    dic = d.Dictation(on_state=lambda s, n=None: states.append((s, n)), transcriber=lambda audio: text,
                      open_mic=mic, type_text=typed.append,
                      end=lambda: d.SpeechEnd(silence_s=0.5, wait_s=2, max_s=10))
    return dic, states, typed, mic


def finish(dic):
    dic._thread.join(5)
    assert not dic._thread.is_alive()


def test_dicta_y_escribe_con_espacio():
    dic, states, typed, mic = make([block(0.001)] * 3 + [block(0.2)] * 5 + [block(0.001)] * 10)
    assert dic.toggle() == "listening"
    finish(dic)
    assert typed == ["hello world "]
    assert [s for s, _ in states] == ["listening", "transcribing", "idle"]
    assert states[-1][1] == "typed ✓" and mic.closed and dic.state == "idle"


def test_sin_voz_no_escribe():
    dic, states, typed, _ = make([block(0.001)] * 30)
    dic.toggle()
    finish(dic)
    assert typed == [] and states[-1] == ("idle", "heard nothing")


def test_mic_roto_avisa():
    def broken(_cb):
        raise OSError("no mic")
    dic = d.Dictation(on_state=lambda s, n=None: notes.append(n), transcriber=lambda a: "x", open_mic=broken)
    notes = []
    dic.toggle()
    finish(dic)
    assert notes[-1] == "mic error" and dic.state == "idle"


def test_toggle_mientras_escucha_termina_ya():
    class SlowMic(FakeMic):
        def __call__(self, callback):
            callback(block(0.2))
            return self
    states, typed = [], []
    dic = d.Dictation(on_state=lambda s, n=None: states.append(s), transcriber=lambda a: "stop early",
                      open_mic=SlowMic([]), type_text=typed.append)
    dic.toggle()
    dic.toggle()            # se pidió parar: transcribe lo que había
    finish(dic)
    assert typed == ["stop early "]


# --- modo automático ---

def test_compuerta_de_voz_aprende_el_ruido_y_pide_voz_sostenida():
    g = d.VoiceGate(min_rms=0.01)
    assert not any(g.feed(0.003, DT) for _ in range(20))   # cuarto callado
    assert not g.feed(0.05, DT) and not g.feed(0.05, DT)    # 0.2 s: todavía no (un golpe no basta)
    assert g.feed(0.05, DT)                                 # 0.3 s de voz: arranca
    assert g.noise < 0.01


def test_compuerta_ignora_voces_lejanas():
    g = d.VoiceGate(min_rms=0.012)
    levels = [0.003] * 20 + [0.008] * 30                    # alguien hablando a unos metros
    assert not any(g.feed(x, DT) for x in levels)


class El:
    def __init__(self, ctype=50004, pid=1, read_only=False):
        self.CurrentControlType, self.CurrentProcessId, self.ro = ctype, pid, read_only

    def GetCurrentPropertyValue(self, prop):
        assert prop == d.VALUE_IS_READ_ONLY
        return self.ro


def test_que_cuenta_como_cuadro_de_texto():
    assert d.focused_is_text(El(50004), own_pid=99)                 # Edit
    assert d.focused_is_text(El(50030), own_pid=99)                 # Document (Word, Notepad)
    assert not d.focused_is_text(El(50000), own_pid=99)             # botón
    assert not d.focused_is_text(El(50030, read_only=True), 99)     # página web que solo se lee
    assert not d.focused_is_text(El(50004, pid=99), own_pid=99)     # ventanas de EyeClick
    assert not d.focused_is_text(None, own_pid=99)


class Focus:
    editable = True

    def stop(self):
        pass


def auto(blocks, text="hello there", preview_s=10, editable=True):
    states, typed = [], []
    focus = Focus()
    focus.editable = editable
    dic = d.Dictation(on_state=lambda s, n=None: states.append((s, n)), transcriber=lambda a: text,
                      open_mic=FakeMic(blocks), type_text=typed.append, preview_s=preview_s,
                      end=lambda noise=None: d.SpeechEnd(silence_s=0.5, wait_s=2, max_s=10, noise=noise))
    dic.start_auto(focus)
    return dic, states, typed


def wait_for(cond, timeout=5):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


SPEECH = [block(0.002)] * 10 + [block(0.1)] * 8 + [block(0.002)] * 10


def test_habla_en_cuadro_de_texto_queda_en_preview_y_se_confirma():
    dic, states, typed = auto(SPEECH)
    assert wait_for(lambda: dic.state == "preview")
    assert dic.auto and dic.pending == "hello there" and typed == []
    assert ("preview", "hello there") in states
    dic.confirm()
    assert wait_for(lambda: dic.state == "idle")
    assert typed == ["hello there "] and states[-1] == ("idle", "typed ✓")
    dic.close()


def test_preview_se_descarta_o_caduca():
    dic, states, typed = auto(SPEECH)
    assert wait_for(lambda: dic.state == "preview")
    dic.discard()
    assert dic.state == "idle" and typed == [] and states[-1] == ("idle", "discarded")
    dic.close()

    dic, states, typed = auto(SPEECH, preview_s=0.1)
    assert wait_for(lambda: states and states[-1] == ("idle", "preview expired"))
    assert typed == []
    dic.close()


def test_sin_cuadro_de_texto_o_en_pausa_no_arranca():
    dic, states, _ = auto(SPEECH, editable=False)
    assert not wait_for(lambda: states, timeout=0.5)
    dic.close()
    states = []
    dic = d.Dictation(on_state=lambda s, n=None: states.append(s), transcriber=lambda a: "x",
                      open_mic=FakeMic(SPEECH), type_text=lambda t: None)
    dic.suspended = True                    # en pausa desde antes de que llegue el audio
    dic.start_auto(Focus())
    assert not wait_for(lambda: states, timeout=0.5)
    dic.close()


def test_el_preroll_no_corta_la_primera_palabra():
    heard = []
    dic = d.Dictation(transcriber=lambda a: heard.append(len(a)) or "x", open_mic=FakeMic(SPEECH),
                      type_text=lambda t: None,
                      end=lambda noise=None: d.SpeechEnd(silence_s=0.5, wait_s=2, max_s=10, noise=noise))
    dic.start_auto(Focus())
    assert wait_for(lambda: heard)
    voice_and_after = 8 * d.BLOCK
    assert heard[0] > voice_and_after       # incluye los bloques de voz de antes de arrancar
    dic.close()



# --- comandos de voz ---

def test_que_cuenta_como_comando():
    assert d.command_for("Enter.") == d.COMMANDS["enter"]
    assert d.command_for(" delete! ") == d.COMMANDS["delete"]
    assert d.command_for("DELETE") == d.COMMANDS["delete"]
    assert d.command_for("enter the room") is None              # frase normal: se escribe
    assert d.command_for("delete that") is None
    assert d.command_for("") is None


def test_comando_aprieta_la_tecla_y_no_escribe():
    keys, typed, states = [], [], []
    blocks = [block(0.001)] * 3 + [block(0.2)] * 5 + [block(0.001)] * 10
    dic = d.Dictation(on_state=lambda s, n=None: states.append((s, n)), transcriber=lambda a: "Delete.",
                      open_mic=FakeMic(blocks), type_text=typed.append, press_key=keys.append,
                      end=lambda: d.SpeechEnd(silence_s=0.5, wait_s=2, max_s=10))
    dic.toggle()
    finish(dic)
    assert keys == ["delete_word"] and typed == [] and states[-1] == ("idle", "⌫ delete")


def test_comando_en_automatico_no_pasa_por_preview():
    keys, typed = [], []
    dic = d.Dictation(transcriber=lambda a: "Enter", open_mic=FakeMic(SPEECH), type_text=typed.append,
                      press_key=keys.append,
                      end=lambda noise=None: d.SpeechEnd(silence_s=0.5, wait_s=2, max_s=10, noise=noise))
    dic.start_auto(Focus())
    assert wait_for(lambda: keys == ["enter"])
    assert dic.state == "idle" and dic.pending is None and typed == []
    dic.close()
