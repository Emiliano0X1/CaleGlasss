"""Live state from SpacetimeDB -> overlay.  (bridge)

Reads (or subscribes to) the request state that forge-app writes to stdb/
and reports each change with on_update(text). Runs on its own thread: it NEVER
touches tkinter. Whoever passes on_update (app.py) must hand the change to the main
thread, the same way it already does with F9 pause requests, and call overlay.show() there.

Examples of what the overlay would show:
    "Router: thinking..."  "Jira: creating ticket"  "Approve plan? (blink)"  "Done ✓"

TODO (bridge):
- [ ] Pick a SpacetimeDB client for Python (or read over HTTP if there's no SDK).
- [ ] Connect to the stdb/ database (host and name from environment variables).
- [ ] Follow only this pair of glasses' requests and turn each state into a short text.
- [ ] Reconnect if the network drops, without stalling the app.
- [ ] stop(): close the connection and the thread (app.py calls this on exit).
"""
import logging
import threading

log = logging.getLogger(__name__)

HOST_ENV = "STDB_HOST"
DB_ENV = "STDB_DATABASE"


class LiveState:
    def __init__(self, on_update):
        """on_update(text): called from LiveState's thread."""
        self.on_update = on_update
        self._running = False
        self._thread = None

    def start(self):
        # TODO (bridge): connect and launch self._loop on a daemon thread
        raise NotImplementedError

    def stop(self):
        # TODO (bridge): close the connection and wait for the thread
        self._running = False

    def _loop(self):
        # TODO (bridge)
        raise NotImplementedError
