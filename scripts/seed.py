"""
Seeds demo data in Jira: Sprint 12 (active), Sprint 13 (future) and 15 issues
with different statuses, priorities and short descriptions.

Before running it:
  1. In your demo site, manually create a **Scrum** project with the key PROJ.
  2. Create a classic API token at id.atlassian.com -> Security -> "Create API token"
     (the regular one, not the scoped token used for Forge).
  3. Create a .env file next to this script with:
         JIRA_SITE=https://YOUR-SITE.atlassian.net
         JIRA_EMAIL=you@example.com
         JIRA_TOKEN=your-classic-token
         PROJECT_KEY=PROJ
  4. pip install requests python-dotenv
  5. python seed_jira.py

When it finishes it prints the board id, the sprint ids and the created issue keys,
and saves them to demo_ids.txt.
"""

import datetime as dt
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

try:
    SITE = os.environ["JIRA_SITE"].rstrip("/")
    AUTH = (os.environ["JIRA_EMAIL"], os.environ["JIRA_TOKEN"])
except KeyError as missing:
    sys.exit(f"Missing variable {missing} in the .env file")

PROJECT = os.environ.get("PROJECT_KEY", "PROJ")
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

# (summary, issue type, final status category, priority, description)
# Status categories: "new" = to do, "indeterminate" = in progress, "done" = done
ISSUES = [
    (
        "Login screen",
        "Story",
        "done",
        "Medium",
        "Users can sign in with email and password. Includes validation errors "
        "and a 'remember me' option.",
    ),
    (
        "Sign up with email and password",
        "Story",
        "done",
        "Medium",
        "New users can create an account. Passwords must be at least 8 characters "
        "and a confirmation email is sent.",
    ),
    (
        "Password reset by email",
        "Story",
        "done",
        "Low",
        "Users receive a reset link that expires after 30 minutes.",
    ),
    (
        "User profile page",
        "Story",
        "done",
        "Medium",
        "Users can view and edit their name, photo and notification preferences.",
    ),
    (
        "Set up CI pipeline",
        "Task",
        "done",
        "Medium",
        "Run lint and unit tests on every pull request and block merges when they fail.",
    ),
    (
        "Migrate database to v2 schema",
        "Task",
        "done",
        "High",
        "Move orders and users to the new schema with zero downtime. Rollback "
        "script tested in staging.",
    ),
    (
        "Document the payments API",
        "Task",
        "done",
        "Low",
        "Write reference docs for the charge, refund and webhook endpoints.",
    ),
    (
        "Shopping cart",
        "Story",
        "indeterminate",
        "High",
        "Users can add, remove and update item quantities. The cart persists "
        "across sessions.",
    ),
    (
        "Payment gateway integration",
        "Story",
        "indeterminate",
        "High",
        "Connect checkout to the payment provider, including 3-D Secure and "
        "payment failure handling.",
    ),
    (
        "Email notifications",
        "Story",
        "indeterminate",
        "Medium",
        "Send emails for order confirmation, shipping updates and password changes.",
    ),
    (
        "Load testing for checkout",
        "Task",
        "indeterminate",
        "Medium",
        "Simulate 500 concurrent users and measure checkout response times.",
    ),
    (
        "Dark mode in the app",
        "Story",
        "new",
        "Low",
        "Add a dark theme that follows the operating system setting.",
    ),
    (
        "Export orders to CSV",
        "Story",
        "new",
        "Medium",
        "Admins can download orders for a date range as a CSV file.",
    ),
    (
        "Checkout fails with international cards",
        "Bug",
        "new",
        "Highest",
        "Payments with cards issued outside the US return a 502 error at checkout. "
        "Roughly 15% of orders are affected.",
    ),
    (
        "Session expires after 5 minutes",
        "Bug",
        "indeterminate",
        "High",
        "Users are logged out after 5 minutes of inactivity instead of 30. "
        "The refresh token is not being renewed.",
    ),
]


