/**
 * Consumer of the `agent-runs` queue (manifest.yml: consumer agent-runs-consumer -> function consume-queue).
 *
 * Three kinds of events, each run outside the web trigger's time budget:
 *
 * { type: 'router', work_id, person }   pushed by triggers/glasses.ts right after the receipt
 *   agents/router.ts splits the request into work items (jira / reporter, with depends_on)
 *   and pushes one 'agent' event per item
 *
 * { type: 'agent', work_id, person }    pushed by the router, one per work item, and again for
 *                                       the items that depend on a plan once it's done
 *   0. the item's type picks the agent: 'jira' (or 'request', from before the router) or 'reporter'
 *   1. claim_work(work_id, agent)       fails if another agent has it or its depends_on isn't done;
 *                                       blocked by depends_on -> heartbeat "waiting for the jira agent"
 *                                       and stop (step 5 of the dependency's execute queues it again)
 *   2. run the agent                    with the team notes (agents/memory.ts) at the start of its prompt;
 *                                       it reads Jira / Confluence and proposes a plan; nothing is executed
 *   3. if it couldn't make a plan, its explanation goes to the person's Telegram
 *
 * { type: 'execute', proposal_id }      pushed by triggers/telegram.ts when someone taps ✅
 *   1. start_execution(id)              only approved -> executing, so a plan never runs twice
 *   2. execute/actions.ts               each change in Jira + record_action
 *   3. complete_proposal(id)            plan and work item done (fail_proposal if an action failed)
 *   4. confirmation to the approver's Telegram: the changes with a link to each issue (or page)
 *   5. the pending work items that depend on it get an 'agent' event (e.g. the report after the moves)
 *
 * If it throws (network, Claude, Jira), Forge retries the event; claim_work and
 * submit_proposal are safe to repeat, and an execute retry stops at start_execution.
 */
import { Queue, type AsyncEvent } from '@forge/events';
import { heartbeat, runAgent as runLoop, type AgentSpec } from '../agents/loop';
import { withMemory } from '../agents/memory';
import { routeWork } from '../agents/router';
import { AGENT_NAME, createJiraAgent } from '../agents/jira_agent';
import { createReporterAgent, REPORTER_NAME } from '../agents/reporter';
import { executeActions, ExecutionError, type Action, type Change } from '../execute/actions';
import { siteUrl } from '../lib/jira';
import { call, sql, StdbError } from '../lib/stdb';
import { send } from '../lib/telegram';

export const QUEUE_KEY = 'agent-runs';   // must match `queue:` in manifest.yml

export interface RouterRun extends Record<string, unknown> {
  type: 'router';
  work_id: string;
  person: string;
}

export interface AgentRun extends Record<string, unknown> {
  type: 'agent';
  work_id: string;
  person: string;
}

export interface ExecuteRun extends Record<string, unknown> {
  type: 'execute';
  proposal_id: string;
}

export type QueueEvent = RouterRun | AgentRun | ExecuteRun;

const SAFE_ID = /^[A-Za-z0-9_-]{1,80}$/;   // ids go inside SQL strings

/** Work item type -> its agent. 'request': items queued before the router existed. */
type AgentFactory = (ctx: { workId: string; requestText: string; chatId: string | null }) => AgentSpec;
const AGENTS: Record<string, AgentFactory> = {
  [AGENT_NAME]: createJiraAgent,
  request: createJiraAgent,
  [REPORTER_NAME]: createReporterAgent,
};

const agentRuns = new Queue<AgentRun>({ key: QUEUE_KEY });

export async function consume(event: AsyncEvent<QueueEvent>): Promise<void> {
  const body = event.body;
  console.log(`consumer: ${body.type} event, attempt ${(event.retryContext?.retryCount ?? 0) + 1}`);
  if (body.type === 'router' && SAFE_ID.test(body.work_id) && SAFE_ID.test(body.person)) {
    return routeWork(body);
  }
  if (body.type === 'agent' && SAFE_ID.test(body.work_id) && SAFE_ID.test(body.person)) {
    return runAgent(body);
  }
  if (body.type === 'execute' && SAFE_ID.test(body.proposal_id)) {
    return execute(body.proposal_id);
  }
  console.error('consumer: invalid event, dropped:', body);   // not retried: it would fail the same way again
}

