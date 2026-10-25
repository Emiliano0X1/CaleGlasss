/**
 * Consumer of the `agent-runs` queue (manifest.yml: consumer agent-runs-consumer -> function consume-queue).
 *
 * Two kinds of events, each run outside the web trigger's time budget:
 *
 * { type: 'agent', work_id, person }    pushed by triggers/glasses.ts right after the receipt
 *   1. claim_work(work_id, 'jira')      fails if another agent has it or its depends_on isn't done
 *   2. run the Jira agent               it reads Jira and proposes a plan; nothing is executed
 *   3. if it couldn't make a plan, its explanation goes to the person's Telegram
 *
 * { type: 'execute', proposal_id }      pushed by triggers/telegram.ts when someone taps ✅
 *   1. start_execution(id)              only approved -> executing, so a plan never runs twice
 *   2. execute/actions.ts               each change in Jira + record_action
 *   3. complete_proposal(id)            plan and work item done (fail_proposal if an action failed)
 *   4. confirmation to the approver's Telegram: the changes with a link to each issue
 *
 * If it throws (network, Claude, Jira), Forge retries the event; claim_work and
 * submit_proposal are safe to repeat, and an execute retry stops at start_execution.
 *
 * TODO (agents):
 * - [ ] agents/router.ts picks the agent instead of always using Jira.
 */
import type { AsyncEvent } from '@forge/events';
import { heartbeat, runAgent as runLoop } from '../agents/loop';
import { AGENT_NAME, createJiraAgent, type PlanAction } from '../agents/jira_agent';
import { executeActions, ExecutionError, type Change } from '../execute/actions';
import { siteUrl } from '../lib/jira';
import { call, sql, StdbError } from '../lib/stdb';
import { send } from '../lib/telegram';

export const QUEUE_KEY = 'agent-runs';   // must match `queue:` in manifest.yml

export interface AgentRun extends Record<string, unknown> {
  type: 'agent';
  work_id: string;
  person: string;
}

export interface ExecuteRun extends Record<string, unknown> {
  type: 'execute';
  proposal_id: string;
}

export type QueueEvent = AgentRun | ExecuteRun;

const SAFE_ID = /^[A-Za-z0-9_-]{1,80}$/;   // ids go inside SQL strings

export async function consume(event: AsyncEvent<QueueEvent>): Promise<void> {
  const body = event.body;
  console.log(`consumer: ${body.type} event, attempt ${(event.retryContext?.retryCount ?? 0) + 1}`);
  if (body.type === 'agent' && SAFE_ID.test(body.work_id) && SAFE_ID.test(body.person)) {
    return runAgent(body);
  }
  if (body.type === 'execute' && SAFE_ID.test(body.proposal_id)) {
    return execute(body.proposal_id);
  }
  console.error('consumer: invalid event, dropped:', body);   // not retried: it would fail the same way again
}

async function runAgent({ work_id, person }: AgentRun): Promise<void> {
  const [work] = await sql(`SELECT text, status FROM work_items WHERE id = '${work_id}'`);
  if (!work) {
    console.error(`consumer: ${work_id} not found in work_items`);
    return;
  }
  const [text, status] = work.map(String);
  if (status === 'proposed') {
    console.log(`consumer: ${work_id} already has a plan, nothing to do`);
    return;
  }

  try {
    await call('claim_work', [work_id, AGENT_NAME]);
  } catch (e) {
    if (e instanceof StdbError && e.status >= 400 && e.status < 500) {
      console.warn(`consumer: can't claim ${work_id}: ${e.message}`);
      return;   // taken by another agent or blocked by depends_on: retrying won't help
    }
    throw e;
  }

  const chatId = await chatOf(person);
  const agent = createJiraAgent({ workId: work_id, requestText: text, chatId });
  const result = await runLoop(agent, text, work_id);
  console.log(`consumer: ${work_id} finished in ${result.turns} turns, proposed=${result.proposed}`);
  await heartbeat(AGENT_NAME, 'idle', '');

  if (result.proposed) {
    await call('log_event', [AGENT_NAME, `${work_id}: plan proposed`]);
  } else {
    await call('log_event', [AGENT_NAME, `${work_id}: no plan: ${result.text}`]);
    if (chatId) {
      await send(chatId, `🤷 No plan for "${text}": ${result.text || 'the agent stopped without an answer.'}`);
    }
  }
}

async function execute(proposalId: string): Promise<void> {
  const [row] = await sql(`SELECT summary, actions, approved_by FROM proposals WHERE id = '${proposalId}'`);
  if (!row) {
    console.error(`consumer: proposal ${proposalId} not found`);
    return;
  }
  const [summary, actionsJson, approvedBy] = row.map(String);

  try {
    await call('start_execution', [proposalId]);
  } catch (e) {
    if (e instanceof StdbError && e.status >= 400 && e.status < 500) {
      console.warn(`consumer: won't execute ${proposalId}: ${e.message}`);
      return;   // already executing or done: running it again would repeat the changes
    }
    throw e;
  }

  const chatId = await chatOf(approvedBy);
  await heartbeat(AGENT_NAME, 'executing', proposalId);
  let changes: Change[];
  try {
    changes = await executeActions(proposalId, JSON.parse(actionsJson) as PlanAction[]);
  } catch (e) {
    // No rethrow: a retry would stop at start_execution anyway, and half the plan is already applied.
    const done = e instanceof ExecutionError ? e.done : [];
    const message = e instanceof Error ? e.message : String(e);
    console.error(`consumer: ${proposalId} failed after ${done.length} changes:`, message);
    await call('fail_proposal', [proposalId, message]);
    await heartbeat(AGENT_NAME, 'idle', '');
    if (chatId) {
      const list = done.length ? `\n\nDone before the error:\n${await changeList(done)}` : '';
      await send(chatId, `❌ Failed: ${summary}\n${message}${list}`.slice(0, 4000));
    }
    return;
  }

  await call('complete_proposal', [proposalId]);
  await heartbeat(AGENT_NAME, 'idle', '');
  await call('log_event', [AGENT_NAME, `${proposalId}: ${changes.length} changes made`]);
  console.log(`consumer: ${proposalId} done, ${changes.length} changes`);
  if (chatId) {
    await send(chatId, `✅ Done: ${summary}\n\n${await changeList(changes)}`.slice(0, 4000));
  }
}

/** Numbered list "1. PROJ-8: Sprint 12 (5207) → Sprint 13 (5208)" with the issue's link under each line. */
async function changeList(changes: Change[]): Promise<string> {
  const site = await siteUrl();
  return changes
    .map((c, i) => {
      const what = c.type === 'comment' ? `comment "${c.after}"` : `${c.before} → ${c.after}`;
      return `${i + 1}. ${c.issue}: ${what}\n${site}/browse/${c.issue}`;
    })
    .join('\n');
}

async function chatOf(person: string): Promise<string | null> {
  if (!SAFE_ID.test(person)) {
    return null;
  }
  const [chat] = await sql(`SELECT telegram_chat_id FROM people WHERE id = '${person}'`);
  return chat?.[0] ? String(chat[0]) : null;
}
