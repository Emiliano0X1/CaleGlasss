/**
 * Cliente de Claude (SDK oficial @anthropic-ai/sdk).
 *
 * TODO (agentes):
 * - [ ] npm install @anthropic-ai/sdk zod
 * - [ ] La API key va en una variable de entorno de Forge
 *       (`forge variables set --encrypt ANTHROPIC_API_KEY ...`), nunca en el repo.
 * - [ ] Crear el cliente: new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY }).
 * - [ ] Fijar effort explícito (output_config.effort): en claude-opus-5-5 el default es 'medium'.
 * - [ ] Fallback por rechazo de seguridad: fallbacks: 'default' con el beta
 *       'server-side-fallback-2026-07-01'.
 * - [ ] Confirmar que api.anthropic.com está en permissions.external.fetch de manifest.yml.
 */

export const MODEL = 'claude-opus-5-5';

export function getClient(): never {
  // TODO (agentes)
  throw new Error('TODO: lib/claude');
}
