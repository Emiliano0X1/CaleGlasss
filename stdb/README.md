# stdb

SpacetimeDB module (TypeScript). It stores the live state of each request so that
`eyeclick/bridge/live_state.py` (glasses overlay) and `dashboard/` can show it.

Who writes and who reads:

- **Writes:** `forge-app/src/lib/stdb.ts` (reducers called from Forge)
- **Reads:** `eyeclick/bridge/live_state.py`, `dashboard/`

## TODO

- [ ] Create the module with the SpacetimeDB CLI (TypeScript template) in this folder.
- [ ] `request` table: id, text, source (`glasses` / `telegram`), status, last message, timestamps.
- [ ] `plan` table: id, request id, agent, summary, actions (JSON), approved, result.
- [ ] Reducers: `create_request`, `set_status`, `save_plan`, `set_approval`.
- [ ] Statuses (same as `forge-app/src/lib/stdb.ts`): `received`, `routing`, `working`, `waiting_approval`, `executing`, `done`, `failed`.
