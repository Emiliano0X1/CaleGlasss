"""
Saves and restores the state of the demo issues, so the agent's changes can be undone
between rehearsals.

    python demo_reset.py save       # writes demo_snapshot.json (do this once, with the demo as it should be)
    python demo_reset.py restore    # puts every issue back as in demo_snapshot.json

Per issue it keeps the sprint, status, assignee, priority and the ids of its comments.
restore moves issues back to their sprint (or the backlog), transitions them to the saved
status, resets the assignee and priority, and deletes comments added after the snapshot.

Uses the same .env as seed.py (JIRA_SITE, JIRA_EMAIL, JIRA_TOKEN) and the ISSUES line of
demo_ids.txt.
"""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

try:
    SITE = os.environ["JIRA_SITE"].rstrip("/")
    AUTH = (os.environ["JIRA_EMAIL"], os.environ["JIRA_TOKEN"])
except KeyError as missing:
    sys.exit(f"Missing variable {missing} in the .env file")

HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
SNAPSHOT = HERE / "demo_snapshot.json"


def demo_issues():
    for line in (HERE / "demo_ids.txt").read_text().splitlines():
        if line.startswith("ISSUES="):
            return line.split("=", 1)[1].split(",")
    sys.exit("demo_ids.txt has no ISSUES= line (run seed.py first)")


def jira(method, path, **kwargs):
    res = requests.request(method, f"{SITE}{path}", auth=AUTH, headers=HEADERS, **kwargs)
    if not res.ok:
        sys.exit(f"{method} {path} -> HTTP {res.status_code}: {res.text[:300]}")
    return res.json() if res.content else None


def state(key):
    f = jira("GET", f"/rest/agile/1.0/issue/{key}?fields=sprint,status,assignee,priority")["fields"]
    comments = jira("GET", f"/rest/api/3/issue/{key}/comment?maxResults=100")["comments"]
    return {
        "sprint_id": f["sprint"]["id"] if f.get("sprint") else None,
        "status": f["status"]["name"],
        "assignee": f["assignee"]["accountId"] if f.get("assignee") else None,
        "priority": f["priority"]["name"],
        "comment_ids": [c["id"] for c in comments],
    }


def save():
    snapshot = {key: state(key) for key in demo_issues()}
    SNAPSHOT.write_text(json.dumps(snapshot, indent=2) + "\n")
    print(f"Saved {len(snapshot)} issues to {SNAPSHOT.name}")


def restore():
    if not SNAPSHOT.exists():
        sys.exit(f"{SNAPSHOT.name} doesn't exist: run `python demo_reset.py save` first")
    snapshot = json.loads(SNAPSHOT.read_text())
    changed = 0
    for key, want in snapshot.items():
        now = state(key)
        fixes = []
        if now["sprint_id"] != want["sprint_id"]:
            if want["sprint_id"]:
                jira("POST", f"/rest/agile/1.0/sprint/{want['sprint_id']}/issue", json={"issues": [key]})
            else:
                jira("POST", "/rest/agile/1.0/backlog/issue", json={"issues": [key]})
            fixes.append(f"sprint {now['sprint_id']} -> {want['sprint_id']}")
        if now["status"] != want["status"]:
            transitions = jira("GET", f"/rest/api/3/issue/{key}/transitions")["transitions"]
            match = next((t for t in transitions if t["to"]["name"] == want["status"]), None)
            if match:
                jira("POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": match["id"]}})
                fixes.append(f"status {now['status']} -> {want['status']}")
            else:
                fixes.append(f"status {now['status']}: no transition to {want['status']}, fix it by hand")
        if now["assignee"] != want["assignee"]:
            jira("PUT", f"/rest/api/3/issue/{key}/assignee", json={"accountId": want["assignee"]})
            fixes.append("assignee")
        if now["priority"] != want["priority"]:
            jira("PUT", f"/rest/api/3/issue/{key}", json={"fields": {"priority": {"name": want["priority"]}}})
            fixes.append(f"priority {now['priority']} -> {want['priority']}")
        for comment_id in now["comment_ids"]:
            if comment_id not in want["comment_ids"]:
                jira("DELETE", f"/rest/api/3/issue/{key}/comment/{comment_id}")
                fixes.append(f"deleted comment {comment_id}")
        if fixes:
            changed += 1
            print(f"{key}: {', '.join(fixes)}")
    print(f"Restored {changed} issues" if changed else "Nothing to restore: the demo is as saved")


if __name__ == "__main__":
    commands = {"save": save, "restore": restore}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit("usage: python demo_reset.py save | restore")
    commands[sys.argv[1]]()
