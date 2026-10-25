/**
 * Telegram bot (@caleglass_bot) over the Bot API, with @forge/api's fetch
 * (api.telegram.org is in manifest.yml's external.fetch.backend).
 *
 *   send(chatId, '📥 Got your request')                                   plain message
 *   send(chatId, 'Approve?', [[{ text: '✅', data: 'approve:p1' }, { text: '❌', data: 'reject:p1' }]])
 *   answerCallbackQuery(callbackId, 'Approved')                           stops the button's loading clock
 *   editMessage(chatId, messageId, 'Approved, executing…')                replaces the text, drops the buttons
 *
 * The bot token is the TELEGRAM_BOT_TOKEN encrypted variable. Chat ids come from the
 * `people` table in stdb (telegram_chat_id).

 */
import { fetch } from '@forge/api';

export interface Button {
  text: string;
  data: string;   // callback_data: what comes back in the webhook when it's tapped (max 64 bytes)
}

export class TelegramError extends Error {}

/** Sends a message; with buttons, one inner array per row. Returns the message_id. */
export async function send(chatId: string, text: string, buttons?: Button[][]): Promise<number> {
  const body: Record<string, unknown> = { chat_id: chatId, text };
  if (buttons?.length) {
    body.reply_markup = {
      inline_keyboard: buttons.map((row) => row.map((b) => ({ text: b.text, callback_data: b.data }))),
    };
  }
  const result = (await botApi('sendMessage', body)) as { message_id: number };
  return result.message_id;
}

/** Answers a button tap; without this Telegram keeps showing the loading clock on the button. */
export async function answerCallbackQuery(callbackQueryId: string, text?: string): Promise<void> {
  await botApi('answerCallbackQuery', { callback_query_id: callbackQueryId, ...(text ? { text } : {}) });
}

/** Replaces a message's text; without reply_markup Telegram also removes its buttons. */
export async function editMessage(chatId: string, messageId: number, text: string): Promise<void> {
  await botApi('editMessageText', { chat_id: chatId, message_id: messageId, text });
}

async function botApi(method: string, body: Record<string, unknown>): Promise<unknown> {
  const token = process.env.TELEGRAM_BOT_TOKEN;
  if (!token) {
    throw new TelegramError('TELEGRAM_BOT_TOKEN is not set (forge variables set --encrypt TELEGRAM_BOT_TOKEN ...)');
  }
  const res = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = (await res.json()) as { ok: boolean; result?: unknown; description?: string };
  if (!data.ok) {
    throw new TelegramError(`${method} failed: HTTP ${res.status} ${data.description ?? ''}`);
  }
  return data.result;
}
