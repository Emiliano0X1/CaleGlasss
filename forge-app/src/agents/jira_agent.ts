/**
 * Jira agent: prompt and tools. It reads Jira and proposes a plan; it never changes anything.
 *
 * Read-only tools: search_issues(jql), read_issue(key), list_transitions(key),
 * find_person(name), sprints().
 * The last tool, propose(summary, actions), validates the plan, saves it as pending in stdb
 * (submit_proposal) and sends it to Telegram as a numbered list with a ✅ Approve button
 * (callback_data ap:<proposal id>); the message is saved with save_plan_message so an approval
 * from the glasses can edit it. execute/actions.ts applies the plan after approval.
 *
 * propose rejects the plan (is_error, so Claude fixes it) if an action:
 *   - uses an issue key that no tool returned in this run, or that doesn't exist in Jira
 *   - points at a sprint that isn't active/future on the board, a transition the issue
 *     doesn't have, a person that doesn't exist, or a priority Jira doesn't know
 */
import { type AgentSpec, type AgentTool, ToolError } from './loop';
import {
  BOARD_ID,
  PROJECT_KEY,
  existingKeys,
  findPerson,
  getPerson,
  listTransitions,
  priorities,
  readIssue,
  searchIssues,
  sprints,
  type IssueSummary,
} from '../lib/jira';
import { call } from '../lib/stdb';
import { send } from '../lib/telegram';

export const AGENT_NAME = 'jira';

export const ACTION_TYPES = ['move_to_sprint', 'transition', 'assign', 'change_priority', 'comment'] as const;
export type ActionType = (typeof ACTION_TYPES)[number];

export interface PlanAction {
  type: ActionType;
  issue: string;
  sprint_id?: number;       // move_to_sprint
  transition_id?: string;   // transition
  account_id?: string;      // assign
  priority?: string;        // change_priority
  text?: string;            // comment
}

export interface JiraAgentContext {
  workId: string;
  requestText: string;
  chatId: string | null;    // where the plan goes; null = no Telegram
}

const ISSUE_KEY = /^[A-Z][A-Z0-9]+-\d+$/;
const MAX_ACTIONS = 50;

const SYSTEM = `You are the Jira agent of a team assistant. Someone asked for something by voice from their smart glasses; your job is to turn it into a plan of Jira changes for a human to approve.

Context:
- Jira project key: ${PROJECT_KEY}. Scrum board id: ${BOARD_ID}.
- The Jira site is in Spanish: tool results show issue types and statuses in Spanish (Error = bug, Historia = story, Tarea = task; "Por hacer", "En curso", "Listo"). Use status_category ("new", "indeterminate", "done") to know whether an issue is finished.
- JQL needs the English issue type names: issuetype = Bug (NOT "Error"), Story, Task. Use statusCategory instead of status names. Priorities: Crítica, Highest, High, Medium, Low, Lowest.
- Always include project = ${PROJECT_KEY} in your JQL (other projects on this site are not yours).
- JQL that works here: project = ${PROJECT_KEY} AND sprint = <sprint id> AND statusCategory != Done, issuetype = Bug, priority in (Highest, High).
- If a search returns nothing, try a broader query (e.g. drop a filter) before concluding there's nothing.

Rules:
- You NEVER execute changes. You only read with the tools and, at the end, call propose once with the plan. A person approves it later.
- Only use issue keys that appeared in the results of your tools in this conversation. Never guess or construct a key.
- Only use sprint ids from sprints(), transition ids from list_transitions(key), and account ids from find_person(name).
- If something in the request doesn't exist or is ambiguous (for example, no person with that name, or several matches), don't propose: answer in one or two short sentences, in the language of the request, saying what's missing.
- If propose returns an error, fix the plan and call propose again.

Each action has a fixed format:
- {"type": "move_to_sprint", "issue": "KEY", "sprint_id": <number>}
- {"type": "transition", "issue": "KEY", "transition_id": "<id>"}
- {"type": "assign", "issue": "KEY", "account_id": "<accountId>"}
- {"type": "change_priority", "issue": "KEY", "priority": "<priority name>"}
- {"type": "comment", "issue": "KEY", "text": "<comment>"}

The summary of propose is one sentence in the language of the request.`;

