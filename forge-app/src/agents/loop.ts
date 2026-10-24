/**
 * Loop de Claude con herramientas, compartido por jira_agent.ts y reporter.ts.
 *
 * Recibe el system prompt y las herramientas de un agente, corre el ciclo
 * (Claude pide herramienta -> se ejecuta -> se devuelve el resultado) hasta que
 * Claude termina, y devuelve el plan propuesto. Los agentes NO ejecutan acciones
 * que cambian cosas: solo leen y proponen un plan; execute/actions.ts lo aplica
 * después de la aprobación.
 *
 * TODO (agentes):
 * - [ ] Usar el Tool Runner del SDK: herramientas con betaZodTool (de
 *       '@anthropic-ai/sdk/helpers/beta/zod') y client.beta.messages.toolRunner(...),
 *       en lugar de escribir el while a mano.
 * - [ ] Herramienta final `propose_plan` (strict: true) para que el plan salga como JSON válido.
 *       Con claude-opus-5-5 no se puede forzar tool_choice: usar 'auto' y pedirlo en el prompt.
 * - [ ] Revisar stop_reason ('refusal', 'max_tokens') antes de usar la respuesta.
 * - [ ] Límite de vueltas y de tiempo (las funciones de Forge tienen tiempo máximo).
 * - [ ] Escribir el progreso en stdb ("Jira: buscando issues...") en cada herramienta.
 */

export interface AgentSpec {
  name: string;
  system: string;
  tools: unknown[];   // TODO: tipos de betaZodTool
}

export interface Plan {
  summary: string;
  actions: { type: string; input: Record<string, unknown> }[];
}

export async function runAgent(spec: AgentSpec, task: string): Promise<Plan> {
  // TODO (agentes)
  throw new Error(`TODO: agents/loop (${spec.name})`);
}
