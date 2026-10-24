/**
 * Runs an approved plan: one function per action type.
 *
 * This is the only place where things change in Jira, Confluence or Telegram. Each
 * action writes its result to stdb ("Ticket PROJ-12 created ✓") for the overlay and dashboard.
 *
 * TODO (agents):
 * - [ ] Implement each action with lib/jira.ts, lib/confluence.ts and lib/telegram.ts.
 * - [ ] Run them in order; if one fails, stop and mark the plan 'failed' with the error.
 * - [ ] Never run the same plan twice (idempotent by planId).
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
  // TODO (agents)
  throw new Error('TODO: execute/actions');
}
