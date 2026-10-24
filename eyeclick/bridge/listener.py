"""Microphone and blink activation.  (bridge, bus subscriber)

It's one more subscriber: app.py registers it with bus.subscribe(listener, TYPES).
handle() runs on the main thread, so it only starts or stops recording;
recording, transcribing (stt.py) and sending (forge_client.py) happen on a separate thread.

Flow:
    activation gesture -> start recording (sounddevice.InputStream)
    gesture again (or silence / max time) -> stop
    thread: audio -> stt.transcribe() -> forge_client.send_request() or send_approval()
    on_status(text) -> the overlay shows "listening...", "sending...", etc.

TODO (bridge):
- [ ] Decide the activation gesture. It must NOT collide with clicks (0.5-3.0 s) or
      with rest (> 3 s). If it needs a new event, events.py has to change:
      tell SWE 1 and SWE 2 first.
- [ ] Fill TYPES with the events the gesture uses.
- [ ] Recording with sounddevice.InputStream at SAMPLE_RATE, mono, with MAX_SECONDS.
- [ ] Worker thread: transcribe and send; report progress with on_status().
- [ ] Tell a "request" from an "approval" (e.g. if the text starts with "approve").
- [ ] Register it in app.py behind a run.py option, so --mock keeps working
      without a microphone or network.
"""
import logging
import threading

log = logging.getLogger(__name__)

TYPES = set()           # TODO: events of the activation gesture
SAMPLE_RATE = 16000     # what faster-whisper expects
MAX_SECONDS = 15.0      # stops recording if the user doesn't repeat the gesture


class VoiceListener:
    def __init__(self, transcribe, client, on_status=lambda text: None):
        """transcribe: stt.Transcriber.transcribe. client: forge_client.ForgeClient.
        on_status: called from ANOTHER thread; whoever passes it must hand it to the main thread."""
        self.transcribe = transcribe
        self.client = client
        self.on_status = on_status
        self.recording = False
        self._stream = None
        self._chunks = []
        self._worker = None
        self._lock = threading.Lock()

    def handle(self, ev):
        # TODO (bridge): detect the gesture and call start_recording() / stop_recording()
        raise NotImplementedError

    def start_recording(self):
        # TODO (bridge): open sounddevice.InputStream and accumulate into self._chunks
        raise NotImplementedError

    def stop_recording(self):
        # TODO (bridge): close the stream and launch self._process on a thread
        raise NotImplementedError

    def _process(self, audio):
        # TODO (bridge): text = self.transcribe(audio); send it with self.client
        raise NotImplementedError

    def close(self):
        # TODO (bridge): close the stream if recording (app.py calls this on exit)
        pass
