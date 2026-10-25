/**
 * Router: splits a request into work items, one per agent, and queues each one.
 *
 *   "move what's left to sprint 13"                -> [jira]
 *   "write the sprint 12 report"                   -> [reporter]
 *   "move what's left to 13 and write the report"  -> [jira, reporter (depends_on the jira one)]
 *
 * route(text): one Claude call (FAST_MODEL, no thinking) forced to use its only tool,
 * create_work_items(items). Each item: type ('jira' | 'reporter'), text (a self-contained
 * instruction) and depends_on (number of an earlier item, 0 = none). If Claude fails or
 * returns nothing usable, the whole request becomes one Jira item: a request is never lost here.
 *
 * routeWork({ work_id, person }): the queue's { type: 'router' } event (queue/consumer.ts),
 * pushed by triggers/glasses.ts. The request's own work item (w-<request_id>, type 'request')
 * stays as the parent:
 *   1. route() its text
 *   2. create_work for each item: id w-<request_id>-<n>, request_id <request_id>-<n>, so a
 *      retried event doesn't duplicate them; depends_on is the id of the earlier item
 *   3. set_work_status(parent, 'routed'); a retry that finds it routed stops here
 *   4. { type: 'agent', work_id } to the queue for each item. An item whose dependency isn't
 *      done is dropped by claim_work and stays pending; queue/consumer.ts queues it again when
 *      the plan it depends on is done.
 */
import { Queue } from '@forge/events';
import { createMessage, FAST_MODEL } from '../lib/claude';
import { PROJECT_KEY } from '../lib/jira';
import { call, sql } from '../lib/stdb';
import { heartbeat } from './loop';
import { QUEUE_KEY, type AgentRun } from '../queue/consumer';

export const ROUTER_NAME = 'router';
export const AGENT_TYPES = ['jira', 'reporter'] as const;
export type AgentType = (typeof AGENT_TYPES)[number];

export interface WorkItemPlan {
  type: AgentType;
  text: string;
  depends_on: number;   // 1-based number of an earlier item, 0 = none
}

const MAX_ITEMS = 5;
const TOOL = 'create_work_items';

const SYSTEM = `You route requests for a team assistant. Someone asked for something by voice from their smart glasses (already cleaned up into one instruction). Split it into work items for these agents and call ${TOOL} once:

- "jira": changes or lookups in Jira project ${PROJECT_KEY}: move issues between sprints, change status, assign, change priority, comment.
- "reporter": writes a report or summary (sprint report, status of an epic, someone's pending work) to share in Confluence or Telegram. It only reads Jira.

Rules:
- Most requests are a single item. Only split when the request clearly asks for separate things for different agents, or several clearly separate Jira tasks.
- Each item's text is a self-contained instruction in the language of the request: keep every concrete detail (sprint numbers, issue keys, names, priorities, statuses, comment text) and repeat any detail it needs from the rest of the request. Never add anything that wasn't asked.
- depends_on: the number (1, 2, ...) of an earlier item that must be finished first, or 0. A report that should reflect changes asked for in the same request depends on that Jira item ("move what's left to 13 and write the report" -> the report depends on item 1).
- If you're unsure, use a single "jira" item with the whole request.`;

const TOOL_DEFINITION = {
  name: TOOL,
  description: 'Create the work items for this request, in order. Later items can depend on earlier ones.',
  strict: true,
  input_schema: {
    type: 'object',
    properties: {
      items: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            type: { type: 'string', enum: [...AGENT_TYPES] },
            text: { type: 'string', description: 'Self-contained instruction for that agent' },
            depends_on: { type: 'integer', description: 'Number (1-based) of an earlier item that must be done first, or 0' },
          },
          required: ['type', 'text', 'depends_on'],
          additionalProperties: false,
        },
      },
    },
    required: ['items'],
    additionalProperties: false,
  },
};

export async function route(requestText: string): Promise<WorkItemPlan[]> {
  const single: WorkItemPlan[] = [{ type: 'jira', text: requestText, depends_on: 0 }];
  try {
    const response = await createMessage({
      model: FAST_MODEL,
      system: SYSTEM,
      messages: [{ role: 'user', content: requestText }],
      tools: [TOOL_DEFINITION],
      toolChoice: TOOL,
      effort: 'low',
      thinking: 'disabled',
      maxTokens: 2048,
    });
    const use = response.content.find((b) => b.type === 'tool_use' && b.name === TOOL);
    const items = validate(use?.input?.items);
    if (!items) {
      console.warn(`router: unusable answer for "${requestText}", using one jira item:`, use?.input);
      return single;
    }
    console.log(`router: "${requestText}" -> ${items.map((i, n) => `${n + 1}.${i.type}${i.depends_on ? `<-${i.depends_on}` : ''}`).join(' ')}`);
    return items;
  } catch (e) {
    console.error('router: Claude failed, using one jira item:', e);
    return single;
  }
}

/** The items if they make sense; null otherwise (empty, unknown type, depends_on not on an earlier item). */
function validate(raw: unknown): WorkItemPlan[] | null {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > MAX_ITEMS) {
    return null;
  }
  const items: WorkItemPlan[] = [];
  for (const [index, item] of raw.entries()) {
    const type = item?.type;
    const text = typeof item?.text === 'string' ? item.text.trim() : '';
    const dependsOn = Number(item?.depends_on ?? 0);
    if (!AGENT_TYPES.includes(type) || !text || !Number.isInteger(dependsOn) || dependsOn < 0 || dependsOn > index) {
      return null;
    }
    items.push({ type, text, depends_on: dependsOn });
  }
  return items;
}

export async function routeWork({ work_id, person }: { work_id: string; person: string }): Promise<void> {
  const [parent] = await sql(`SELECT text, status, request_id FROM work_items WHERE id = '${work_id}'`);
  if (!parent) {
    console.error(`router: ${work_id} not found in work_items`);
    return;
  }
  const [text, status, requestId] = parent.map(String);
  if (status === 'routed') {
    console.log(`router: ${work_id} was already routed, nothing to do`);
    return;
  }

  await heartbeat(ROUTER_NAME, 'routing', work_id);
  const items = await route(text);
  const ids = items.map((_, n) => `${work_id}-${n + 1}`);
  for (const [n, item] of items.entries()) {
    const dependsOn = item.depends_on ? ids[item.depends_on - 1] : '';
    await call('create_work', [ids[n], item.type, item.text, `${requestId}-${n + 1}`, dependsOn]);
  }
  await call('set_work_status', [work_id, 'routed']);
  await heartbeat(ROUTER_NAME, 'idle', '');
  await call('log_event', [ROUTER_NAME, `${work_id}: ${items.map((i, n) => `${ids[n]} ${i.type}`).join(', ')}`]);

  // After 'routed', so a failed push isn't retried by re-routing (the items already exist).
  const agentRuns = new Queue<AgentRun>({ key: QUEUE_KEY });   // here, not at import: consumer.ts imports this file
  for (const id of ids) {
    try {
      await agentRuns.push({ body: { type: 'agent', work_id: id, person } });
    } catch (e) {
      console.error(`router: queue push for ${id} failed:`, e);
    }
  }
}
