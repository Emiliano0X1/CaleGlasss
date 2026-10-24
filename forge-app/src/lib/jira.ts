/**
 * Llamadas a la API REST de Jira desde Forge (@forge/api, requestJira).
 *
 * TODO (agentes):
 * - [ ] Lectura (la usa jira_agent.ts): searchIssues(jql), getIssue(key), listTransitions(key).
 * - [ ] Escritura (la usa execute/actions.ts): createIssue, transitionIssue, addComment, assignIssue.
 * - [ ] Decidir asApp() o asUser() según quién debe aparecer como autor.
 */

export async function searchIssues(jql: string): Promise<unknown[]> {
  // TODO (agentes)
  throw new Error('TODO: lib/jira');
}
