"""Micrófono y activación por parpadeo.  (bridge, suscriptor del bus)

Es un suscriptor más: app.py lo registra con bus.subscribe(listener, TYPES).
handle() corre en el hilo principal, así que solo prende o apaga la grabación;
grabar, transcribir (stt.py) y enviar (forge_client.py) pasan en un hilo aparte.

Flujo:
    gesto de activación -> empezar a grabar (sounddevice.InputStream)
    gesto otra vez (o silencio / tiempo máximo) -> parar
    hilo: audio -> stt.transcribe() -> forge_client.send_request() o send_approval()
    on_status(texto) -> el overlay muestra "escuchando...", "enviando...", etc.

TODO (bridge):
- [ ] Decidir el gesto de activación. NO puede chocar con los clics (0.5-3.0 s) ni
      con el descanso (> 3 s). Si necesita un evento nuevo hay que cambiar events.py:
      avisar a SWE 1 y SWE 2 antes.
- [ ] Llenar TYPES con los eventos que usa el gesto.
- [ ] Grabación con sounddevice.InputStream a SAMPLE_RATE, mono, con MAX_SECONDS.
- [ ] Hilo de trabajo: transcribir y enviar; avisar el progreso con on_status().
- [ ] Distinguir "pedido" de "aprobar" (p. ej. si el texto empieza con "aprobar").
- [ ] Registrar en app.py detrás de una opción de run.py, para que --mock siga
      funcionando sin micrófono ni red.
"""
import logging
import threading

log = logging.getLogger(__name__)

TYPES = set()           # TODO: eventos del gesto de activación
SAMPLE_RATE = 16000     # lo que espera faster-whisper
MAX_SECONDS = 15.0      # corta la grabación si el usuario no vuelve a hacer el gesto


class VoiceListener:
    def __init__(self, transcribe, client, on_status=lambda text: None):
        """transcribe: stt.Transcriber.transcribe. client: forge_client.ForgeClient.
        on_status: se llama desde OTRO hilo; quien lo pase debe llevarlo al hilo principal."""
        self.transcribe = transcribe
        self.client = client
        self.on_status = on_status
        self.recording = False
        self._stream = None
        self._chunks = []
        self._worker = None
        self._lock = threading.Lock()

    def handle(self, ev):
        # TODO (bridge): detectar el gesto y llamar start_recording() / stop_recording()
        raise NotImplementedError

    def start_recording(self):
        # TODO (bridge): abrir sounddevice.InputStream y acumular en self._chunks
        raise NotImplementedError

    def stop_recording(self):
        # TODO (bridge): cerrar el stream y lanzar self._process en un hilo
        raise NotImplementedError

    def _process(self, audio):
        # TODO (bridge): texto = self.transcribe(audio); enviar con self.client
        raise NotImplementedError

    def close(self):
        # TODO (bridge): cerrar el stream si está grabando (lo llama app.py al salir)
        pass
