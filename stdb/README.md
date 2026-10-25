# stdb

SpacetimeDB module `agentes` (TypeScript, maincloud). It stores the live state of the agent
team so that `eyeclick/bridge/live_state.py` (glasses overlay) and `dashboard/` can show it.

- **Writes:** `forge-app/src/lib/stdb.ts` (calls the reducers)
- **Reads:** `eyeclick/bridge/live_state.py`, `dashboard/`

Created with `spacetime init --lang typescript --server-only`. The module is in
`spacetimedb/src/index.ts`; `spacetime.json` points the CLI at it and at maincloud.

## Tables (all public)

| Table | Columns |
|---|---|
| `work_items` | `id` (PK), `type`, `text`, `status`, `claimed_by`, `request_id` (unique), `depends_on`, `created_at` |
| `proposals` | `id` (PK, text: the ✅ button sends `ap:<id>`), `work_id`, `agent`, `summary`, `actions` (JSON as text), `status`, `approved_by`, `approved_via` |
| `events` | `id` (PK, auto), `date`, `actor`, `text` |
| `people` | `id` (PK, what the glasses send as `person`), `name`, `telegram_chat_id`, `atlassian_account_id` |
| `agents` | `name` (PK), `status`, `work_id`, `last_seen` (last heartbeat) |
| `actions` | `id` (PK, auto), `proposal_id`, `type`, `target` (issue key), `before`, `after`, `date`: one row per change made in Jira |
| `plan_messages` | `proposal_id` (PK), `chat_id`, `message_id`, `text`: the Telegram message each plan was sent in, so an approval from the glasses can edit it |
| `memory` | `path` (PK, e.g. `people/ana`, `reporter/report-format`), `content`, `updated_at`: the agents' notes, at the start of every agent's prompt (`forge-app/src/agents/memory.ts`) |

## Reducers

- `create_work(id, type, text, request_id, depends_on)`: creates a work item with `status = 'pending'`.
  If a work item with that `request_id` already exists, it does nothing, so forge-app can retry without duplicating.
- `log_event(actor, text)`: appends to `events`.
- `register_person(id, name, telegram_chat_id, atlassian_account_id)`: creates or updates a person.
- `heartbeat(agent, status, work_id)`: the agent's current state (one row per agent).
- `claim_work(work_id, agent)`: sets `claimed_by` and `status = 'claimed'`. Fails if another agent has it or its `depends_on` isn't `done`; the same agent claiming again is fine.
- `submit_proposal(id, work_id, agent, summary, actions)`: saves the plan as `pending` (nothing is executed) and sets the work item to `proposed`. Only the agent that claimed it can submit; resubmitting a pending proposal replaces it.

- `approve_proposal(id, person, via)`: only a `pending` proposal; otherwise it fails with `already approved by ...`.
- `start_execution(id)`: only `approved` → `executing`, so the same plan never runs twice.
- `record_action(proposal_id, type, target, before, after)`: one change made in Jira (the proposal must be `executing`).
- `complete_proposal(id)`: the proposal and its work item become `done` (this unblocks `depends_on`).
- `fail_proposal(id, error)`: an action failed halfway; proposal and work item become `failed`, the error goes to `events`.
- `reject_proposal(id, person, via)`: only a `pending` proposal; it and its work item become `rejected`.
- `set_work_status(id, status)`: closes work items no agent runs (voice approvals: `done`, voice input nobody understood: `unclear`, a request the router split into work items: `routed`).
- `save_plan_message(proposal_id, chat_id, message_id, text)`: called by the Jira agent right after it sends the plan.
- `memory_write(path, content)`: creates or replaces a note (the agents' `save_note` tool).

Work item status: `pending` → `claimed` → `proposed` → `approved` → `executing` → `done` (or `failed`).
Proposal status: `pending` → `approved` → `executing` → `done` (or `failed`).

## Usage

```bash
cd stdb
spacetime login                      # first time (opens the browser)
cd spacetimedb && npm install && cd ..
spacetime publish agentes            # build + publish to maincloud
spacetime call agentes create_work '"w1"' '"jira"' '"move pending items"' '"r1"' '""'
spacetime sql agentes "SELECT * FROM work_items"
spacetime logs agentes               # module errors show up here, not in `call`
```

`spacetime call` (CLI 2.13) takes **one JSON value per argument**. The single-array form
`'["w1", "jira", ...]'` fails with `invalid arguments ... expected , or ]`. Run these from Git Bash:
PowerShell 5.1 strips the inner double quotes when it passes them to `spacetime.exe`.

The database is live on maincloud: https://spacetimedb.com/agentes

## HTTP access (what Forge uses)

Forge runs in Atlassian's cloud and can't reach localhost, so the database lives on maincloud.
Forge writes with its own SpacetimeDB identity:

```bash
curl -X POST https://maincloud.spacetimedb.com/v1/identity     # -> { "identity": ..., "token": ... }
```

The identity and token are in `stdb/.env` (gitignored, never commit it):
`STDB_HOST`, `STDB_DATABASE`, `STDB_IDENTITY`, `STDB_TOKEN`. In Forge the token goes in an encrypted
environment variable (`forge variables set --encrypt STDB_TOKEN ...`), not in the code.

```bash
B=https://maincloud.spacetimedb.com/v1/database/agentes
curl -X POST "$B/sql" -d "SELECT * FROM work_items"                     # read: JSON with schema + rows
curl -X POST "$B/call/log_event" -H "Authorization: Bearer $STDB_TOKEN" \
     -H "Content-Type: application/json" -d '["me", "hello"]'           # reducer args as a JSON array
```

Over HTTP, `/call/<reducer>` takes **all the arguments in one JSON array**, unlike `spacetime call`.
The tables are public and the reducers don't check the caller yet, so anyone who knows the name can
read and write (see TODO).

On Windows the installer puts `spacetime.exe` in `%LOCALAPPDATA%\SpacetimeDB`; open a new terminal if `spacetime` isn't found.

## TODO

- [ ] A status for work items the agent couldn't make a plan for (today they stay `claimed`).
- [ ] Decide who may call the reducers (today anyone who knows the database name).
