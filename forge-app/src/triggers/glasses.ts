/**
 * `glasses` web trigger: what the person said into the glasses.
 * Called by eyeclick/bridge/forge_client.py with a POST.
 *
 *   header  x-secret: <APPROVAL_SECRET>
 *   body    { "type": "request", "text": "<Whisper transcript>", "person": "me", "request_id": "r1" }
 *           { "type": "approve", "proposal_id": "p-...", "person": "me", "request_id": "r2", "via": "panel" }
 *
 * "approve" comes from a long blink (or the word "approve") while the overlay shows a pending
 * plan (bridge/live_state.py), or from the dashboard's Approve button (via "panel"; default
 * "glasses"): approve_proposal with that via, execute queued, and the plan's Telegram message
 * edited to "Approved from the glasses" / "from the panel".
 *
 * The dashboard calls it from the browser, so every answer carries CORS headers and an
 * OPTIONS preflight gets a 204 (lib/webtrigger.ts withCors / preflight).
 *
 * 1. Wrong or missing x-secret -> 401 and nothing is created.
 * 2. Invalid body -> 400.
 * 3. A work item with that request_id already exists -> 200 { duplicate: true } and nothing new
 *    (so a retry never approves twice or creates two requests).
 * 4. agents/interpret.ts (Claude, ~1 s) cleans up the transcript and says what it is:
 *    - request:  create_work with the clean instruction; in parallel log_event, the receipt
 *                "📥 Got your request" (+ what was heard) to the person's Telegram, and
 *                { type: 'router', work_id, person } to the `agent-runs` queue: the router
 *                (agents/router.ts) splits it into work items and queues an agent for each.
 *    - approve / reject: applies to the newest pending plan (execute/approve.ts), the same as
 *                the ✅ button; Telegram gets "✅ Approved by voice" / "❌ Rejected".
 *    - unclear:  nothing runs; Telegram gets "🤔 Didn't get that".
 *    Every input is a work item (type = intent) so the request_id check above covers it;
 *    approvals and unclear input are closed right away with set_work_status.
 *    A failed Telegram message or queue push doesn't fail the request: the response says
 *    receipt: sent | no_chat | failed and router: queued | failed.
 */
import { Queue } from '@forge/events';
import { interpret } from '../agents/interpret';
import { approve, latestPending, reject, updatePlanMessage } from '../execute/approve';
import { QUEUE_KEY, type RouterRun } from '../queue/consumer';
import { call, sql, StdbError } from '../lib/stdb';
import { send } from '../lib/telegram';
import {
  header,
  json,
  preflight,
  secretMatches,
  withCors,
  type WebTriggerRequest,
  type WebTriggerResponse,
} from '../lib/webtrigger';

const agentRuns = new Queue<RouterRun>({ key: QUEUE_KEY });

interface GlassesRequest {
  type: 'request' | 'approve';
  text: string;          // '' for approve
  proposal_id: string;   // '' for request
  via: Via;              // approve only: where the approval came from
  person: string;
  request_id: string;
}

const SAFE_ID = /^[A-Za-z0-9_-]{1,64}$/;   // request_id and person: also makes them safe inside SQL strings

type Via = 'glasses' | 'panel';
const VIA_LABEL: Record<Via, string> = { glasses: 'the glasses', panel: 'the panel' };

export async function glasses(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  if (request.method === 'OPTIONS') {
    return preflight();
  }
  return withCors(await handle(request));
}

async function handle(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  if (!secretMatches(header(request, 'x-secret'), process.env.APPROVAL_SECRET)) {
    return json(401, { error: 'invalid x-secret' });
  }

  const parsed = parse(request.body);
  if (typeof parsed === 'string') {
    return json(400, { error: parsed });
  }
  const { type, text, proposal_id, via, person, request_id } = parsed;

  try {
    const existing = await sql(`SELECT id FROM work_items WHERE request_id = '${request_id}'`);
    if (existing.length > 0) {
      console.log(`glasses: request ${request_id} already exists (${existing[0][0]})`);
      return json(200, { ok: true, duplicate: true, work_id: existing[0][0], request_id });
    }

    const workId = `w-${request_id}`;
    if (type === 'approve') {
      await call('create_work', [workId, 'approve', `approve ${proposal_id}`, request_id, '']);
      const decision = await approveFrom(via, proposal_id, person);
      await call('set_work_status', [workId, 'done']);
      await call('log_event', [person, `approve from ${VIA_LABEL[via]}: ${decision.result} ${proposal_id}`]);
      return json(200, { ok: true, duplicate: false, work_id: workId, request_id, intent: 'approve', ...decision });
    }

    const { intent, instruction, note } = await interpret(text);
    const base = { ok: true, duplicate: false, work_id: workId, request_id, intent, heard: text };

    if (intent === 'request') {
      await call('create_work', [workId, 'request', instruction, request_id, '']);
      const heard = instruction !== text ? `\n🎙️ Heard: "${text}"` : '';
      const [, receipt, router] = await Promise.all([
        call('log_event', [person, `request ${request_id}: ${instruction}`]),
        notify(person, `📥 Got your request: ${instruction}${heard}`),
        enqueueRouter(workId, person),
      ]);
      console.log(`glasses: created ${workId} for ${person}, receipt ${receipt}, router ${router}`);
      return json(200, { ...base, instruction, receipt, router });
    }

    await call('create_work', [workId, intent, text, request_id, '']);
    if (intent === 'unclear') {
      await call('set_work_status', [workId, 'unclear']);
      const receipt = await notify(person, `🤔 Didn't get that: "${text}"${note ? ` (${note})` : ''}. Try again.`);
      return json(200, { ...base, note, receipt });
    }

    const decision = await decide(intent, person);
    await call('set_work_status', [workId, 'done']);
    await call('log_event', [person, `${intent} by voice: ${decision.result} ${decision.proposal_id ?? ''}`]);
    return json(200, { ...base, ...decision });
  } catch (e) {
    console.error('glasses:', e);
    const status = e instanceof StdbError && e.status === 500 ? 500 : 502;
    return json(status, { error: e instanceof Error ? e.message : String(e) });
  }
}

