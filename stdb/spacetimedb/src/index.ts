/**
 * SpacetimeDB module `agentes`: live state of the agent team.
 *
 * Writes: forge-app/src/lib/stdb.ts (calling the reducers).
 * Read:   eyeclick/bridge/live_state.py (glasses overlay) and dashboard/.
 *
 * Tables (public, any client can subscribe):
 *   work_items  one work item per request; request_id is unique (a request never creates two)
 *   proposals   the plan an agent proposes for a work item, waiting for approval
 *   events      log: what happened, who did it and when
 *
 * Column and reducer names are snake_case on purpose: they're what you use in
 * `spacetime call agentes create_work ...` and `spacetime sql agentes ...`.
 *
 * TODO (agents):
 * - [ ] Reducers for the rest of the flow: claim_work, set_work_status, create_proposal, approve_proposal.
 * - [ ] Decide who may call the reducers (today anyone who knows the database name).
 */
import { schema, table, t, SenderError } from 'spacetimedb/server';

const workItems = table(
  { name: 'work_items', public: true },
  {
    id: t.string().primaryKey(),
    type: t.string(),                 // agent that handles it: 'jira', 'reporter', ...
    text: t.string(),                 // what the person asked for
    status: t.string(),               // 'pending' when created
    claimed_by: t.string(),           // '' until an agent takes it
    request_id: t.string().unique(),  // forge-app request id
    depends_on: t.string(),           // id of another work item, or ''
    created_at: t.timestamp(),
  }
);

const proposals = table(
  { name: 'proposals', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    work_id: t.string().index('btree'),
    agent: t.string(),
    summary: t.string(),
    actions: t.string(),              // JSON as text: [{ type, input }, ...]
    status: t.string(),               // 'pending' | 'approved' | 'rejected' | 'done' | 'failed'
    approved_by: t.string(),          // who approved it, or ''
    approved_via: t.string(),         // 'glasses' | 'telegram' | ''
  }
);

const events = table(
  { name: 'events', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    date: t.timestamp(),
    actor: t.string(),
    text: t.string(),
  }
);

const spacetimedb = schema({ workItems, proposals, events });
export default spacetimedb;

// If a work item with that request_id already exists it does nothing: forge-app can retry without duplicates.
export const create_work = spacetimedb.reducer(
  { id: t.string(), type: t.string(), text: t.string(), request_id: t.string(), depends_on: t.string() },
  (ctx, { id, type, text, request_id, depends_on }) => {
    if (ctx.db.workItems.request_id.find(request_id)) {
      return;
    }
    if (ctx.db.workItems.id.find(id)) {
      throw new SenderError(`a work item with id ${id} already exists (from another request_id)`);
    }
    ctx.db.workItems.insert({
      id,
      type,
      text,
      status: 'pending',
      claimed_by: '',
      request_id,
      depends_on,
      created_at: ctx.timestamp,
    });
  }
);

export const log_event = spacetimedb.reducer(
  { actor: t.string(), text: t.string() },
  (ctx, { actor, text }) => {
    ctx.db.events.insert({ id: 0n, date: ctx.timestamp, actor, text });
  }
);
