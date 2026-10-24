/**
 * Claude loop with tools, shared by jira_agent.ts and reporter.ts.
 *
 * Takes an agent's system prompt and tools, runs the cycle (Claude asks for a
 * tool -> it runs -> the result goes back) until Claude is done, and returns the
 * proposed plan. Agents do NOT run actions that change things: they only read and
 * propose a plan; execute/actions.ts applies it after approval.
 *
 * TODO (agents):
 * - [ ] Use the SDK's Tool Runner: tools with betaZodTool (from
 *       '@anthropic-ai/sdk/helpers/beta/zod') and client.beta.messages.toolRunner(...),
 *       instead of hand-writing the while loop.
 * - [ ] Final `propose_plan` tool (strict: true) so the plan comes back as valid JSON.
 *       claude-opus-5-5 doesn't allow forcing tool_choice: use 'auto' and ask for it in the prompt.
 * - [ ] Check stop_reason ('refusal', 'max_tokens') before using the response.
 * - [ ] Limit turns and time (Forge functions have a maximum run time).
 * - [ ] Write progress to stdb ("Jira: searching issues...") on every tool call.
 */

export interface AgentSpec {
  name: string;
  system: string;
  tools: unknown[];   // TODO: betaZodTool types
}

export interface Plan {
  summary: string;
  actions: { type: string; input: Record<string, unknown> }[];
}

export async function runAgent(spec: AgentSpec, task: string): Promise<Plan> {
  // TODO (agents)
  throw new Error(`TODO: agents/loop (${spec.name})`);
}
