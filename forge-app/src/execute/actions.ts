/**
 * Ejecuta un plan ya aprobado: una función por tipo de acción.
 *
 * Solo aquí se cambian cosas en Jira, Confluence o Telegram. Cada acción escribe
 * su resultado en stdb ("Ticket PROJ-12 creado ✓") para el overlay y el dashboard.
 *
 * TODO (agentes):
 * - [ ] Implementar cada acción con lib/jira.ts, lib/confluence.ts y lib/telegram.ts.
 * - [ ] Ejecutar en orden; si una falla, parar y marcar el plan como 'failed' con el error.
 * - [ ] No ejecutar dos veces el mismo plan (idempotencia por planId).
 */

export type ActionType =
  | 'create_issue'
  | 'transition_issue'
  | 'add_comment'
  | 'assign_issue'
  | 'create_page'
  | 'update_page'
  | 'send_message';

export type ActionHandler = (input: Record<string, unknown>) => Promise<string>;

export const actions: Record<ActionType, ActionHandler> = {
  create_issue: async () => { throw new Error('TODO: create_issue'); },
  transition_issue: async () => { throw new Error('TODO: transition_issue'); },
  add_comment: async () => { throw new Error('TODO: add_comment'); },
  assign_issue: async () => { throw new Error('TODO: assign_issue'); },
  create_page: async () => { throw new Error('TODO: create_page'); },
  update_page: async () => { throw new Error('TODO: update_page'); },
  send_message: async () => { throw new Error('TODO: send_message'); },
};

export async function executePlan(planId: string): Promise<void> {
  // TODO (agentes)
  throw new Error('TODO: execute/actions');
}
