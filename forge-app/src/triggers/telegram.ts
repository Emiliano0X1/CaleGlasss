/**
 * `telegram` web trigger: the Telegram bot's webhook.
 *   - ✅ button (callback_query) -> approve the plan, same as "approval" in glasses.ts.
 *   - Text message              -> written request, same as "request" in glasses.ts.
 *
 * TODO (agents):
 * - [ ] Register the web trigger URL as the bot's webhook (setWebhook) with secret_token.
 * - [ ] Verify the X-Telegram-Bot-Api-Secret-Token header.
 * - [ ] Accept only the team's chat (list of allowed chat ids).
 * - [ ] Reuse the same logic as glasses.ts to create requests and approve plans.
 * - [ ] Answer the callback_query (lib/telegram.ts) so the button stops loading.
 */
import type { WebTriggerRequest, WebTriggerResponse } from './glasses';

export async function telegram(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  // TODO (agents)
  throw new Error('TODO: triggers/telegram');
}
