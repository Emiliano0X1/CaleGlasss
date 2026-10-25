"""Dictado por voz con el micrófono lavalier: habla y el texto se escribe donde está el cursor.

Pensado para alguien sin movilidad en las manos, así que se arranca igual que un clic:
mirar el botón "mic" del indicador flotante y parpadear (el indicador no roba el foco,
así que el texto cae en la ventana donde estabas escribiendo). F11 también sirve.

    toggle()  idle -> "listening": abre el micrófono
              "listening" -> deja de escuchar ya y transcribe lo que hay
    Escuchando, termina solo:
        - tras hablar, DICTATION_SILENCE_S de silencio
        - si nadie habla en DICTATION_WAIT_S, se cancela sin escribir nada
        - DICTATION_MAX_S como tope
    "transcribing": faster-whisper (en la laptop, sin internet) y se escribe el texto
    con el teclado de pynput, más un espacio para que la siguiente frase se pegue bien.

Silencio vs. voz: el primer NOISE_S mide el ruido del cuarto (la mediana, así el bip de
inicio no cuenta) y es voz lo que pase de max(MIN_RMS, NOISE_X * ruido).

Modo automático (DICTATION_AUTO, start_auto()): sin botón. El micrófono queda abierto y
el dictado arranca solo cuando se cumplen las dos cosas:
    - TextFocus: el foco está en un cuadro de texto editable de otra app (UI Automation
      de Windows: control Edit o Document que no sea de solo lectura)
    - VoiceGate: la persona habla. El lavalier oye a quien lo lleva mucho más fuerte que
      a los demás, así que se pide AUTO_X veces el ruido del cuarto durante AUTO_SPEECH_S.
Se guardan los PREROLL_S anteriores para no cortar la primera palabra.
Como puede equivocarse (hablar con alguien con un cuadro de texto abierto), lo dictado
en automático NO se escribe directo: queda en "preview" y el indicador lo muestra.
    parpadeo izquierdo -> confirm(): se escribe     (app.py se come ese clic: el mouse no
    parpadeo derecho   -> discard(): se descarta     hace clic y el foco no se mueve)
    DICTATION_PREVIEW_S sin hacer nada -> se descarta
El botón mic / F11 sigue sirviendo igual y escribe directo (ahí la intención es clara).

Comandos de voz: si TODO lo dicho es un comando (sin importar mayúsculas ni puntos),
se aprieta la tecla en vez de escribir la palabra, también en modo automático (sin
preview: una tecla suelta cuesta poco deshacer):
    "enter"  -> Enter
    "delete" -> Ctrl+Backspace (borra la palabra anterior)

Todo corre en un hilo propio: on_state(estado, nota) se llama desde ese hilo, así que
app.py lo pasa por una cola al hilo principal antes de tocar tkinter.
El modelo se carga en segundo plano al arrancar (preload) para que el primer dictado
no espere la descarga/carga.
"""
import collections
import logging
import os
import queue
import threading
import time

import numpy as np

from eyeclick.config import (DICTATION_AUTO_RMS, DICTATION_DEVICE, DICTATION_LANGUAGE, DICTATION_MAX_S,
                             DICTATION_MODEL, DICTATION_PREVIEW_S, DICTATION_SILENCE_S, DICTATION_WAIT_S)

log = logging.getLogger(__name__)

SR = 16000              # lo que espera Whisper
BLOCK = 1600            # 0.1 s por bloque
NOISE_S = 0.3
NOISE_X = 3.0
MIN_RMS = 0.004         # un lavalier con poca ganancia habla en ~0.005-0.05
EPS = 1e-6              # 3 x 0.1 s da 0.30000000000000004: comparar con margen
AUTO_X = 4.0            # modo automático: voz = AUTO_X veces el ruido (y más que DICTATION_AUTO_RMS)
AUTO_SPEECH_S = 0.3     # ...durante tanto tiempo, dentro de una ventana de AUTO_WINDOW_S
AUTO_WINDOW_S = 0.5
PREROLL_S = 0.5
FOCUS_POLL_S = 0.3
TEXT_TYPES = {50004, 50030}     # UIA_EditControlTypeId, UIA_DocumentControlTypeId
VALUE_IS_READ_ONLY = 30046      # UIA_ValueIsReadOnlyPropertyId


