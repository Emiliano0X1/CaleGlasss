/**
 * Telegram bot: send messages and approval buttons.
 *
 * TODO (agents):
 * - [ ] The bot token goes in a Forge environment variable (TELEGRAM_BOT_TOKEN).
 * - [ ] sendMessage(chatId, text) and sendApprovalRequest(chatId, plan) with ✅ / ❌ buttons
 *       (inline_keyboard with callback_data = planId).
 * - [ ] answerCallbackQuery(id) so the button stops loading.
 */

export async function sendMessage(chatId: string, text: string): Promise<void> {
  // TODO (agents)
  throw new Error('TODO: lib/telegram');
}
