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
| `proposals` | `id` (PK, auto), `work_id`, `agent`, `summary`, `actions` (JSON as text), `status`, `approved_by`, `approved_via` |
| `events` | `id` (PK, auto), `date`, `actor`, `text` |

## Reducers

- `create_work(id, type, text, request_id, depends_on)`: creates a work item with `status = 'pending'`.
  If a work item with that `request_id` already exists, it does nothing, so forge-app can retry without duplicating.
- `log_event(actor, text)`: appends to `events`.

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

On Windows the installer puts `spacetime.exe` in `%LOCALAPPDATA%\SpacetimeDB`; open a new terminal if `spacetime` isn't found.

## TODO

- [ ] Reducers for the rest of the flow: `claim_work`, `set_work_status`, `create_proposal`, `approve_proposal`.
- [ ] Decide who may call the reducers (today anyone who knows the database name).