class SpeechEnd:
    """Decide cuándo terminó de hablar, bloque por bloque (sin audio real: se prueba solo)."""

    def __init__(self, silence_s=DICTATION_SILENCE_S, wait_s=DICTATION_WAIT_S, max_s=DICTATION_MAX_S,
                 noise=None):
        """noise: ruido ya medido. El modo automático arranca con la persona hablando, así que
        no se puede medir al principio y ya se sabe que hubo voz."""
        self.silence_s, self.wait_s, self.max_s = silence_s, wait_s, max_s
        self.t = 0.0
        self.noise = [] if noise is None else [noise]
        self.measuring = noise is None
        self.heard = noise is not None
        self.quiet = 0.0

    def feed(self, rms, dt):
        """None mientras sigue; "done" (hubo voz) o "nothing" (nadie habló) al terminar."""
        self.t += dt
        if self.measuring and self.t <= NOISE_S + EPS:
            self.noise.append(rms)
            return None
        thr = max(MIN_RMS, NOISE_X * float(np.median(self.noise)) if self.noise else MIN_RMS)
        if rms > thr:
            self.heard, self.quiet = True, 0.0
        else:
            self.quiet += dt
        if self.t >= self.max_s - EPS:
            return "done" if self.heard else "nothing"
        if self.heard and self.quiet >= self.silence_s - EPS:
            return "done"
        if not self.heard and self.t >= self.wait_s - EPS:
            return "nothing"
        return None


class WhisperTranscriber:
    def __init__(self, model=DICTATION_MODEL, language=DICTATION_LANGUAGE):
        self.name, self.language = model, language
        self._model = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self._model is None:
                # La descarga "Xet" de Hugging Face se queda en 0 bytes en algunas redes
                # (pasó en la de Cal Hacks); la descarga HTTP normal sí funciona.
                os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
                from faster_whisper import WhisperModel     # aquí: las pruebas no lo necesitan
                t0 = time.monotonic()
                self._model = WhisperModel(self.name, device="cpu", compute_type="int8")
                log.info("Modelo de dictado '%s' listo en %.1f s", self.name, time.monotonic() - t0)
        return self._model

    def __call__(self, audio):
        segments, _ = self.load().transcribe(audio, language=self.language, beam_size=1,
                                             vad_filter=True, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()


def _find_device(sd, name):
    """Windows lista cada micrófono una vez por driver (MME, DirectSound, WASAPI...): con un
    nombre, usar la primera entrada de entrada que lo contenga (MME, que acepta 16 kHz)."""
    if not isinstance(name, str):
        return name
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name.lower() in dev["name"].lower():
            return i
    raise ValueError(f"No hay micrófono que se llame como {name!r}")


def _open_mic(callback):
    import sounddevice as sd
    stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=BLOCK,
                            device=_find_device(sd, DICTATION_DEVICE), callback=lambda data, *_: callback(data[:, 0].copy()))
    stream.start()
    return stream


def _type_text(text):
    from pynput.keyboard import Controller
    Controller().type(text)


COMMANDS = {"enter": ("enter", "⏎ enter"), "delete": ("delete_word", "⌫ delete")}


def command_for(text):
    """"Enter." / " delete!" -> ("enter", nota); cualquier otra cosa -> None."""
    word = "".join(ch for ch in text.lower() if ch.isalnum() or ch == " ").strip()
    return COMMANDS.get(word)


def _press_key(key):
    from pynput.keyboard import Controller, Key
    kb = Controller()
    if key == "enter":
        kb.tap(Key.enter)
    elif key == "delete_word":
        with kb.pressed(Key.ctrl):
            kb.tap(Key.backspace)


class VoiceGate:
    """Modo automático: ¿empezó a hablar quien lleva el lavalier? Bloque por bloque."""

    def __init__(self, min_rms=DICTATION_AUTO_RMS):
        self.min_rms = min_rms
        self.noise = None
        self.recent = collections.deque()      # (dt, era voz) de la última AUTO_WINDOW_S

    def threshold(self):
        return max(self.min_rms, AUTO_X * (self.noise or 0.0))

    def feed(self, rms, dt):
        voiced = self.noise is not None and rms > self.threshold()
        if not voiced:                          # el ruido se aprende solo de lo que no es voz
            self.noise = rms if self.noise is None else self.noise + (rms - self.noise) * min(1.0, dt / 2.0)
        self.recent.append((dt, voiced))
        while sum(d for d, _ in self.recent) > AUTO_WINDOW_S + EPS:
            self.recent.popleft()
        return sum(d for d, v in self.recent if v) >= AUTO_SPEECH_S - EPS

    def reset(self):
        self.recent.clear()


