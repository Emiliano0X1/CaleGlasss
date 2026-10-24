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
 *
 * The work item starts with type 'request': the router (agents/router.ts) will decide
 * which agent takes it.
 *
 * TODO (agents):
 * - [ ] { "type": "approval", "planId": "...", "approved": true }: mark the plan and enqueue
 *       { type: 'execute', planId } on the `agent-jobs` queue.
 * - [ ] After create_work, enqueue { type: 'route', requestId } (@forge/events Queue).
 */
import { timingSafeEqual } from 'crypto';
import { call, sql, StdbError } from '../lib/stdb';

// TODO: replace with Forge's web trigger types if the SDK exports them.
export interface WebTriggerRequest {
  body: string;
  headers: Record<string, string[]>;
  queryParameters?: Record<string, string[]>;
}

export interface WebTriggerResponse {
  statusCode: number;
  headers?: Record<string, string[]>;
  body?: string;
}

interface GlassesRequest {
  type: 'request';
  text: string;
  person: string;
  request_id: string;
}

const REQUEST_ID = /^[A-Za-z0-9_-]{1,64}$/;   // also makes it safe inside the SQL string

export async function glasses(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  if (!secretMatches(request.headers['x-secret']?.[0])) {
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
    await call('log_event', [person, `request ${request_id}: ${text}`]);
    console.log(`glasses: created ${workId} for ${person}`);
    return json(200, { ok: true, duplicate: false, work_id: workId, request_id });
  } catch (e) {
    console.error('glasses:', e);
    const status = e instanceof StdbError && e.status === 500 ? 500 : 502;
    return json(status, { error: e instanceof Error ? e.message : String(e) });
  }
}

function secretMatches(given: string | undefined): boolean {
  const expected = process.env.APPROVAL_SECRET;
  if (!expected || !given) {
    return false;
  }
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
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
  if (typeof data.request_id !== 'string' || !REQUEST_ID.test(data.request_id)) {
    return 'request_id is required: 1-64 letters, digits, "-" or "_"';
  }
  const person = typeof data.person === 'string' && data.person.trim() ? data.person.trim() : 'unknown';
  return { type: 'request', text: data.text.trim(), person, request_id: data.request_id };
}

function json(statusCode: number, body: unknown): WebTriggerResponse {
  return {
    statusCode,
    headers: { 'Content-Type': ['application/json'] },
    body: JSON.stringify(body),
  };
}
