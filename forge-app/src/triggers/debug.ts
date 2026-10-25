/**
 * `debug` web trigger: checks that Forge can read Jira as the app.
 *
 * Searches a sprint's issues with JQL and returns Jira's JSON as-is
 * (summary, status, assignee, priority). Defaults to the seed's Sprint 12
 * (scripts/demo_ids.txt); another sprint with ?sprint=<id>, e.g. ?sprint=5208.
 *
 *   forge webtrigger create -f debug-webtrigger -s one-atlas-hyek.atlassian.net -p jira -e development
 *   curl "<URL>"                 # Sprint 12
 *   curl "<URL>?sprint=5208"     # Sprint 13
 *
 * Debugging only: anyone with the URL can read the sprint.
 *
 * TODO (agents):
 * - [ ] Move the search to lib/jira.ts (searchIssues) once it's implemented.
 * - [ ] Remove this web trigger (or protect it with a token) before the demo.
 */
import api, { route } from '@forge/api';
import { json, type WebTriggerRequest, type WebTriggerResponse } from '../lib/webtrigger';

const DEFAULT_SPRINT = '5207';   // Sprint 12 (scripts/demo_ids.txt)
const FIELDS = 'summary,status,assignee,priority';

export async function debug(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  const sprint = request.queryParameters?.sprint?.[0] ?? DEFAULT_SPRINT;
  if (!/^\d+$/.test(sprint)) {
    return json(400, { error: `sprint must be a number, got "${sprint}"` });
  }

  const jql = `sprint=${sprint}`;
  const res = await api.asApp().requestJira(route`/rest/api/3/search/jql?jql=${jql}&fields=${FIELDS}`, {
    headers: { Accept: 'application/json' },
  });
  const data = await res.json();
  console.log(`debug: sprint ${sprint} -> HTTP ${res.status}, ${data.issues?.length ?? 0} issues`);

  if (res.status === 401 || res.status === 403) {
    return json(res.status, {
      hint: 'A scope is missing: add it to manifest.yml, forge deploy and forge install --upgrade',
      jira: data,
    });
  }
  return json(res.status, data);
}
