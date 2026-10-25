# dashboard_agents

Live web panel for the agent team (Vite + React + SpacetimeDB SDK). It subscribes to the
`agentes` database on maincloud (`stdb/`) and updates without reloading.

| Block | Table(s) |
|---|---|
| Agents: status of each one, `offline` after 2 min without a heartbeat | `agents` |
| Work: status, who claimed it, "waiting on …" while its `depends_on` isn't `done` | `work_items` |
| Pending plans, with an **Approve** button | `proposals` (`pending`) |
| Events feed, newest first | `events` |
| Log: what was changed (before → after), who approved and via what | `proposals` + `actions` |

**Approve** sends `{ type: "approve", via: "panel", ... }` to the `glasses` web trigger
(`forge-app/src/triggers/glasses.ts`), the same path as a long blink from the glasses.

## Usage

```bash
cp .env.example .env.local     # fill in the web trigger URL, APPROVAL_SECRET and PERSON_ID
npm install
npm run dev
```

`VITE_APPROVAL_SECRET` ends up in the browser bundle: run the panel locally, never deploy it.
Without the URL and secret the panel still works, it just can't approve.

## Bindings

`src/module_bindings/` is generated. After changing the module, regenerate from `stdb/`:

```bash
spacetime generate --lang typescript --out-dir ../dashboard_agents/src/module_bindings --module-path ./spacetimedb
```