def api(method, path, **kwargs):
    """Calls the Jira API and raises a clear error if the request fails."""
    resp = requests.request(
        method, f"{SITE}{path}", auth=AUTH, headers=HEADERS, timeout=30, **kwargs
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text[:400]}")
    return resp.json() if resp.text else {}


def adf(text):
    """Wraps plain text in Atlassian Document Format, required by the v3 API."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def get_board():
    data = api("GET", "/rest/agile/1.0/board", params={"projectKeyOrId": PROJECT})
    boards = data.get("values", [])
    if not boards:
        sys.exit(f"No board found for {PROJECT}. Did you create it as a Scrum project?")
    return boards[0]["id"]


def get_or_create_sprint(board, name):
    data = api(
        "GET",
        f"/rest/agile/1.0/board/{board}/sprint",
        params={"state": "active,future", "maxResults": 50},
    )
    for sprint in data.get("values", []):
        if sprint["name"] == name:
            return sprint
    return api("POST", "/rest/agile/1.0/sprint", json={"name": name, "originBoardId": board})


def create_issue(summary, issue_type, priority, description):
    fields = {
        "project": {"key": PROJECT},
        "summary": summary,
        "issuetype": {"name": issue_type},
        "priority": {"name": priority},
        "description": adf(description),
    }
    try:
        return api("POST", "/rest/api/3/issue", json={"fields": fields})["key"]
    except RuntimeError as error:
        # Some projects don't have the priority field on the create screen.
        if "priority" not in str(error).lower():
            raise
        fields.pop("priority")
        print(f"  (no priority for '{summary}': the project doesn't accept that field)")
        return api("POST", "/rest/api/3/issue", json={"fields": fields})["key"]


def move_to_sprint(sprint_id, keys):
    for i in range(0, len(keys), 50):
        api("POST", f"/rest/agile/1.0/sprint/{sprint_id}/issue", json={"issues": keys[i : i + 50]})


def transition(key, category):
    """Moves the issue to the first available status in the requested category."""
    if category == "new":
        return
    transitions = api("GET", f"/rest/api/3/issue/{key}/transitions")["transitions"]
    for t in transitions:
        if t["to"]["statusCategory"]["key"] == category:
            api("POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": t["id"]}})
            return
    print(f"  (no transition to '{category}' found for {key})")


def start_sprint(sprint):
    if sprint.get("state") == "active":
        return
    now = dt.datetime.now(dt.timezone.utc)
    api(
        "POST",
        f"/rest/agile/1.0/sprint/{sprint['id']}",
        json={
            "state": "active",
            "startDate": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "endDate": (now + dt.timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        },
    )


def main():
    print(f"Site: {SITE} · Project: {PROJECT}")
    board = get_board()
    print(f"Board: {board}")

    sprint12 = get_or_create_sprint(board, "Sprint 12")
    sprint13 = get_or_create_sprint(board, "Sprint 13")
    print(f"Sprint 12: {sprint12['id']} · Sprint 13: {sprint13['id']}")

    print("Creating issues...")
    keys = []
    for summary, issue_type, _, priority, description in ISSUES:
        key = create_issue(summary, issue_type, priority, description)
        keys.append(key)
        print(f"  {key}  {summary}")

    move_to_sprint(sprint12["id"], keys)
    print("Issues moved to Sprint 12")

    start_sprint(sprint12)
    print("Sprint 12 started")

    print("Setting statuses...")
    for key, (_, _, category, _, _) in zip(keys, ISSUES):
        transition(key, category)

    summary = (
        f"JIRA_SITE={SITE}\n"
        f"PROJECT_KEY={PROJECT}\n"
        f"BOARD_ID={board}\n"
        f"SPRINT_12_ID={sprint12['id']}\n"
        f"SPRINT_13_ID={sprint13['id']}\n"
        f"ISSUES={','.join(keys)}\n"
    )
    with open("demo_ids.txt", "w", encoding="utf-8") as f:
        f.write(summary)
    print("\nDone. Saved to demo_ids.txt:\n" + summary)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        sys.exit(f"Error: {error}")