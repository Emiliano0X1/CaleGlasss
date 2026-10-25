/**
 * Claude over the Messages API (POST /v1/messages), with @forge/api's fetch
 * (api.anthropic.com is in manifest.yml's external.fetch.backend).
 *
 *   ask(system, text)            one request, one text answer
 *   askJson(system, text, schema) one request, JSON that matches `schema` (agents/interpret.ts)
 *   createMessage({ ... })       the raw call, used by agents/loop.ts for tool use and by
 *                                agents/router.ts (one forced tool call)
 *
 * The key is the ANTHROPIC_API_KEY encrypted Forge variable, never in the code.
 * Refusal fallback is on for MODEL: if it declines for safety reasons, the API retries the same
 * request on a fallback model it picks (`fallbacks: "default"`, beta header below).
 * FAST_MODEL (Haiku, for quick classification) has no server-side fallback, so it goes without.
 *
 * TODO (agents):
 * - [ ] Consider moving to the official @anthropic-ai/sdk (typed errors, retries) if this grows.
 */
import { fetch } from '@forge/api';

export const MODEL = 'claude-sonnet-5-5';
export const FAST_MODEL = 'claude-haiku-5-5';
const API_URL = 'https://api.anthropic.com/v1/messages';
const FALLBACK_BETA = 'server-side-fallback-2026-07-01';

export type Effort = 'low' | 'medium' | 'high' | 'xhigh' | 'max';

export class ClaudeError extends Error {}

/** A content block as the API returns it. Kept whole so it can be sent back unchanged. */
export interface ContentBlock {
  type: string;                       // 'text' | 'thinking' | 'tool_use' | ...
  text?: string;
  id?: string;                        // tool_use
  name?: string;                      // tool_use
  input?: Record<string, unknown>;    // tool_use
  [key: string]: unknown;
}

export interface ToolResultBlock {
  type: 'tool_result';
  tool_use_id: string;
  content: string;
  is_error?: boolean;
}

export interface Message {
  role: 'user' | 'assistant';
  content: string | (ContentBlock | ToolResultBlock)[];
}

export interface ToolDefinition {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  strict?: boolean;
}

export interface MessagesRequest {
  model?: string;       // default MODEL
  system: string;
  messages: Message[];
  tools?: ToolDefinition[];
  toolChoice?: string;  // name of a tool Claude must call (default: Claude decides); needs thinking 'disabled'
  effort?: Effort;      // claude-sonnet-5-5 defaults to 'high'
  maxTokens?: number;
  thinking?: 'disabled';                 // skip thinking for simple, latency-sensitive calls
  jsonSchema?: Record<string, unknown>;  // structured output: the reply is JSON matching it
}

export interface MessagesResponse {
  content: ContentBlock[];
  stop_reason: string;  // 'end_turn' | 'tool_use' | 'max_tokens' | 'refusal' | ...
  stop_details?: { category?: string | null; explanation?: string } | null;
  usage?: { input_tokens: number; output_tokens: number };
}

export async function createMessage(request: MessagesRequest): Promise<MessagesResponse> {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) {
    throw new ClaudeError('ANTHROPIC_API_KEY is not set (forge variables set --encrypt ANTHROPIC_API_KEY ...)');
  }
  const model = request.model ?? MODEL;
  const fallback = model === MODEL;
  const res = await fetch(API_URL, {
    method: 'POST',
    headers: {
      'x-api-key': key,
      'anthropic-version': '2023-06-01',
      ...(fallback ? { 'anthropic-beta': FALLBACK_BETA } : {}),
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      model,
      max_tokens: request.maxTokens ?? 16000,
      ...(fallback ? { fallbacks: 'default' } : {}),
      ...(request.thinking ? { thinking: { type: request.thinking } } : {}),
      output_config: {
        effort: request.effort ?? 'medium',
        ...(request.jsonSchema ? { format: { type: 'json_schema', schema: request.jsonSchema } } : {}),
      },
      system: request.system,
      messages: request.messages,
      ...(request.tools?.length
        ? {
            tools: request.tools,
            tool_choice: request.toolChoice ? { type: 'tool', name: request.toolChoice } : { type: 'auto' },
          }
        : {}),
    }),
  });
  const data = (await res.json()) as MessagesResponse & { error?: { message: string } };
  if (!res.ok || data.error) {
    throw new ClaudeError(`HTTP ${res.status}: ${data.error?.message ?? 'unknown error'}`);
  }
  if (data.stop_reason === 'refusal') {
    throw new ClaudeError(`refused (${data.stop_details?.category ?? 'no category'})`);
  }
  return data;
}

/** Text of a reply (thinking blocks may come first with empty text: they're skipped). */
export function textOf(response: MessagesResponse): string {
  return response.content.filter((b) => b.type === 'text').map((b) => b.text ?? '').join('').trim();
}

/** One request, one answer: returns the text of Claude's reply. */
export async function ask(system: string, userText: string, effort: Effort = 'low'): Promise<string> {
  const response = await createMessage({
    system,
    messages: [{ role: 'user', content: userText }],
    effort,
    maxTokens: 2048,
  });
  const text = textOf(response);
  if (!text) {
    throw new ClaudeError(`empty reply (stop_reason: ${response.stop_reason})`);
  }
  return text;
}

/** One fast request whose reply is JSON matching `schema` (FAST_MODEL, low effort, no thinking). */
export async function askJson<T>(system: string, userText: string, schema: Record<string, unknown>): Promise<T> {
  const response = await createMessage({
    model: FAST_MODEL,
    system,
    messages: [{ role: 'user', content: userText }],
    effort: 'low',
    thinking: 'disabled',
    maxTokens: 1024,
    jsonSchema: schema,
  });
  if (response.stop_reason === 'max_tokens') {
    throw new ClaudeError('JSON reply was cut off (max_tokens)');
  }
  return JSON.parse(textOf(response)) as T;
}
