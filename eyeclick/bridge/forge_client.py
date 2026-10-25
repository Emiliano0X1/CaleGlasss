"""Client for forge-app's `glasses` web trigger.  (bridge)

Sends what the wearer said to forge-app/src/triggers/glasses.ts:
    send_request(text)               -> a new request ("move what's left to sprint 13")
    send_approval(proposal_id)       -> approve a pending plan (long blink, or the word "approve")

    POST <GLASSES_WEBTRIGGER_URL>
    x-secret: <APPROVAL_SECRET>
    { "type": "request", "text": "...", "person": "<PERSON_ID>", "request_id": "<uuid4>" }
    { "type": "approve", "proposal_id": "p-...", "person": "<PERSON_ID>", "request_id": "<uuid4>" }

The settings come from eyeclick/bridge/.env (gitignored, see .env.example):
GLASSES_WEBTRIGGER_URL (from `forge webtrigger create -f glasses-webtrigger ...`),
APPROVAL_SECRET (the same as the encrypted Forge variable) and PERSON_ID (the id in the
stdb `people` table, so the receipt and the plan reach that person's Telegram).

A failed send is retried once with the same request_id: glasses.ts ignores a request_id it
already has, so a retry never creates two requests or approves twice.
"""
import logging
import os
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv(Path(__file__).with_name(".env"))

TIMEOUT_S = 10.0
ATTEMPTS = 2


class ForgeError(Exception):
    pass


class ForgeClient:
    def __init__(self, url=None, secret=None, person=None, timeout=TIMEOUT_S):
        self.url = url or os.environ.get("GLASSES_WEBTRIGGER_URL")
        self.secret = secret or os.environ.get("APPROVAL_SECRET")
        self.person = person or os.environ.get("PERSON_ID", "unknown")
        self.timeout = timeout
        if not self.url or not self.secret:
            raise ForgeError("GLASSES_WEBTRIGGER_URL and APPROVAL_SECRET must be set in eyeclick/bridge/.env")

    def send_request(self, text) -> dict:
        """Voice request. Returns glasses.ts's answer (work_id, request_id, receipt, agent)."""
        body = {"type": "request", "text": text, "person": self.person, "request_id": str(uuid.uuid4())}
        return self._post(body)

    def send_approval(self, proposal_id) -> dict:
        """Approves a pending plan. Returns glasses.ts's answer (result: approved | already | ...)."""
        body = {"type": "approve", "proposal_id": proposal_id, "person": self.person, "request_id": str(uuid.uuid4())}
        return self._post(body)

    def _post(self, body):
        for attempt in range(1, ATTEMPTS + 1):
            try:
                res = httpx.post(self.url, json=body, headers={"x-secret": self.secret}, timeout=self.timeout)
            except httpx.HTTPError as e:
                log.warning("send attempt %d failed: %s", attempt, e)
                if attempt == ATTEMPTS:
                    raise ForgeError(f"couldn't reach the web trigger: {e}") from e
                continue
            if res.status_code >= 500 and attempt < ATTEMPTS:
                log.warning("send attempt %d: HTTP %d, retrying", attempt, res.status_code)
                continue
            if res.status_code != 200:
                raise ForgeError(f"web trigger answered HTTP {res.status_code}: {res.text[:300]}")
            return res.json()
