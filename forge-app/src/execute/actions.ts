/**
 * Runs an approved plan: one function per action type of agents/jira_agent.ts, plus
 * publish_page from agents/reporter.ts.
 *
 * This is the only place where things change in Jira and Confluence. queue/consumer.ts calls
 * executeActions() after start_execution; every change is written to stdb with
 * record_action (type, issue, before, after) as soon as Jira accepts it, so the overlay and
 * dashboard see it live and a failure halfway still leaves a record of what was done.
 *
 *   move_to_sprint    POST /rest/agile/1.0/sprint/{id}/issue    (consecutive moves to the same sprint go in one request)
 *   transition        POST /rest/api/3/issue/{key}/transitions
 *   assign            PUT  /rest/api/3/issue/{key}/assignee
 *   change_priority   PUT  /rest/api/3/issue/{key}               (fields.priority)
 *   comment           POST /rest/api/3/issue/{key}/comment        (body in ADF)
 *   publish_page      POST /wiki/api/v2/pages                     (Confluence, body in storage format;
 *                                                                  the change's url links to the new page)
 *
 * Actions run in plan order; the first one that fails stops the run (ExecutionError, with
 * the changes made so far). Running the same plan twice is prevented in stdb:
 * start_execution only goes from approved to executing.
 */
import type { ActionType, PlanAction } from '../agents/jira_agent';
import type { PublishPageAction } from '../agents/reporter';
import { createPage, getSpace } from '../lib/confluence';
import {
  addComment,
  assignIssue,
  getPerson,
  listTransitions,
  moveToSprint as moveIssuesToSprint,
  readIssue,
  setPriority,
  sprints,
  transitionIssue,
} from '../lib/jira';
import { call } from '../lib/stdb';

export type Action = PlanAction | PublishPageAction;

/** One change made in Jira or Confluence; also a row of the `actions` table (issue = its target). */
export interface Change {
  type: ActionType | 'publish_page';
  issue: string;          // issue key, or the page id for publish_page
  before: string;
  after: string;
  url?: string;           // publish_page: link to the new page
}

export class ExecutionError extends Error {
  constructor(message: string, readonly done: Change[]) {
    super(message);
  }
}

const MAX_ISSUES_PER_MOVE = 50;   // Jira's limit for POST /sprint/{id}/issue

export async function executeActions(proposalId: string, plan: Action[]): Promise<Change[]> {
  const done: Change[] = [];
  for (const step of steps(plan)) {
    const issues = step.map((a) => ('issue' in a ? a.issue : a.title)).join(', ');
    try {
      const changes = step[0].type === 'move_to_sprint' ? await moveToSprint(step as PlanAction[]) : [await runSingle(step[0])];
      for (const c of changes) {
        await call('record_action', [proposalId, c.type, c.issue, c.before, c.after]);
        done.push(c);
      }
      console.log(`execute: ${proposalId} ${step[0].type} ${issues} ok`);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      throw new ExecutionError(`${step[0].type} ${issues}: ${message}`, done);
    }
  }
  return done;
}

/** Groups consecutive moves to the same sprint into one step; every other action is its own step. */
function steps(plan: Action[]): Action[][] {
  const result: Action[][] = [];
  for (const action of plan) {
    const last = result[result.length - 1];
    if (
      action.type === 'move_to_sprint' &&
      last?.[0].type === 'move_to_sprint' &&
      (last[0] as PlanAction).sprint_id === action.sprint_id &&
      last.length < MAX_ISSUES_PER_MOVE
    ) {
      last.push(action);
    } else {
      result.push([action]);
    }
  }
  return result;
}

function runSingle(action: Action): Promise<Change> {
  switch (action.type) {
    case 'publish_page':
      return publishPage(action);
    case 'transition':
      return transition(action);
    case 'assign':
      return assign(action);
    case 'change_priority':
      return changePriority(action);
    case 'comment':
      return comment(action);
    default:
      throw new Error(`unknown action type ${action.type}`);
  }
}

async function moveToSprint(actions: PlanAction[]): Promise<Change[]> {
  const sprintId = Number(actions[0].sprint_id);
  const keys = actions.map((a) => a.issue);
  const [before, boardSprints] = await Promise.all([Promise.all(keys.map((k) => readIssue(k))), sprints()]);
  const sprint = boardSprints.find((s) => s.id === sprintId);
  const after = sprint ? `${sprint.name} (${sprint.id})` : `sprint ${sprintId}`;
  await moveIssuesToSprint(sprintId, keys);
  return before.map((issue) => ({ type: 'move_to_sprint', issue: issue.key, before: issue.sprint ?? 'Backlog', after }));
}

async function transition(action: PlanAction): Promise<Change> {
  const [issue, transitions] = await Promise.all([readIssue(action.issue), listTransitions(action.issue)]);
  const target = transitions.find((t) => t.id === String(action.transition_id));
  if (!target) {
    throw new Error(`transition ${action.transition_id} isn't available anymore (status is now ${issue.status})`);
  }
  await transitionIssue(action.issue, target.id);
  return { type: 'transition', issue: action.issue, before: issue.status, after: target.to };
}

async function assign(action: PlanAction): Promise<Change> {
  const [issue, person] = await Promise.all([readIssue(action.issue), getPerson(String(action.account_id))]);
  if (!person) {
    throw new Error(`account ${action.account_id} doesn't exist`);
  }
  await assignIssue(action.issue, person.account_id);
  return { type: 'assign', issue: action.issue, before: issue.assignee ?? 'Unassigned', after: person.name };
}

async function changePriority(action: PlanAction): Promise<Change> {
  const issue = await readIssue(action.issue);
  await setPriority(action.issue, String(action.priority));
  return { type: 'change_priority', issue: action.issue, before: issue.priority, after: String(action.priority) };
}

async function comment(action: PlanAction): Promise<Change> {
  const text = String(action.text ?? '');
  await addComment(action.issue, text);
  return { type: 'comment', issue: action.issue, before: '', after: text };
}

async function publishPage(action: PublishPageAction): Promise<Change> {
  const space = await getSpace(action.space);
  if (!space) {
    throw new Error(`space ${action.space} doesn't exist anymore`);
  }
  const page = await createPage(space.id, action.parent_id, action.title, action.content);
  return { type: 'publish_page', issue: page.id, before: '', after: action.title, url: page.url };
}
