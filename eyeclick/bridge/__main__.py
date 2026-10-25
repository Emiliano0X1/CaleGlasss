"""Voice test without EyeClick: Enter (or the wake phrase) is the trigger instead of the blink.

    python -m eyeclick.bridge --wake           # always listening: "Hey glasses, move the open bugs..."
    python -m eyeclick.bridge --wake --no-send # same, but only prints what it would send
    python -m eyeclick.bridge --list-devices   # find the glasses' microphone, put it in MIC_DEVICE
    python -m eyeclick.bridge                  # Enter -> record -> transcribe -> send to Forge
    python -m eyeclick.bridge --level          # live volume bar of MIC_DEVICE: is it the right mic?
    python -m eyeclick.bridge --no-send        # only transcribe (no Jira, no Telegram)
    python -m eyeclick.bridge --model base.en  # faster model if "small.en" takes more than 3 s

Each round prints the text, how long the transcription took, and how forge-app understood
it: a request (with the cleaned-up instruction), approve / reject of the newest plan, or
"didn't get that". Saying "approve" with a pending plan approves that plan. Ctrl+C to quit.
"""
import argparse
import logging
import os
import sys
import time

import threading

from . import stt, wake  # importing the package also quiets httpx and faster_whisper
from .forge_client import ForgeClient, ForgeError
from .listener import VoiceListener, describe, handle_text
from .live_state import LiveState, fetch_pending


def main():
    parser = argparse.ArgumentParser(description="Voice request with Enter as the trigger")
    parser.add_argument("--list-devices", action="store_true", help="list the microphones and exit")
    parser.add_argument("--level", action="store_true", help="show the microphone's volume live (Ctrl+C to stop)")
    parser.add_argument("--wake", action="store_true", help=f'always listen for "{wake.PHRASE}, ..." instead of Enter')
    parser.add_argument("--no-send", action="store_true", help="transcribe only, don't call Forge")
    parser.add_argument("--model", default=stt.MODEL_SIZE, help="Whisper model: tiny.en, base.en, small.en...")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")   # a console without ✓ or … still prints
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.list_devices:
        for index, name, api, rate in stt.input_devices():
            print(f"{index:3}  {name}  [{api}, {rate} Hz]")
        return
    if args.level:
        show_level(stt.find_device(os.environ.get("MIC_DEVICE")))
        return

    client = None if args.no_send else ForgeClient()   # fails now if the .env is missing, not after talking
    device = stt.find_device(os.environ.get("MIC_DEVICE"))
    transcriber = stt.Transcriber(model_size=args.model)
    transcriber.load()
    mic = stt.Microphone(device)
    if args.wake:
        return wake_loop(client, transcriber, mic)
    print(f"Microphone: {mic.name}. Press Enter and talk in English (Ctrl+C to quit).")

    try:
        while True:
            input("\n[Enter] ")
            print("Listening...")
            audio = mic.record()
            started = time.monotonic()
            text = transcriber.transcribe(audio)
            elapsed = time.monotonic() - started
            print(f'Heard ({elapsed:.1f} s): "{text}"')
            if not text:
                print("Nothing understood, try again closer to the microphone.")
                continue
            if client:
                try:
                    print(describe(handle_text(client, text, fetch_pending())))
                except ForgeError as e:
                    print(f"Couldn't send: {e}")
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        mic.close()


class PrintClient:
    """--no-send: shows what would go to Forge."""

    def send_request(self, text):
        print(f'  would send request: "{text}"')
        return {"intent": "request", "instruction": text}

    def send_approval(self, proposal_id):
        print(f"  would approve {proposal_id}")
        return {"intent": "approve", "result": "approved"}


def wake_loop(client, transcriber, mic):
    """The same wake loop EyeClick runs with --voice, printing each status."""
    fast = stt.Transcriber(wake.WAKE_MODEL, prompt=None)
    fast.load()
    state = LiveState()
    state.start()
    voice = VoiceListener(client or PrintClient(), state, transcriber, mic, on_status=lambda t: print(f"  {t}"))
    stop = threading.Event()
    print(f'Microphone: {mic.name}.')
    print(f'Say "{wake.PHRASE}, <your Jira request>" or "{wake.PHRASE}, approve" (Ctrl+C to quit).')
    print("Everything it hears is printed; only what starts with the phrase is sent.\n")
    try:
        voice.run_wake_loop(
            stop, fast,
            on_wake=lambda: print(f"\a>> {wake.PHRASE} ✓", flush=True),
            on_heard=lambda text: print(f'   heard (no "{wake.PHRASE}", ignored): "{text}"', flush=True),
        )
    except KeyboardInterrupt:
        print()
    finally:
        stop.set()
        state.stop()
        mic.close()


def show_level(device):
    """Volume bar; the | mark is SILENCE_RMS: talking should go past it, quiet should stay under."""
    import numpy as np
    import sounddevice as sd

    rate = int(sd.query_devices(device, "input")["default_samplerate"])
    mark = int(stt.SILENCE_RMS * 400)
    print(f"Microphone: {sd.query_devices(device, 'input')['name']}. Talk; Ctrl+C to stop.")
    try:
        with sd.InputStream(device=device, channels=1, samplerate=rate, dtype="float32") as stream:
            while True:
                data, _ = stream.read(rate // 10)
                rms = float(np.sqrt(np.mean(data**2)))
                bar = "#" * min(int(rms * 400), 50)
                print(f"\r{rms:.4f} {bar[:mark].ljust(mark)}|{bar[mark:].ljust(50 - mark)}", end="", flush=True)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