/** Voice approve / reject of the newest pending plan. Only people in the `people` table can decide. */
async function decide(
  intent: 'approve' | 'reject',
  person: string
): Promise<{ result: string; proposal_id?: string; receipt: string }> {
  const plan = await latestPending();
  if (!plan) {
    const receipt = await notify(person, `🤷 Nothing to ${intent}: there's no pending plan.`);
    return { result: 'nothing_pending', receipt };
  }
  if (intent === 'approve') {
    return approveFrom('glasses', plan.id, person);
  }
  const name = await nameOf(person);
  if (!name) {
    return { result: 'not_registered', proposal_id: plan.id, receipt: await notify(person, `🚫 ${person} isn't registered.`) };
  }
  const result = await reject(plan.id, person, 'glasses');
  if (result === 'already') {
    return { result, proposal_id: plan.id, receipt: await notify(person, `Already decided: ${plan.summary}`) };
  }
  const receipt = (await updatePlanMessage(plan.id, `❌ Rejected from the glasses (${name})`))
    ? 'edited'
    : await notify(person, `❌ Rejected: ${plan.summary}`);
  return { result, proposal_id: plan.id, receipt };
}

/** approve_proposal (with `via`) + execute queued + the plan's Telegram message edited. */
async function approveFrom(
  via: Via,
  proposalId: string,
  person: string
): Promise<{ result: string; proposal_id: string; receipt: string }> {
  const name = await nameOf(person);
  if (!name) {
    return { result: 'not_registered', proposal_id: proposalId, receipt: await notify(person, `🚫 ${person} isn't registered to approve plans.`) };
  }
  const exists = await sql(`SELECT id FROM proposals WHERE id = '${proposalId}'`);
  if (exists.length === 0) {
    return { result: 'not_found', proposal_id: proposalId, receipt: 'none' };
  }
  const result = await approve(proposalId, person, via);
  if (result === 'already') {
    return { result, proposal_id: proposalId, receipt: 'none' };   // the plan message already says how it went
  }
  const line =
    result === 'approved'
      ? `✅ Approved from ${VIA_LABEL[via]} (${name}), executing…`
      : `✅ Approved from ${VIA_LABEL[via]} (${name}), but the execution couldn't be queued`;
  const receipt = (await updatePlanMessage(proposalId, line)) ? 'edited' : await notify(person, line);
  return { result, proposal_id: proposalId, receipt };
}

async function nameOf(person: string): Promise<string | null> {
  const [row] = await sql(`SELECT name FROM people WHERE id = '${person}'`);
  return row ? String(row[0]) : null;
}

/** Telegram message to the person's chat (people table). */
async function notify(person: string, message: string): Promise<'sent' | 'no_chat' | 'failed'> {
  try {
    const rows = await sql(`SELECT telegram_chat_id FROM people WHERE id = '${person}'`);
    const chatId = rows[0]?.[0];
    if (typeof chatId !== 'string' || !chatId) {
      return 'no_chat';
    }
    await send(chatId, message);
    return 'sent';
  } catch (e) {
    console.error('glasses: Telegram message failed:', e);
    return 'failed';
  }
}

async function enqueueRouter(workId: string, person: string): Promise<'queued' | 'failed'> {
  try {
    const { jobId } = await agentRuns.push({ body: { type: 'router', work_id: workId, person } });
    console.log(`glasses: queued ${workId} on ${QUEUE_KEY} (job ${jobId})`);
    return 'queued';
  } catch (e) {
    console.error('glasses: queue push failed:', e);
    return 'failed';
  }
}

/** Returns the request, or an error message for a 400. */
function parse(body: string): GlassesRequest | string {
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(body || '');
  } catch {
    return 'body must be JSON';
  }
  if (data.type !== 'request' && data.type !== 'approve') {
    return 'type must be "request" or "approve"';
  }
  if (typeof data.request_id !== 'string' || !SAFE_ID.test(data.request_id)) {
    return 'request_id is required: 1-64 letters, digits, "-" or "_"';
  }
  const person = typeof data.person === 'string' && data.person.trim() ? data.person.trim() : 'unknown';
  if (!SAFE_ID.test(person)) {
    return 'person must be 1-64 letters, digits, "-" or "_" (the id in the people table)';
  }
  if (data.type === 'approve') {
    if (typeof data.proposal_id !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(data.proposal_id)) {
      return 'proposal_id is required for "approve"';
    }
    const via = data.via ?? 'glasses';
    if (via !== 'glasses' && via !== 'panel') {
      return 'via must be "glasses" or "panel"';
    }
    return { type: 'approve', text: '', proposal_id: data.proposal_id, via, person, request_id: data.request_id };
  }
  if (typeof data.text !== 'string' || !data.text.trim()) {
    return 'text is required';
  }
  return { type: 'request', text: data.text.trim(), proposal_id: '', via: 'glasses', person, request_id: data.request_id };
}
