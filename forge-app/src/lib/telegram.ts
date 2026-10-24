/**
 * Bot de Telegram: mandar mensajes y botones de aprobación.
 *
 * TODO (agentes):
 * - [ ] El token del bot va en una variable de entorno de Forge (TELEGRAM_BOT_TOKEN).
 * - [ ] sendMessage(chatId, texto) y sendApprovalRequest(chatId, plan) con botón ✅ / ❌
 *       (inline_keyboard con callback_data = planId).
 * - [ ] answerCallbackQuery(id) para que el botón deje de cargar.
 */

export async function sendMessage(chatId: string, text: string): Promise<void> {
  // TODO (agentes)
  throw new Error('TODO: lib/telegram');
}
