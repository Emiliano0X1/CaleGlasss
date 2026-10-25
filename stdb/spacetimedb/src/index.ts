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
 *   people      who can make requests: Telegram chat (receipts, approvals) and Atlassian account
 *   agents      each agent's last heartbeat: what it's doing and on which work item
 *   actions     one row per change made in Jira while executing a proposal (before / after)
 *
 * Work item status: pending -> claimed (claim_work) -> proposed (submit_proposal)
 *   -> approved (approve_proposal) -> executing (start_execution) -> done (complete_proposal)
 *   or failed (fail_proposal).
 * Proposal status:  pending -> approved -> executing -> done | failed.
 *
 * Column and reducer names are snake_case on purpose: they're what you use in
 * `spacetime call agentes create_work ...` and `spacetime sql agentes ...`.
 *
 * TODO (agents):
 * - [ ] A status for work items the agent couldn't make a plan for (they stay 'claimed').
 * - [ ] Decide who may call the reducers (today anyone who knows the database name).
 */
import { schema, table, t, SenderError } from 'spacetimedb/server';

const workItems = table(
  { name: 'work_items', public: true },
  {
    id: t.string().primaryKey(),
    type: t.string(),                 // agent that handles it: 'jira', 'reporter', ...
    text: t.string(),                 // what the person asked for
    status: t.string(),               // 'pending' | 'claimed' | 'proposed' | ... ('done' unblocks depends_on)
    claimed_by: t.string(),           // '' until an agent takes it (claim_work)
    request_id: t.string().unique(),  // forge-app request id
    depends_on: t.string(),           // id of another work item, or ''
    created_at: t.timestamp(),
  }
);

