/**
 * Claude loop with tools, shared by the agents (jira_agent.ts, later reporter.ts).
 *
 * Each turn: heartbeat -> ask Claude (with the agent's tools) -> run every tool it asked for
 * (in parallel) -> send all the results back in one user message -> repeat. The assistant
 * content goes back unchanged every turn (thinking blocks included), as the API requires.
 *
 * Stops when:
 *   - a tool says it's done (propose accepted the plan)        -> { proposed: true }
 *   - Claude answers without asking for tools (it gave up/explained) -> { proposed: false, text }
 *   - MAX_TURNS is reached or the reply is cut off              -> { proposed: false, text }
 *
 * Agents only read and propose; nothing here changes Jira. execute/actions.ts applies a plan
 * after it's approved.
 */
import { createMessage, textOf, type ContentBlock, type Message, type ToolDefinition, type ToolResultBlock } from '../lib/claude';
import { call } from '../lib/stdb';

export const MAX_TURNS = 15;

/** What a tool returns: `done` ends the loop after this turn (e.g. the plan was accepted). */
export interface ToolOutcome {
  content: unknown;
  done?: boolean;
}

export interface AgentTool {
  definition: ToolDefinition;
  run(input: Record<string, unknown>): Promise<ToolOutcome>;
}

export interface AgentSpec {
  name: string;          // 'jira': also the agent's name in stdb (claim_work, heartbeat)
  system: string;
  tools: AgentTool[];
}

export interface RunResult {
  proposed: boolean;
  turns: number;
  text: string;          // Claude's last words when it didn't propose
}

/** Error a tool throws on purpose: its message goes back to Claude as is_error so it can fix it. */
export class ToolError extends Error {}

export async function runAgent(spec: AgentSpec, task: string, workId: string): Promise<RunResult> {
  const tools = new Map(spec.tools.map((t) => [t.definition.name, t]));
  const messages: Message[] = [{ role: 'user', content: task }];

  for (let turn = 1; turn <= MAX_TURNS; turn++) {
    await heartbeat(spec.name, `turn ${turn}/${MAX_TURNS}`, workId);
    const response = await createMessage({
      system: spec.system,
      messages,
      tools: spec.tools.map((t) => t.definition),
      effort: 'medium',
    });
    messages.push({ role: 'assistant', content: response.content });

    const uses = response.content.filter((b) => b.type === 'tool_use');
    console.log(`agent ${spec.name}: turn ${turn}, stop ${response.stop_reason}, tools [${uses.map((u) => u.name).join(', ')}]`);
    if (response.stop_reason === 'max_tokens') {
      return { proposed: false, turns: turn, text: 'The reply was cut off (max_tokens).' };
    }
    if (uses.length === 0) {
      return { proposed: false, turns: turn, text: textOf(response) };
    }

    const outcomes = await Promise.all(uses.map((use) => runTool(tools, use)));
    messages.push({ role: 'user', content: outcomes.map((o) => o.block) });
    if (outcomes.some((o) => o.done)) {
      return { proposed: true, turns: turn, text: '' };
    }
  }
  return { proposed: false, turns: MAX_TURNS, text: `Stopped after ${MAX_TURNS} turns without a plan.` };
}

async function runTool(tools: Map<string, AgentTool>, use: ContentBlock): Promise<{ block: ToolResultBlock; done: boolean }> {
  const id = use.id ?? '';
  const tool = tools.get(use.name ?? '');
  if (!tool) {
    return { block: { type: 'tool_result', tool_use_id: id, content: `Unknown tool ${use.name}`, is_error: true }, done: false };
  }
  try {
    const outcome = await tool.run(use.input ?? {});
    const content = typeof outcome.content === 'string' ? outcome.content : JSON.stringify(outcome.content);
    return { block: { type: 'tool_result', tool_use_id: id, content }, done: Boolean(outcome.done) };
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    if (!(e instanceof ToolError)) {
      console.error(`agent tool ${use.name} failed:`, e);
    }
    return { block: { type: 'tool_result', tool_use_id: id, content: message, is_error: true }, done: false };
  }
}

/** A missed heartbeat must not stop the run. */
export async function heartbeat(agent: string, status: string, workId: string): Promise<void> {
  try {
    await call('heartbeat', [agent, status, workId]);
  } catch (e) {
    console.error('agent: heartbeat failed:', e);
  }
}
