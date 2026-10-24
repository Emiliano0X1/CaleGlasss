/**
 * Consumidor de la cola `agent-jobs`: un trabajo por paso, para no pasarse del
 * límite de tiempo de una función de Forge.
 *
 *   { type: 'route',   requestId } -> agents/router.ts decide qué agente(s) y encola 'agent'
 *   { type: 'agent',   jobId }     -> corre jira_agent o reporter; deja un plan pendiente de aprobar
 *   { type: 'execute', planId }    -> execute/actions.ts aplica el plan aprobado
 *
 * Cada paso escribe su estado en SpacetimeDB (lib/stdb.ts) para que el overlay de
 * los lentes (bridge/live_state.py) y el dashboard lo vean en vivo.
 *
 * TODO (agentes):
 * - [ ] Resolver de @forge/resolver con resolver.define('job', ...) (method `job` en manifest.yml)
 *       y exportarlo como `consumer = resolver.getDefinitions()`.
 * - [ ] Despachar por job.type; errores -> estado 'failed' en stdb, sin reintentos infinitos.
 * - [ ] Notificar por Telegram cuando un plan queda esperando aprobación.
 */

export type Job =
  | { type: 'route'; requestId: string }
  | { type: 'agent'; jobId: string }
  | { type: 'execute'; planId: string };

export async function handleJob(job: Job): Promise<void> {
  // TODO (agentes)
  throw new Error(`TODO: queue/consumer (${job.type})`);
}

// TODO (agentes): reemplazar por resolver.getDefinitions() de @forge/resolver.
export const consumer = async (event: { payload: Job }): Promise<void> => handleJob(event.payload);