def focused_is_text(element, own_pid):
    """¿El elemento con foco (UI Automation) es un cuadro de texto editable de otra app?"""
    if element is None or element.CurrentProcessId == own_pid:
        return False                            # el monitor o el indicador de EyeClick
    if element.CurrentControlType not in TEXT_TYPES:
        return False
    try:
        return not bool(element.GetCurrentPropertyValue(VALUE_IS_READ_ONLY))
    except Exception:
        return True


class TextFocus:
    """Revisa cada FOCUS_POLL_S si el foco está en un cuadro de texto (hilo propio: COM)."""

    def __init__(self, probe=None):
        self.editable = False
        self._probe = probe
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()

    def _run(self):
        probe = self._probe
        if probe is None:
            try:
                probe = _uia_probe()
            except Exception:
                log.warning("UI Automation no disponible: el dictado automático queda apagado", exc_info=True)
                return
        while not self._stop.is_set():
            try:
                self.editable = probe()
            except Exception:
                self.editable = False           # ventanas que se cierran a media consulta, etc.
            self._stop.wait(FOCUS_POLL_S)


def _uia_probe():
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()                     # en ESTE hilo
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
    uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
    own = os.getpid()
    return lambda: focused_is_text(uia.GetFocusedElement(), own)


class Dictation:
    def __init__(self, on_state=None, transcriber=None, open_mic=_open_mic, type_text=_type_text,
                 end=SpeechEnd, gate=VoiceGate, preview_s=DICTATION_PREVIEW_S, press_key=_press_key):
        self.on_state = on_state or (lambda state, note=None: None)
        self.press_key = press_key
        self.transcriber = transcriber or WhisperTranscriber()
        self.open_mic, self.type_text, self.end, self.gate = open_mic, type_text, end, gate
        self.preview_s = preview_s
        self.state = "idle"             # idle / listening / transcribing / preview / typing
        self.auto = False               # la frase actual arrancó sola (sin bip, va a preview)
        self.pending = None             # texto en preview
        self.suspended = False          # en pausa no arranca solo
        self.focus = None
        self._preview_until = 0.0
        self._stop = threading.Event()
        self._closed = threading.Event()
        self._manual = threading.Event()
        self._thread = None
        self._auto_thread = None

    def preload(self):
        """Carga el modelo en segundo plano. Si falla, se reintenta al dictar."""
        load = getattr(self.transcriber, "load", None)
        if load is not None:
            threading.Thread(target=self._safe_load, args=(load,), daemon=True).start()

    @staticmethod
    def _safe_load(load):
        try:
            load()
        except Exception:
            log.warning("No se pudo cargar el modelo de dictado", exc_info=True)

    def start_auto(self, focus=None):
        """Micrófono siempre abierto + arranque solo en cuadros de texto (ver arriba)."""
        self.focus = focus or TextFocus().start()
        self._auto_thread = threading.Thread(target=self._auto_run, daemon=True)
        self._auto_thread.start()

    def toggle(self):
        if self.state == "idle":
            self._stop.clear()
            if self._auto_thread is not None:
                self._manual.set()      # el hilo automático ya tiene el micrófono abierto
            else:
                self.auto = False
                self._set("listening")
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        elif self.state == "listening":
            self._stop.set()            # termina ya y transcribe lo que hay
        elif self.state == "preview":
            self.discard()
        return self.state

    def confirm(self):
        """Preview -> escribir (en otro hilo: pynput tarda con textos largos)."""
        text, self.pending = self.pending, None
        if self.state != "preview" or not text:
            return
        self.state = "typing"
        threading.Thread(target=self._type, args=(text,), daemon=True).start()

    def discard(self, note="discarded"):
        if self.state == "preview":
            self.pending = None
            self._set("idle", note)

    def close(self):
        self._stop.set()
        self._closed.set()
        if self.focus is not None:
            self.focus.stop()

    def _set(self, state, note=None):
        self.state = state
        self.on_state(state, note)

    # --- botón / F11 sin modo automático: el micrófono se abre solo para esta frase ---
    def _run(self):
        blocks = queue.SimpleQueue()
        try:
            stream = self.open_mic(blocks.put)
        except Exception:
            log.warning("No se pudo abrir el micrófono", exc_info=True)
            self._set("idle", "mic error")
            return
        try:
            audio, result = self._listen(blocks, [], self.end())
        finally:
            stream.stop()
            stream.close()
        self._finish(audio, result)

    # --- modo automático: un solo hilo con el micrófono abierto todo el tiempo ---
    def _auto_run(self):
        blocks = queue.SimpleQueue()
        try:
            stream = self.open_mic(blocks.put)
        except Exception:
            log.warning("No se pudo abrir el micrófono: dictado automático apagado", exc_info=True)
            self._auto_thread = None
            self._set("idle", "mic error")
            return
        gate = self.gate()
        preroll = collections.deque(maxlen=max(1, round(PREROLL_S * SR / BLOCK)))
        try:
            while not self._closed.is_set():
                if self.state == "preview" and time.monotonic() > self._preview_until:
                    self.discard("preview expired")
                try:
                    block = blocks.get(timeout=0.5)
                except queue.Empty:
                    continue
                if self._manual.is_set():
                    self._manual.clear()
                    self.auto = False
                    self._set("listening")
                    self._finish(*self._listen(blocks, [], self.end()))
                    gate.reset()
                    preroll.clear()
                    continue
                if self.state != "idle":
                    continue
                preroll.append(block)
                started = gate.feed(_rms(block), len(block) / SR)
                if started and not self.suspended and self.focus.editable:
                    self.auto = True
                    self._stop.clear()
                    self._set("listening")
                    self._finish(*self._listen(blocks, list(preroll), self.end(noise=gate.noise)))
                    gate.reset()
                    preroll.clear()
        finally:
            stream.stop()
            stream.close()

    def _listen(self, blocks, audio, end):
        result = None
        while result is None and not self._closed.is_set():
            if self._stop.is_set():         # pidieron parar: lo que ya llegó sí cuenta
                while True:
                    try:
                        audio.append(blocks.get_nowait())
                    except queue.Empty:
                        break
                break
            try:
                block = blocks.get(timeout=0.5)
            except queue.Empty:
                continue
            audio.append(block)
            result = end.feed(_rms(block), len(block) / SR)
        return audio, result

    def _finish(self, audio, result):
        quiet_note = None if self.auto else "heard nothing"    # en automático, callado
        if result == "nothing" or not audio:
            self._set("idle", quiet_note)
            return
        self._set("transcribing")
        try:
            text = self.transcriber(np.concatenate(audio))
        except Exception:
            log.warning("Falló el dictado", exc_info=True)
            self._set("idle", "dictation error")
            return
        if not text:
            self._set("idle", quiet_note)
            return
        command = command_for(text)
        if command is not None:
            key, note = command
            log.info("Comando de voz: %s", key)
            try:
                self.press_key(key)
            except Exception:
                log.warning("No se pudo apretar %s", key, exc_info=True)
                self._set("idle", "could not press key")
                return
            self._set("idle", note)
            return
        log.info("Dictado: %d caracteres", len(text))     # el texto no va al log
        if self.auto:
            self.pending = text
            self._preview_until = time.monotonic() + self.preview_s
            self._set("preview", text)
        else:
            self._type(text)

    def _type(self, text):
        try:
            self.type_text(text + " ")
        except Exception:
            log.warning("No se pudo escribir el dictado", exc_info=True)
            self._set("idle", "could not type")
            return
        self._set("idle", "typed ✓")


