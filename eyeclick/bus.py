"""Bus de eventos: cola + suscriptores. ÚNICA frontera entre SWE 1 y SWE 2.  (SWE 2)

    publish(evento)              -> se puede llamar desde CUALQUIER hilo (pipeline, mock)
    subscribe(suscriptor, tipos) -> registra a quién le interesa qué (None = todos)
    dispatch()                   -> SOLO en el hilo principal (tkinter, cada DISPATCH_MS);
                                    saca todo lo pendiente y llama suscriptor.handle(evento)

Si un suscriptor falla, se registra el error y los demás siguen recibiendo.

TODO (SWE 2):
- [ ] publish(): queue.Queue.put_nowait.
- [ ] subscribe(): guardar (suscriptor, set de EventType o None).
- [ ] dispatch(): vaciar la cola con get_nowait hasta queue.Empty; try/except por suscriptor
      con logging.exception.
- [ ] Quitar el skip de tests/test_bus.py cuando esté listo.
"""
import logging
import queue

log = logging.getLogger(__name__)


class Bus:
    def __init__(self):
        self._q = queue.Queue()
        self._subs = []     # lista de (suscriptor, set[EventType] | None)

    def publish(self, event):
        # TODO (SWE 2)
        raise NotImplementedError

    def subscribe(self, subscriber, types=None):
        # TODO (SWE 2)
        raise NotImplementedError

    def dispatch(self):
        # TODO (SWE 2)
        raise NotImplementedError
