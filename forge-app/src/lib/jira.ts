/**
 * Jira REST calls from Forge, as the app (api.asApp().requestJira).
 *
 * Reads: the Jira agent (agents/jira_agent.ts) uses them as its tools, and propose() uses
 * them to check that the plan only mentions things that exist. Each one returns a small
 * summary instead of Jira's whole JSON, to keep Claude's context short.
 *
 * Writes (moveToSprint, transitionIssue, assignIssue, setPriority, addComment): only
 * execute/actions.ts calls them, after a person approved the plan.
 *
 * Scopes (manifest.yml): read:jira-work, read:jira-user, read:sprint:jira-software,
 * read:board-scope:jira-software, read:issue:jira-software (agile issue API), write:jira-work,
 * write:sprint:jira-software.
 */
import api, { route } from '@forge/api';

export const PROJECT_KEY = 'PROJ';
export const BOARD_ID = 178;          // scripts/demo_ids.txt

export class JiraError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export interface IssueSummary {
  key: string;
  summary: string;
  type: string;
  status: string;
  status_category: string;   // 'new' | 'indeterminate' | 'done': language-independent "is it finished"
  priority: string;
  assignee: string | null;
  assignee_account_id: string | null;
}

export interface Sprint {
  id: number;
  name: string;
  state: string;
}

export interface Transition {
  id: string;
  name: string;
  to: string;
}

export interface Person {
  account_id: string;
  name: string;
}

const FIELDS = 'summary,issuetype,status,priority,assignee';

/** JQL search; up to `max` issues. */
export async function searchIssues(jql: string, max = 50): Promise<IssueSummary[]> {
  const data = await get(route`/rest/api/3/search/jql?jql=${jql}&fields=${FIELDS}&maxResults=${String(max)}`);
  return (data.issues ?? []).map(toSummary);
}

/** One issue, with its current and closed sprints. */
export async function readIssue(key: string): Promise<IssueSummary & { sprint: string | null; closed_sprints: string[] }> {
  const data = await get(route`/rest/agile/1.0/issue/${key}?fields=${FIELDS},sprint,closedSprints`);
  return {
    ...toSummary(data),
    sprint: data.fields.sprint ? `${data.fields.sprint.name} (${data.fields.sprint.id})` : null,
    closed_sprints: (data.fields.closedSprints ?? []).map((s: Sprint) => `${s.name} (${s.id})`),
  };
}

export async function listTransitions(key: string): Promise<Transition[]> {
  const data = await get(route`/rest/api/3/issue/${key}/transitions`);
  return data.transitions.map((t: { id: string; name: string; to: { name: string } }) => ({
    id: t.id,
    name: t.name,
    to: t.to.name,
  }));
}

/** Active people (no bots or apps) whose name or email matches. */
export async function findPerson(query: string): Promise<Person[]> {
  const data = await get(route`/rest/api/3/user/search?query=${query}&maxResults=20`);
  return data
    .filter((u: { accountType: string; active: boolean }) => u.accountType === 'atlassian' && u.active)
    .map((u: { accountId: string; displayName: string }) => ({ account_id: u.accountId, name: u.displayName }));
}

export async function getPerson(accountId: string): Promise<Person | null> {
  try {
    const u = await get(route`/rest/api/3/user?accountId=${accountId}`);
    return { account_id: u.accountId, name: u.displayName };
  } catch (e) {
    if (e instanceof JiraError && e.status === 404) {
      return null;
    }
    throw e;
  }
}

/** Sprints of the board: active and future ones by default; the reporter also asks for 'closed'. */
export async function sprints(boardId = BOARD_ID, state = 'active,future'): Promise<Sprint[]> {
  const data = await get(route`/rest/agile/1.0/board/${String(boardId)}/sprint?state=${state}`);
  return data.values.map((s: Sprint) => ({ id: s.id, name: s.name, state: s.state }));
}

export async function priorities(): Promise<string[]> {
  const data = await get(route`/rest/api/3/priority`);
  return data.map((p: { name: string }) => p.name);
}

/** Which of these keys exist. One request per key (in parallel): a JQL `key in (...)` with a
 *  non-existent key fails as a whole instead of skipping it, and catching made-up keys is the point. */
export async function existingKeys(keys: string[]): Promise<Set<string>> {
  const unique = [...new Set(keys)];
  const checks = await Promise.all(
    unique.map(async (key) => {
      try {
        const data = await get(route`/rest/api/3/issue/${key}?fields=summary`);
        return data.key as string;
      } catch (e) {
        if (e instanceof JiraError && (e.status === 404 || e.status === 400)) {
          return null;
        }
        throw e;
      }
    })
  );
  return new Set(checks.filter((k): k is string => k !== null));
}

/** The site's URL, e.g. https://your-site.atlassian.net (for /browse/KEY links). */
export async function siteUrl(): Promise<string> {
  const data = await get(route`/rest/api/3/serverInfo`);
  return String(data.baseUrl).replace(/\/$/, '');
}

/** Moves up to 50 issues to a sprint in one request. */
export async function moveToSprint(sprintId: number, keys: string[]): Promise<void> {
  await write('POST', route`/rest/agile/1.0/sprint/${String(sprintId)}/issue`, { issues: keys });
}

export async function transitionIssue(key: string, transitionId: string): Promise<void> {
  await write('POST', route`/rest/api/3/issue/${key}/transitions`, { transition: { id: transitionId } });
}

export async function assignIssue(key: string, accountId: string): Promise<void> {
  await write('PUT', route`/rest/api/3/issue/${key}/assignee`, { accountId });
}

export async function setPriority(key: string, priority: string): Promise<void> {
  await write('PUT', route`/rest/api/3/issue/${key}`, { fields: { priority: { name: priority } } });
}

/** Plain-text comment; the REST API v3 wants it in ADF (Atlassian Document Format). */
export async function addComment(key: string, text: string): Promise<void> {
  const paragraphs = text.split(/\n+/).map((line) => ({ type: 'paragraph', content: [{ type: 'text', text: line }] }));
  await write('POST', route`/rest/api/3/issue/${key}/comment`, { body: { type: 'doc', version: 1, content: paragraphs } });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function get(path: ReturnType<typeof route>): Promise<any> {
  const res = await api.asApp().requestJira(path, { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    throw new JiraError(`Jira GET ${path.value.split('?')[0]} ${res.status}: ${(await res.text()).slice(0, 300)}`, res.status);
  }
  return res.json();
}

async function write(method: 'POST' | 'PUT', path: ReturnType<typeof route>, body: unknown): Promise<void> {
  const res = await api.asApp().requestJira(path, {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const hint = res.status === 401 || res.status === 403 ? ' (missing a write scope? check manifest.yml and forge install --upgrade)' : '';
    throw new JiraError(`Jira ${method} ${path.value} ${res.status}${hint}: ${(await res.text()).slice(0, 300)}`, res.status);
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toSummary(issue: any): IssueSummary {
  const f = issue.fields;
  return {
    key: issue.key,
    summary: f.summary,
    type: f.issuetype?.name,
    status: f.status?.name,
    status_category: f.status?.statusCategory?.key,
    priority: f.priority?.name,
    assignee: f.assignee?.displayName ?? null,
    assignee_account_id: f.assignee?.accountId ?? null,
  };
}