async function runAgent({ work_id, person }: AgentRun): Promise<void> {
  const [work] = await sql(`SELECT text, status, type FROM work_items WHERE id = '${work_id}'`);
  if (!work) {
    console.error(`consumer: ${work_id} not found in work_items`);
    return;
  }
  const [text, status, type] = work.map(String);
  const create = AGENTS[type];
  if (!create) {
    console.log(`consumer: ${work_id} is a ${type} item, no agent runs it`);
    return;
  }
  if (status === 'proposed') {
    console.log(`consumer: ${work_id} already has a plan, nothing to do`);
    return;
  }

  const chatId = await chatOf(person);
  const agent = await withMemory(create({ workId: work_id, requestText: text, chatId }));   // + team notes, save_note
  try {
    await call('claim_work', [work_id, agent.name]);
  } catch (e) {
    if (e instanceof StdbError && e.rejected) {
      console.warn(`consumer: can't claim ${work_id}: ${e.message}`);
      if (e.message.includes('depends on')) {
        await heartbeat(agent.name, `waiting for the ${await dependencyAgent(work_id)} agent`, work_id);
      }
      return;   // taken by another agent or blocked by depends_on: retrying won't help
    }
    throw e;
  }

  const result = await runLoop(agent, text, work_id);
  console.log(`consumer: ${work_id} finished in ${result.turns} turns, proposed=${result.proposed}`);
  await heartbeat(agent.name, 'idle', '');

  if (result.proposed) {
    await call('log_event', [agent.name, `${work_id}: plan proposed`]);
  } else {
    await call('log_event', [agent.name, `${work_id}: no plan: ${result.text}`]);
    if (chatId) {
      await send(chatId, `🤷 No plan for "${text}": ${result.text || 'the agent stopped without an answer.'}`);
    }
  }
}

async function execute(proposalId: string): Promise<void> {
  const [row] = await sql(`SELECT summary, actions, approved_by, agent, work_id FROM proposals WHERE id = '${proposalId}'`);
  if (!row) {
    console.error(`consumer: proposal ${proposalId} not found`);
    return;
  }
  const [summary, actionsJson, approvedBy, agentName, workId] = row.map(String);

  try {
    await call('start_execution', [proposalId]);
  } catch (e) {
    if (e instanceof StdbError && e.rejected) {
      console.warn(`consumer: won't execute ${proposalId}: ${e.message}`);
      return;   // already executing or done: running it again would repeat the changes
    }
    throw e;
  }

  const chatId = await chatOf(approvedBy);
  await heartbeat(agentName, 'executing', proposalId);
  let changes: Change[];
  try {
    changes = await executeActions(proposalId, JSON.parse(actionsJson) as Action[]);
  } catch (e) {
    // No rethrow: a retry would stop at start_execution anyway, and half the plan is already applied.
    const done = e instanceof ExecutionError ? e.done : [];
    const message = e instanceof Error ? e.message : String(e);
    console.error(`consumer: ${proposalId} failed after ${done.length} changes:`, message);
    await call('fail_proposal', [proposalId, message]);
    await heartbeat(agentName, 'idle', '');
    if (chatId) {
      const list = done.length ? `\n\nDone before the error:\n${await changeList(done)}` : '';
      await send(chatId, `❌ Failed: ${summary}\n${message}${list}`.slice(0, 4000));
    }
    return;
  }

  await call('complete_proposal', [proposalId]);
  await heartbeat(agentName, 'idle', '');
  await call('log_event', [agentName, `${proposalId}: ${changes.length} changes made`]);
  console.log(`consumer: ${proposalId} done, ${changes.length} changes`);
  if (chatId) {
    await send(chatId, `✅ Done: ${summary}\n\n${await changeList(changes)}`.slice(0, 4000));
  }
  await queueDependents(workId, approvedBy);
}

/** 'agent' events for the pending work items waiting on this one (claim_work lets them through now). */
async function queueDependents(workId: string, person: string): Promise<void> {
  if (!SAFE_ID.test(workId) || !SAFE_ID.test(person)) {
    return;
  }
  const rows = await sql(`SELECT id FROM work_items WHERE depends_on = '${workId}' AND status = 'pending'`);
  for (const [id] of rows) {
    try {
      await agentRuns.push({ body: { type: 'agent', work_id: String(id), person } });
      console.log(`consumer: ${workId} done, queued ${id}`);
    } catch (e) {
      console.error(`consumer: queue push for ${id} failed:`, e);
    }
  }
}

/** Numbered list "1. PROJ-8: Sprint 12 (5207) → Sprint 13 (5208)" with the issue's link under each line. */
async function changeList(changes: Change[]): Promise<string> {
  const site = await siteUrl();
  return changes
    .map((c, i) => {
      if (c.type === 'publish_page') {
        return `${i + 1}. Confluence page "${c.after}"\n${c.url}`;
      }
      const what = c.type === 'comment' ? `comment "${c.after}"` : `${c.before} → ${c.after}`;
      return `${i + 1}. ${c.issue}: ${what}\n${site}/browse/${c.issue}`;
    })
    .join('\n');
}

/** Type of the work item `workId` depends on ('jira', ...), for the "waiting for ..." heartbeat. */
async function dependencyAgent(workId: string): Promise<string> {
  const [row] = await sql(`SELECT depends_on FROM work_items WHERE id = '${workId}'`);
  const dependsOn = String(row?.[0] ?? '');
  if (!SAFE_ID.test(dependsOn)) {
    return 'other';
  }
  const [dependency] = await sql(`SELECT type FROM work_items WHERE id = '${dependsOn}'`);
  return String(dependency?.[0] ?? 'other');
}

async function chatOf(person: string): Promise<string | null> {
  if (!SAFE_ID.test(person)) {
    return null;
  }
  const [chat] = await sql(`SELECT telegram_chat_id FROM people WHERE id = '${person}'`);
  return chat?.[0] ? String(chat[0]) : null;
}
