"""Cliente del web trigger `glasses` de forge-app.  (bridge)

Manda lo que dijo la persona a forge-app/src/triggers/glasses.ts:
    send_request(texto)          -> un pedido nuevo ("crea un ticket para...")
    send_approval(plan_id, sí/no) -> aprobar o rechazar un plan pendiente

La URL del web trigger la da `forge webtrigger` después de `forge install`;
se lee de la variable de entorno FORGE_WEBTRIGGER_URL (no va en el repo).

TODO (bridge):
- [ ] Definir el JSON con forge-app (mismo formato que espera triggers/glasses.ts).
- [ ] POST con timeout y reintento corto; nunca bloquear el hilo principal.
- [ ] Devolver el id del pedido para que live_state.py lo siga.
- [ ] Error claro si falta FORGE_WEBTRIGGER_URL.
"""
import logging
import os

log = logging.getLogger(__name__)

URL_ENV = "FORGE_WEBTRIGGER_URL"
TIMEOUT_S = 10.0


class ForgeClient:
    def __init__(self, url=None, timeout=TIMEOUT_S):
        self.url = url or os.environ.get(URL_ENV)
        self.timeout = timeout

    def send_request(self, text) -> str:
        """Pedido por voz. Devuelve el id del pedido."""
        # TODO (bridge)
        raise NotImplementedError

    def send_approval(self, plan_id, approved=True):
        """Aprobación (o rechazo) de un plan desde los lentes."""
        # TODO (bridge)
        raise NotImplementedError
