/**
 * Agente de Jira: prompt y herramientas.
 *
 * Herramientas de solo lectura (las ejecuta durante el loop):
 *   search_issues (JQL), get_issue, list_transitions
 * Lo que cambia cosas NO se hace aquí: va en el plan (propose_plan) y lo aplica
 * execute/actions.ts tras la aprobación:
 *   create_issue, transition_issue, add_comment, assign_issue
 *
 * TODO (agentes):
 * - [ ] System prompt: proyecto(s) permitidos, formato de los tickets, idioma.
 * - [ ] Herramientas con betaZodTool que llamen a lib/jira.ts.
 * - [ ] Exportar el AgentSpec para agents/loop.ts.
 */
import type { AgentSpec } from './loop';

export const jiraAgent: AgentSpec = {
  name: 'jira',
  system: 'TODO: prompt del agente de Jira',
  tools: [],   // TODO
};
