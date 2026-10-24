# dashboard

Web panel (Vite + SpacetimeDB SDK). It shows live the same state the glasses
overlay shows: incoming requests, which agent is working, plans waiting for
approval, and results. Useful for the audience during the demo.

Reads from `stdb/`; it doesn't write anything.

## TODO

- [ ] Create the project with Vite (TypeScript template) in this folder.
- [ ] Connect with the SpacetimeDB SDK and subscribe to the `request` and `plan` tables.
- [ ] Request list with their status, and the detail of each plan.
- [ ] Large view for projecting during the demo.
