/**
 * Router: lee el pedido y decide qué agente(s) lo atienden.
 *
 *   "crea un ticket / mueve el issue / ..."   -> jira_agent
 *   "haz un resumen / reporte del sprint ..." -> reporter
 *   pedido ambiguo                            -> pedir aclaración (Telegram / overlay)
 *
 * TODO (agentes):
 * - [ ] Una sola llamada a Claude (lib/claude.ts) con salida estructurada
 *       (output_config.format) que devuelva { agents: [...], tasks: [...] }.
 * - [ ] Crear un trabajo { type: 'agent', jobId } por agente en la cola `agent-jobs`.
 * - [ ] Guardar la decisión en stdb para mostrarla ("Router: Jira").
 */

export type AgentName = 'jira' | 'reporter';

export interface RouteDecision {
  agents: { agent: AgentName; task: string }[];
  clarification?: string;   // si el pedido no es claro
}

export async function route(requestText: string): Promise<RouteDecision> {
  // TODO (agentes)
  throw new Error('TODO: agents/router');
}
