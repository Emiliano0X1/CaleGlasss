/**
 * Jira REST API calls from Forge (@forge/api, requestJira).
 *
 * TODO (agents):
 * - [ ] Read (used by jira_agent.ts): searchIssues(jql), getIssue(key), listTransitions(key).
 * - [ ] Write (used by execute/actions.ts): createIssue, transitionIssue, addComment, assignIssue.
 * - [ ] Decide between asApp() and asUser() depending on who should appear as the author.
 */

export async function searchIssues(jql: string): Promise<unknown[]> {
  // TODO (agents)
  throw new Error('TODO: lib/jira');
}