export function createJiraAgent(ctx: JiraAgentContext): AgentSpec {
  const seen = new Map<string, string>();   // issue key -> summary, from tool results this run

  const remember = <T extends IssueSummary>(issues: T[]): T[] => {
    for (const i of issues) {
      seen.set(i.key, i.summary);
    }
    return issues;
  };

  const tools: AgentTool[] = [
    {
      definition: {
        name: 'search_issues',
        description: 'Search Jira issues with JQL. Returns up to 50 issues with key, summary, type, status, status_category, priority and assignee.',
        input_schema: {
          type: 'object',
          properties: { jql: { type: 'string', description: 'JQL query, e.g. "sprint = 5207 AND statusCategory != Done"' } },
          required: ['jql'],
          additionalProperties: false,
        },
      },
      run: async ({ jql }) => {
        const issues = remember(await searchIssues(String(jql)));
        console.log(`jira agent: search_issues "${jql}" -> ${issues.length} issues`);
        return { content: issues };
      },
    },
    {
      definition: {
        name: 'read_issue',
        description: 'Read one issue by key, including its current sprint and closed sprints.',
        input_schema: {
          type: 'object',
          properties: { key: { type: 'string', description: 'Issue key, e.g. PROJ-8' } },
          required: ['key'],
          additionalProperties: false,
        },
      },
      run: async ({ key }) => {
        const issue = await readIssue(issueKey(key));
        remember([issue]);
        return { content: issue };
      },
    },
    {
      definition: {
        name: 'list_transitions',
        description: 'Transitions (status changes) available right now for an issue: id, name and target status.',
        input_schema: {
          type: 'object',
          properties: { key: { type: 'string', description: 'Issue key' } },
          required: ['key'],
          additionalProperties: false,
        },
      },
      run: async ({ key }) => ({ content: await listTransitions(issueKey(key)) }),
    },
    {
      definition: {
        name: 'find_person',
        description: 'Search Jira users by name or email. Returns active people with their account_id.',
        input_schema: {
          type: 'object',
          properties: { name: { type: 'string', description: 'Name or part of it, e.g. "Ana"' } },
          required: ['name'],
          additionalProperties: false,
        },
      },
      run: async ({ name }) => {
        const people = await findPerson(String(name));
        console.log(`jira agent: find_person "${name}" -> ${people.map((p) => p.name).join(', ') || 'nobody'}`);
        return { content: people };
      },
    },
    {
      definition: {
        name: 'sprints',
        description: `Active and future sprints of board ${BOARD_ID}: id, name and state.`,
        input_schema: { type: 'object', properties: {}, additionalProperties: false },
      },
      run: async () => ({ content: await sprints() }),
    },
    {
      definition: {
        name: 'propose',
        description:
          'Submit the final plan for human approval. Nothing is executed. Returns an error listing what to fix if the plan is invalid.',
        input_schema: {
          type: 'object',
          properties: {
            summary: { type: 'string', description: 'One sentence describing the plan' },
            actions: {
              type: 'array',
              description: 'Actions in the fixed format described in the system prompt',
              items: {
                type: 'object',
                properties: {
                  type: { type: 'string', enum: [...ACTION_TYPES] },
                  issue: { type: 'string' },
                  sprint_id: { type: 'integer' },
                  transition_id: { type: 'string' },
                  account_id: { type: 'string' },
                  priority: { type: 'string' },
                  text: { type: 'string' },
                },
                required: ['type', 'issue'],
              },
            },
          },
          required: ['summary', 'actions'],
          additionalProperties: false,
        },
      },
      run: (input) => propose(ctx, seen, input),
    },
  ];

  return { name: AGENT_NAME, system: SYSTEM, tools };
}

export function proposalId(workId: string): string {
  return `p-${workId}`;
}