def _rms(block):
    return float(np.sqrt(np.mean(block ** 2)))


def _self_test():
    """python -m eyeclick.actions.dictation: habla y ve el nivel del micrófono y el texto (no escribe nada)."""
    import sounddevice as sd
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    dev = _find_device(sd, DICTATION_DEVICE)
    print("Microphone:", sd.query_devices(dev if dev is not None else sd.default.device[0])["name"])
    print("Loading model...")
    transcriber = WhisperTranscriber()
    transcriber.load()
    peaks, done = [], threading.Event()

    class Meter(SpeechEnd):
        def feed(self, rms, dt):
            peaks.append(rms)
            print(f"\r  level {rms:.4f}  {'#' * min(40, int(rms * 800))}".ljust(60), end="", flush=True)
            return super().feed(rms, dt)

    def on_state(state, note=None):
        print(f"\n[{state}] {note or ''}")
        if state == "listening":
            print(f"Speak now (stops after {DICTATION_SILENCE_S} s of silence)...")
        if state == "idle":
            done.set()

    dic = Dictation(on_state=on_state, transcriber=transcriber, end=Meter,
                    type_text=lambda text: print("TEXT:", repr(text)))
    dic.toggle()
    done.wait(DICTATION_MAX_S + 60)
    if peaks:
        print(f"Max level {max(peaks):.4f} (speech threshold {MIN_RMS}). If your voice stays "
              "below the threshold, raise the mic level in Windows sound settings.")


if __name__ == "__main__":
    _self_test()
