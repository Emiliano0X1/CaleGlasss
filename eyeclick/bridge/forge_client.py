"""Client for forge-app's `glasses` web trigger.  (bridge)

Sends what the wearer said to forge-app/src/triggers/glasses.ts:
    send_request(text)               -> a new request ("create a ticket for...")
    send_approval(plan_id, yes/no)   -> approve or reject a pending plan

The web trigger URL comes from `forge webtrigger create` after `forge install`;
it's read from the FORGE_WEBTRIGGER_URL environment variable (not in the repo).

TODO (bridge):
- [ ] Agree on the JSON with forge-app (same format triggers/glasses.ts expects).
- [ ] POST with a timeout and a short retry; never block the main thread.
- [ ] Return the request id so live_state.py can follow it.
- [ ] Clear error if FORGE_WEBTRIGGER_URL is missing.
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
        """Voice request. Returns the request id."""
        # TODO (bridge)
        raise NotImplementedError

    def send_approval(self, plan_id, approved=True):
        """Approval (or rejection) of a plan from the glasses."""
        # TODO (bridge)
        raise NotImplementedError
