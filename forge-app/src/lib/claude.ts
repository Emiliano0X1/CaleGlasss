/**
 * Claude client (official @anthropic-ai/sdk).
 *
 * TODO (agents):
 * - [ ] npm install @anthropic-ai/sdk zod
 * - [ ] The API key goes in a Forge environment variable
 *       (`forge variables set --encrypt ANTHROPIC_API_KEY ...`), never in the repo.
 * - [ ] Create the client: new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY }).
 * - [ ] Set effort explicitly (output_config.effort): on claude-opus-5-5 the default is 'medium'.
 * - [ ] Safety-refusal fallback: fallbacks: 'default' with the
 *       'server-side-fallback-2026-07-01' beta.
 * - [ ] Make sure api.anthropic.com is in manifest.yml's permissions.external.fetch.
 */

export const MODEL = 'claude-opus-5-5';

export function getClient(): never {
  // TODO (agents)
  throw new Error('TODO: lib/claude');
}