const proposals = table(
  { name: 'proposals', public: true },
  {
    id: t.string().primaryKey(),      // chosen by the agent; the ✅ button sends ap:<id>
    work_id: t.string().index('btree'),
    agent: t.string(),
    summary: t.string(),
    actions: t.string(),              // JSON as text: [{ type: 'move_to_sprint', issue, ... }, ...]
    status: t.string(),               // 'pending' | 'approved' | 'executing' | 'done' | 'failed'
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

const people = table(
  { name: 'people', public: true },
  {
    id: t.string().primaryKey(),      // what the glasses send as `person`, e.g. 'emiliano'
    name: t.string(),
    telegram_chat_id: t.string(),     // text: Telegram ids can exceed 32 bits
    atlassian_account_id: t.string(),
  }
);

const agents = table(
  { name: 'agents', public: true },
  {
    name: t.string().primaryKey(),    // 'jira', 'reporter', ...
    status: t.string(),               // free text: 'turn 3/15', 'idle', ...
    work_id: t.string(),              // work item it's on, or ''
    last_seen: t.timestamp(),
  }
);

const actions = table(
  { name: 'actions', public: true },
  {
    id: t.u64().primaryKey().autoInc(),
    proposal_id: t.string().index('btree'),
    type: t.string(),                 // 'move_to_sprint', 'transition', 'assign', ...
    target: t.string(),               // issue key
    before: t.string(),               // value before the change, e.g. 'Sprint 12'
    after: t.string(),                // value after it, e.g. 'Sprint 13'
    date: t.timestamp(),
  }
);

const spacetimedb = schema({ workItems, proposals, events, people, agents, actions });
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

// Creates the person or updates them if the id already exists (registering twice is fine).
export const register_person = spacetimedb.reducer(
  { id: t.string(), name: t.string(), telegram_chat_id: t.string(), atlassian_account_id: t.string() },
  (ctx, person) => {
    if (ctx.db.people.id.find(person.id)) {
      ctx.db.people.id.update(person);
    } else {
      ctx.db.people.insert(person);
    }
  }
);

// The agent says it's alive and what it's doing (one row per agent, overwritten each time).
export const heartbeat = spacetimedb.reducer(
  { agent: t.string(), status: t.string(), work_id: t.string() },
  (ctx, { agent, status, work_id }) => {
    const row = { name: agent, status, work_id, last_seen: ctx.timestamp };
    if (ctx.db.agents.name.find(agent)) {
      ctx.db.agents.name.update(row);
    } else {
      ctx.db.agents.insert(row);
    }
  }
);

// Fails if another agent already has it or if its depends_on isn't done.
// Claiming again with the same agent is fine (the queue may retry the run).
export const claim_work = spacetimedb.reducer(
  { work_id: t.string(), agent: t.string() },
  (ctx, { work_id, agent }) => {
    const work = ctx.db.workItems.id.find(work_id);
    if (!work) {
      throw new SenderError(`work item ${work_id} doesn't exist`);
    }
    if (work.claimed_by && work.claimed_by !== agent) {
      throw new SenderError(`work item ${work_id} is already claimed by ${work.claimed_by}`);
    }
    if (work.depends_on) {
      const dependency = ctx.db.workItems.id.find(work.depends_on);
      if (!dependency || dependency.status !== 'done') {
        throw new SenderError(`work item ${work_id} depends on ${work.depends_on}, which isn't done`);
      }
    }
    if (work.claimed_by !== agent) {
      ctx.db.workItems.id.update({ ...work, claimed_by: agent, status: 'claimed' });
    }
  }
);

// Saves the plan as pending (nothing is executed) and marks the work item as proposed.
// Resubmitting a still-pending proposal replaces it (the queue may retry the run).
export const submit_proposal = spacetimedb.reducer(
  { id: t.string(), work_id: t.string(), agent: t.string(), summary: t.string(), actions: t.string() },
  (ctx, { id, work_id, agent, summary, actions }) => {
    const work = ctx.db.workItems.id.find(work_id);
    if (!work) {
      throw new SenderError(`work item ${work_id} doesn't exist`);
    }
    if (work.claimed_by !== agent) {
      throw new SenderError(`work item ${work_id} isn't claimed by ${agent}`);
    }
    const row = { id, work_id, agent, summary, actions, status: 'pending', approved_by: '', approved_via: '' };
    const existing = ctx.db.proposals.id.find(id);
    if (existing && existing.status !== 'pending') {
      throw new SenderError(`proposal ${id} is already ${existing.status}`);
    }
    if (existing) {
      ctx.db.proposals.id.update(row);
    } else {
      ctx.db.proposals.insert(row);
    }
    ctx.db.workItems.id.update({ ...work, status: 'proposed' });
  }
);

export const log_event = spacetimedb.reducer(
  { actor: t.string(), text: t.string() },
  (ctx, { actor, text }) => {
    ctx.db.events.insert({ id: 0n, date: ctx.timestamp, actor, text });
  }
);

// Only a pending proposal can be approved: a second tap fails with "already approved by ...".
export const approve_proposal = spacetimedb.reducer(
  { id: t.string(), person: t.string(), via: t.string() },
  (ctx, { id, person, via }) => {
    const proposal = ctx.db.proposals.id.find(id);
    if (!proposal) {
      throw new SenderError(`proposal ${id} doesn't exist`);
    }
    if (proposal.status !== 'pending') {
      throw new SenderError(`already approved by ${proposal.approved_by || 'nobody'} (status ${proposal.status})`);
    }
    ctx.db.proposals.id.update({ ...proposal, status: 'approved', approved_by: person, approved_via: via });
    const work = ctx.db.workItems.id.find(proposal.work_id);
    if (work) {
      ctx.db.workItems.id.update({ ...work, status: 'approved' });
    }
  }
);

// Only approved -> executing, so a retried or duplicated execute event can't run the plan twice.
export const start_execution = spacetimedb.reducer({ id: t.string() }, (ctx, { id }) => {
  const proposal = ctx.db.proposals.id.find(id);
  if (!proposal) {
    throw new SenderError(`proposal ${id} doesn't exist`);
  }
  if (proposal.status !== 'approved') {
    throw new SenderError(`proposal ${id} is ${proposal.status}, not approved`);
  }
  ctx.db.proposals.id.update({ ...proposal, status: 'executing' });
  const work = ctx.db.workItems.id.find(proposal.work_id);
    if (work) {
      ctx.db.workItems.id.update({ ...work, status: 'executing' });
    }
});

export const record_action = spacetimedb.reducer(
  { proposal_id: t.string(), type: t.string(), target: t.string(), before: t.string(), after: t.string() },
  (ctx, { proposal_id, type, target, before, after }) => {
    const proposal = ctx.db.proposals.id.find(proposal_id);
    if (!proposal || proposal.status !== 'executing') {
      throw new SenderError(`proposal ${proposal_id} isn't executing`);
    }
    ctx.db.actions.insert({ id: 0n, proposal_id, type, target, before, after, date: ctx.timestamp });
  }
);

// Marks the plan and its work item as done (this also unblocks work items that depend on it).
export const complete_proposal = spacetimedb.reducer({ id: t.string() }, (ctx, { id }) => {
  const proposal = ctx.db.proposals.id.find(id);
  if (!proposal || proposal.status !== 'executing') {
    throw new SenderError(`proposal ${id} isn't executing`);
  }
  ctx.db.proposals.id.update({ ...proposal, status: 'done' });
  const work = ctx.db.workItems.id.find(proposal.work_id);
    if (work) {
      ctx.db.workItems.id.update({ ...work, status: 'done' });
    }
});

// An action failed halfway: the plan and its work item stay as failed (the changes already
// made are in `actions`).
export const fail_proposal = spacetimedb.reducer({ id: t.string(), error: t.string() }, (ctx, { id, error }) => {
  const proposal = ctx.db.proposals.id.find(id);
  if (!proposal) {
    throw new SenderError(`proposal ${id} doesn't exist`);
  }
  ctx.db.proposals.id.update({ ...proposal, status: 'failed' });
  const work = ctx.db.workItems.id.find(proposal.work_id);
    if (work) {
      ctx.db.workItems.id.update({ ...work, status: 'failed' });
    }
  ctx.db.events.insert({ id: 0n, date: ctx.timestamp, actor: proposal.agent, text: `${id} failed: ${error}` });
});