async function propose(
  ctx: JiraAgentContext,
  seen: Map<string, string>,
  input: Record<string, unknown>
): Promise<{ content: unknown; done: boolean }> {
  const summary = typeof input.summary === 'string' ? input.summary.trim() : '';
  const actions = Array.isArray(input.actions) ? (input.actions as PlanAction[]) : [];
  const problems: string[] = [];
  if (!summary) problems.push('summary is empty');
  if (actions.length === 0) problems.push('actions is empty');
  if (actions.length > MAX_ACTIONS) problems.push(`at most ${MAX_ACTIONS} actions`);

  const keys = actions.map((a) => String(a?.issue ?? ''));
  const [exists, boardSprints, priorityNames] = await Promise.all([
    existingKeys(keys.filter((k) => ISSUE_KEY.test(k))),
    sprints(),
    priorities(),
  ]);
  const transitionsByIssue = new Map<string, Promise<{ id: string; to: string }[]>>();
  const lines: string[] = [];

  for (const [n, a] of actions.entries()) {
    const at = `action ${n + 1}`;
    if (!ACTION_TYPES.includes(a?.type)) {
      problems.push(`${at}: unknown type "${a?.type}"`);
      continue;
    }
    if (!ISSUE_KEY.test(String(a.issue))) {
      problems.push(`${at}: "${a.issue}" is not an issue key`);
      continue;
    }
    if (!seen.has(a.issue)) {
      problems.push(`${at}: ${a.issue} didn't come from any tool result; only use keys you saw`);
      continue;
    }
    if (!exists.has(a.issue)) {
      problems.push(`${at}: ${a.issue} doesn't exist in Jira`);
      continue;
    }
    const label = `${a.issue} (${seen.get(a.issue)})`;

    switch (a.type) {
      case 'move_to_sprint': {
        const sprint = boardSprints.find((s) => s.id === Number(a.sprint_id));
        if (!sprint) problems.push(`${at}: sprint_id ${a.sprint_id} is not an active or future sprint of the board`);
        else lines.push(`${label} → ${sprint.name}`);
        break;
      }
      case 'transition': {
        if (!transitionsByIssue.has(a.issue)) transitionsByIssue.set(a.issue, listTransitions(a.issue));
        const transition = (await transitionsByIssue.get(a.issue)!).find((t) => t.id === String(a.transition_id));
        if (!transition) problems.push(`${at}: ${a.issue} has no transition ${a.transition_id}`);
        else lines.push(`${label} → status "${transition.to}"`);
        break;
      }
      case 'assign': {
        const person = a.account_id ? await getPerson(String(a.account_id)) : null;
        if (!person) problems.push(`${at}: account_id ${a.account_id} is not a Jira user`);
        else lines.push(`${label} → assign to ${person.name}`);
        break;
      }
      case 'change_priority': {
        if (!priorityNames.includes(String(a.priority))) {
          problems.push(`${at}: priority "${a.priority}" doesn't exist (valid: ${priorityNames.join(', ')})`);
        } else lines.push(`${label} → priority ${a.priority}`);
        break;
      }
      case 'comment': {
        const text = String(a.text ?? '').trim();
        if (!text || text.length > 2000) problems.push(`${at}: comment text must be 1-2000 characters`);
        else lines.push(`${label} → comment: "${text}"`);
        break;
      }
    }
  }

  if (problems.length > 0) {
    console.log(`jira agent: plan rejected: ${problems.join('; ')}`);
    throw new ToolError(`The plan was rejected, fix these and call propose again:\n- ${problems.join('\n- ')}`);
  }

  const id = proposalId(ctx.workId);
  await call('submit_proposal', [id, ctx.workId, AGENT_NAME, summary, JSON.stringify(actions)]);
  console.log(`jira agent: proposal ${id} saved with ${actions.length} actions`);

  if (ctx.chatId) {
    const list = lines.map((l, i) => `${i + 1}. ${l}`).join('\n');
    const message = `📝 Plan for "${ctx.requestText}"\n${summary}\n\n${list}`.slice(0, 4000);
    const messageId = await send(ctx.chatId, message, [[{ text: '✅ Approve', data: `ap:${id}` }]]);
    await call('save_plan_message', [id, ctx.chatId, messageId, message]);
  }
  return { content: { ok: true, proposal_id: id, actions: actions.length }, done: true };
}

function issueKey(value: unknown): string {
  const key = String(value ?? '').trim().toUpperCase();
  if (!ISSUE_KEY.test(key)) {
    throw new ToolError(`"${value}" is not an issue key (expected something like ${PROJECT_KEY}-8)`);
  }
  return key;
}
