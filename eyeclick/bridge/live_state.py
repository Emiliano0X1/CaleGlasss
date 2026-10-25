"""Live state from SpacetimeDB -> overlay.  (bridge)

Every POLL_S seconds it asks SpacetimeDB over HTTP (the same /sql endpoint forge-app and
the dashboard read) for the newest pending plan, and calls on_change(plan) when it changes:
plan = {"id": "p-...", "summary": "..."} or None. The overlay then shows
"Plan ready: say approve or blink" (bridge/__init__.py: Bridge.note()).

"Newest" = the pending proposal whose work item was created last: the same rule forge-app
uses for a voice "approve" (execute/approve.ts latestPending), so both point at one plan.

Runs on its own daemon thread and NEVER touches tkinter. A network error keeps the last
known plan and is logged once, so a flaky connection doesn't stall or spam the app.

STDB_HOST and STDB_DATABASE can be set in eyeclick/bridge/.env (defaults: maincloud, agentes).
"""
import logging
import os
import threading

import httpx

log = logging.getLogger(__name__)

POLL_S = 2.0
TIMEOUT_S = 5.0


def stdb_url():
    host = os.environ.get("STDB_HOST", "https://maincloud.spacetimedb.com").rstrip("/")
    return f"{host}/v1/database/{os.environ.get('STDB_DATABASE', 'agentes')}/sql"


def sql(query, timeout=TIMEOUT_S):
    """Rows of the first result, each a list of values."""
    res = httpx.post(stdb_url(), content=query, timeout=timeout)
    res.raise_for_status()
    results = res.json()
    return results[0]["rows"] if results else []


def fetch_pending():
    """Newest pending plan as {"id", "summary"}, or None."""
    proposals = sql("SELECT id, work_id, summary FROM proposals WHERE status = 'pending'")
    if not proposals:
        return None
    created = {row[0]: timestamp(row[1]) for row in sql("SELECT id, created_at FROM work_items WHERE status = 'proposed'")}
    pid, _, summary = max(proposals, key=lambda p: created.get(p[1], 0))
    return {"id": pid, "summary": summary}


def timestamp(value):
    """stdb's SQL over HTTP returns a timestamp as [microseconds since the epoch]."""
    if isinstance(value, list):
        value = value[0] if value else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class LiveState:
    def __init__(self, on_change=lambda plan: None, poll_s=POLL_S, fetch=fetch_pending):
        """on_change(plan): called from LiveState's thread when the newest pending plan changes."""
        self.on_change = on_change
        self.poll_s = poll_s
        self._fetch = fetch
        self._pending = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._failing = False

    @property
    def pending(self):
        """Newest pending plan as last seen ({"id", "summary"} or None). Any thread."""
        with self._lock:
            return self._pending

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="live-state", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=TIMEOUT_S + 1)

    def poll(self):
        """One check; returns the plan. Also what the thread does every poll_s."""
        try:
            plan = self._fetch()
        except Exception as e:
            if not self._failing:
                log.warning("can't read SpacetimeDB (keeping the last state): %s", e)
            self._failing = True
            return self.pending
        if self._failing:
            log.info("SpacetimeDB reachable again")
        self._failing = False
        with self._lock:
            changed = plan != self._pending
            self._pending = plan
        if changed:
            log.info("pending plan: %s", plan["id"] if plan else "none")
            self.on_change(plan)
        return plan

    def _loop(self):
        while not self._stop.is_set():
            self.poll()
            self._stop.wait(self.poll_s)
