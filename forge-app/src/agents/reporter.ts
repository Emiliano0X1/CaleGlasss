/**
 * Agente reportero: prompt y herramientas.
 *
 * Junta información de Jira (y Confluence) y propone un reporte: resumen del
 * sprint, estado de un epic, pendientes de una persona, etc.
 *   Lectura: search_issues, get_page
 *   En el plan: create_page / update_page en Confluence, send_message por Telegram
 *
 * TODO (agentes):
 * - [ ] System prompt: formato del reporte, tono y longitud.
 * - [ ] Herramientas con betaZodTool que llamen a lib/jira.ts y lib/confluence.ts.
 * - [ ] Exportar el AgentSpec para agents/loop.ts.
 */
import type { AgentSpec } from './loop';

export const reporterAgent: AgentSpec = {
  name: 'reporter',
  system: 'TODO: prompt del reportero',
  tools: [],   // TODO
};
