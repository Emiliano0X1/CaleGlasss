"""Bus de eventos: cola + suscriptores. ÚNICA frontera entre SWE 1 y SWE 2.  (SWE 2)

    publish(evento)              -> se puede llamar desde CUALQUIER hilo (pipeline, mock)
    subscribe(suscriptor, tipos) -> registra a quién le interesa qué (None = todos)
    dispatch()                   -> SOLO en el hilo principal (tkinter, cada DISPATCH_MS);
                                    saca todo lo pendiente y llama suscriptor.handle(evento)

Si un suscriptor falla, se registra el error y los demás siguen recibiendo.
Los suscriptores reciben los eventos en el orden en que se publicaron, y en el
orden en que se registraron. Los eventos que un suscriptor publique dentro de
handle() se reparten en el siguiente dispatch(), así un ciclo no congela la UI.
"""
import logging
import queue

log = logging.getLogger(__name__)


class Bus:
    def __init__(self):
        self._q = queue.SimpleQueue()   # segura entre hilos, sin bloquear
        self._subs = []                 # lista de (suscriptor, frozenset[EventType] | None)

    def publish(self, event):
        self._q.put_nowait(event)

    def subscribe(self, subscriber, types=None):
        if not callable(getattr(subscriber, "handle", None)):
            raise TypeError(f"{subscriber!r} no tiene handle(evento)")
        self._subs.append((subscriber, None if types is None else frozenset(types)))

    def dispatch(self):
        """Reparte lo pendiente. Devuelve cuántos eventos repartió."""
        n = 0
        for _ in range(self._q.qsize()):
            try:
                ev = self._q.get_nowait()
            except queue.Empty:
                break
            n += 1
            for sub, types in self._subs:
                if types is not None and ev.type not in types:
                    continue
                try:
                    sub.handle(ev)
                except Exception:
                    log.exception("Falló %s con %s", type(sub).__name__, ev.type.value)
        return n
