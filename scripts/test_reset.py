"""
Puts everything the agents touch back to the start, so the tests can run from zero.

    python test_reset.py           # Jira + Confluence + agent state in SpacetimeDB
    python test_reset.py --wipe    # same, and also empties SpacetimeDB (the panel starts blank)

1. Jira: demo_reset.py restore (sprint, status, assignee, priority, comments of each issue,
   as in demo_snapshot.json).
2. Confluence: deletes (and purges from the trash, so the title can be used again) every page
   under "Sprint reports" that you didn't create yourself: the reports the reporter published.
   Your example report stays.
3. SpacetimeDB:
   - pending plans -> rejected, open work items -> cancelled (so nothing is left waiting)
   - every agent -> idle
   - the two seed notes are written again (a format the reporter saved in a test is replaced)
   With --wipe it republishes the module with --delete-data instead (all tables empty), then
   registers the people again (saved first to stdb_people_backup.json) and writes the seed notes.

Uses the same .env as seed.py (JIRA_SITE, JIRA_EMAIL, JIRA_TOKEN: the classic token also works
for Confluence) and stdb/.env (STDB_TOKEN) for the reducer calls.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import urllib.error
import urllib.parse
import urllib.request
from dotenv import dotenv_values

import demo_reset

HERE = Path(__file__).parent
STDB_DIR = HERE.parent / "stdb"
STDB_ENV = dotenv_values(STDB_DIR / ".env")
STDB = f"{STDB_ENV.get('STDB_HOST') or 'https://maincloud.spacetimedb.com'}/v1/database/{STDB_ENV.get('STDB_DATABASE') or 'agentes'}"
PEOPLE_BACKUP = HERE / "stdb_people_backup.json"

PARENT_TITLES = ["Sprint reports", "Sprints reports"]   # the second one: how it was first typed in Confluence
SEED_NOTES = {
    "people/ana": "Ana = Alana Grant in Jira, accountId 60ad2d2a06bf0c006a42fa84 (use it to assign issues to Ana without searching).",
    "reporter/report-format": "Report format, sections in this order: Summary, Done, Moves to the next sprint, Risks.",
}
OPEN_WORK = ("pending", "claimed", "proposed", "approved")


# --- Confluence -------------------------------------------------------------------------------

class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.content = body
        self.text = body.decode("utf-8", errors="replace")
        self.ok = 200 <= status_code < 400

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text[:300]}")


def http_request(method, url, *, auth=None, headers=None, params=None, data=None, json_body=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    request_headers = dict(headers or {})
    if auth:
        import base64
        credentials = f"{auth[0]}:{auth[1]}".encode()
        request_headers["Authorization"] = "Basic " + base64.b64encode(credentials).decode()
    if json_body is not None:
        data = json.dumps(json_body).encode()
        request_headers.setdefault("Content-Type", "application/json")
    elif isinstance(data, str):
        data = data.encode()
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            return _Response(response.status, response.read())
    except urllib.error.HTTPError as error:
        return _Response(error.code, error.read())


def wiki(method, path, **kwargs):
    res = http_request(method, f"{demo_reset.SITE}/wiki{path}", auth=demo_reset.AUTH, headers=demo_reset.HEADERS, **kwargs)
    if not res.ok:
        sys.exit(f"Confluence {method} {path} -> HTTP {res.status_code}: {res.text[:300]}")
    return res.json() if res.content else None


def reset_confluence():
    titles = " OR ".join(f'title = "{t}"' for t in PARENT_TITLES)
    found = wiki("GET", "/rest/api/content/search", params={"cql": f"type = page AND ({titles})"})["results"]
    if not found:
        print("Confluence: no \"Sprint reports\" page found, nothing to clean")
        return
    me = wiki("GET", "/rest/api/user/current")["accountId"]
    deleted = 0
    for parent in found:
        children = wiki("GET", f"/api/v2/pages/{parent['id']}/children", params={"limit": 250})["results"]
        for child in children:
            page = wiki("GET", f"/api/v2/pages/{child['id']}")
            if page.get("authorId") == me:
                print(f"Confluence: keeping \"{page['title']}\" (yours)")
                continue
            wiki("DELETE", f"/api/v2/pages/{child['id']}")                       # to the trash
            wiki("DELETE", f"/api/v2/pages/{child['id']}", params={"purge": "true"})   # out of the trash
            print(f"Confluence: deleted \"{page['title']}\"")
            deleted += 1
    print(f"Confluence: {deleted} report(s) deleted")


# --- SpacetimeDB ------------------------------------------------------------------------------

def sql(query):
    res = http_request("POST", f"{STDB}/sql", data=query)
    res.raise_for_status()
    return res.json()[0]["rows"]


def call(reducer, *args):
    res = http_request("POST", f"{STDB}/call/{reducer}", json_body=list(args),
                       headers={"Authorization": f"Bearer {STDB_ENV['STDB_TOKEN']}"})
    if not res.ok:
        raise RuntimeError(f"{reducer} {args}: HTTP {res.status_code} {res.text[:200]}")


def seed_notes():
    for path, content in SEED_NOTES.items():
        call("memory_write", path, content)
    print(f"SpacetimeDB: {len(SEED_NOTES)} seed notes written")


def reset_stdb():
    pending = sql("SELECT id FROM proposals WHERE status = 'pending'")
    for (proposal_id,) in pending:
        call("reject_proposal", proposal_id, "reset", "reset")
    work = [row for row in sql("SELECT id, status FROM work_items") if row[1] in OPEN_WORK]
    for work_id, _ in work:
        call("set_work_status", work_id, "cancelled")
    agents = sql("SELECT name FROM agents")
    for (name,) in agents:
        call("heartbeat", name, "idle", "")
    print(f"SpacetimeDB: {len(pending)} plan(s) rejected, {len(work)} work item(s) cancelled, {len(agents)} agent(s) idle")
    seed_notes()


def wipe_stdb():
    people = sql("SELECT id, name, telegram_chat_id, atlassian_account_id FROM people")
    PEOPLE_BACKUP.write_text(json.dumps(people, indent=2) + "\n")
    print(f"SpacetimeDB: {len(people)} person(s) saved to {PEOPLE_BACKUP.name}")

    cli = shutil.which("spacetime") or str(Path(os.environ["LOCALAPPDATA"]) / "SpacetimeDB" / "spacetime.exe")
    database = STDB_ENV.get("STDB_DATABASE") or "agentes"
    subprocess.run([cli, "publish", database, "--delete-data", "--yes=all"], cwd=STDB_DIR, check=True)

    for person in people:
        call("register_person", *person)
    print(f"SpacetimeDB: emptied, {len(people)} person(s) registered again")
    seed_notes()


if __name__ == "__main__":
    wipe = "--wipe" in sys.argv[1:]
    if [a for a in sys.argv[1:] if a != "--wipe"]:
        sys.exit("usage: python test_reset.py [--wipe]")
    if wipe and input("--wipe empties every SpacetimeDB table (history included). Type yes: ").strip() != "yes":
        sys.exit("Cancelled")
    demo_reset.restore()
    reset_confluence()
    wipe_stdb() if wipe else reset_stdb()
    print("Ready: everything is back to the start")
