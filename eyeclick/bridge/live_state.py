"""Estado en vivo desde SpacetimeDB -> overlay.  (bridge)

Lee (o se suscribe a) el estado de los pedidos que escribe forge-app en stdb/
y avisa cada cambio con on_update(texto). Corre en su propio hilo: NUNCA toca
tkinter. Quien pase on_update (app.py) debe llevar el cambio al hilo principal,
igual que hoy hace con las peticiones de pausa de F9, y ahí llamar overlay.show().

Ejemplos de lo que mostraría el overlay:
    "Router: pensando..."  "Jira: creando ticket"  "¿Aprobar plan? (parpadeo)"  "Listo ✓"

TODO (bridge):
- [ ] Elegir cliente de SpacetimeDB para Python (o leer por HTTP si no hay SDK).
- [ ] Conectar a la base de stdb/ (host y nombre por variables de entorno).
- [ ] Seguir solo los pedidos de estos lentes y traducir cada estado a un texto corto.
- [ ] Reconectar si se cae la red, sin trabar la app.
- [ ] stop(): cerrar la conexión y el hilo (lo llama app.py al salir).
"""
import logging
import threading

log = logging.getLogger(__name__)

HOST_ENV = "STDB_HOST"
DB_ENV = "STDB_DATABASE"


class LiveState:
    def __init__(self, on_update):
        """on_update(texto): se llama desde el hilo de LiveState."""
        self.on_update = on_update
        self._running = False
        self._thread = None

    def start(self):
        # TODO (bridge): conectar y lanzar self._loop en un hilo daemon
        raise NotImplementedError

    def stop(self):
        # TODO (bridge): cerrar la conexión y esperar al hilo
        self._running = False

    def _loop(self):
        # TODO (bridge)
        raise NotImplementedError
