/**
 * Router: reads the request and decides which agent(s) handle it.
 *
 *   "create a ticket / move the issue / ..."   -> jira_agent
 *   "write a summary / sprint report ..."      -> reporter
 *   ambiguous request                          -> ask for clarification (Telegram / overlay)
 *
 * TODO (agents):
 * - [ ] A single Claude call (lib/claude.ts) with structured output
 *       (output_config.format) that returns { agents: [...], tasks: [...] }.
 * - [ ] Create one { type: 'agent', jobId } job per agent on the `agent-jobs` queue.
 * - [ ] Save the decision to stdb so it shows up ("Router: Jira").
 */

export type AgentName = 'jira' | 'reporter';

export interface RouteDecision {
  agents: { agent: AgentName; task: string }[];
  clarification?: string;   // when the request isn't clear
}

export async function route(requestText: string): Promise<RouteDecision> {
  // TODO (agents)
  throw new Error('TODO: agents/router');
}
