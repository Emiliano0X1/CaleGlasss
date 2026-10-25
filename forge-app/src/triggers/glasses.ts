/**
 * `glasses` web trigger: requests from the glasses (and, later, approvals).
 * Called by eyeclick/bridge/forge_client.py with a POST.
 *
 *   header  x-secret: <APPROVAL_SECRET>
 *   body    { "type": "request", "text": "move the pending items", "person": "me", "request_id": "r1" }
 *
 * 1. Wrong or missing x-secret -> 401 and nothing is created.
 * 2. Invalid body -> 400.
 * 3. A work item with that request_id already exists -> 200 { duplicate: true } and nothing new.
 * 4. Otherwise create_work + log_event in SpacetimeDB (lib/stdb.ts) -> 200 { work_id }.
 * 5. In parallel, so the web trigger answers fast: log_event, the receipt "📥 Got your request"
 *    to the person's Telegram chat (people table), and { type: 'agent', work_id, person } pushed
 *    to the `agent-runs` queue (queue/consumer.ts runs Claude a few seconds later).
 *    A failed receipt or push doesn't fail the request: the response says
 *    receipt: sent | no_chat | failed and agent: queued | failed.
 *
 * The work item starts with type 'request': the router (agents/router.ts) will decide
 * which agent takes it.
 *
 * TODO (agents):
 * - [ ] { "type": "approval", "plan_id": "...", "approved": true }: mark the plan and push
 *       { type: 'execute', plan_id } to the queue.
 */
import { Queue } from '@forge/events';
import { QUEUE_KEY, type AgentRun } from '../queue/consumer';
import { call, sql, StdbError } from '../lib/stdb';
import { send } from '../lib/telegram';
import { header, json, secretMatches, type WebTriggerRequest, type WebTriggerResponse } from '../lib/webtrigger';

const agentRuns = new Queue<AgentRun>({ key: QUEUE_KEY });

interface GlassesRequest {
  type: 'request';
  text: string;
  person: string;
  request_id: string;
}

const SAFE_ID = /^[A-Za-z0-9_-]{1,64}$/;   // request_id and person: also makes them safe inside SQL strings

export async function glasses(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  if (!secretMatches(header(request, 'x-secret'), process.env.APPROVAL_SECRET)) {
    return json(401, { error: 'invalid x-secret' });
  }

  const parsed = parse(request.body);
  if (typeof parsed === 'string') {
    return json(400, { error: parsed });
  }
  const { text, person, request_id } = parsed;

  try {
    const existing = await sql(`SELECT id FROM work_items WHERE request_id = '${request_id}'`);
    if (existing.length > 0) {
      console.log(`glasses: request ${request_id} already exists (${existing[0][0]})`);
      return json(200, { ok: true, duplicate: true, work_id: existing[0][0], request_id });
    }

    const workId = `w-${request_id}`;
    await call('create_work', [workId, 'request', text, request_id, '']);
    const [, receipt, agent] = await Promise.all([
      call('log_event', [person, `request ${request_id}: ${text}`]),
      sendReceipt(person, text),
      enqueueAgent(workId, person),
    ]);
    console.log(`glasses: created ${workId} for ${person}, receipt ${receipt}, agent ${agent}`);
    return json(200, { ok: true, duplicate: false, work_id: workId, request_id, receipt, agent });
  } catch (e) {
    console.error('glasses:', e);
    const status = e instanceof StdbError && e.status === 500 ? 500 : 502;
    return json(status, { error: e instanceof Error ? e.message : String(e) });
  }
}

async function sendReceipt(person: string, text: string): Promise<'sent' | 'no_chat' | 'failed'> {
  try {
    const rows = await sql(`SELECT telegram_chat_id FROM people WHERE id = '${person}'`);
    const chatId = rows[0]?.[0];
    if (typeof chatId !== 'string' || !chatId) {
      return 'no_chat';
    }
    await send(chatId, `📥 Got your request: ${text}`);
    return 'sent';
  } catch (e) {
    console.error('glasses: receipt failed:', e);
    return 'failed';
  }
}

async function enqueueAgent(workId: string, person: string): Promise<'queued' | 'failed'> {
  try {
    const { jobId } = await agentRuns.push({ body: { type: 'agent', work_id: workId, person } });
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
  if (data.type !== 'request') {
    return 'type must be "request" (approvals are not implemented yet)';
  }
  if (typeof data.text !== 'string' || !data.text.trim()) {
    return 'text is required';
  }
  if (typeof data.request_id !== 'string' || !SAFE_ID.test(data.request_id)) {
    return 'request_id is required: 1-64 letters, digits, "-" or "_"';
  }
  const person = typeof data.person === 'string' && data.person.trim() ? data.person.trim() : 'unknown';
  if (!SAFE_ID.test(person)) {
    return 'person must be 1-64 letters, digits, "-" or "_" (the id in the people table)';
  }
  return { type: 'request', text: data.text.trim(), person, request_id: data.request_id };
}
