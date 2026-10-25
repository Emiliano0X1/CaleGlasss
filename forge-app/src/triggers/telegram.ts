/**
 * `telegram` web trigger: the webhook of the @caleglass_bot bot.
 *
 * Registered once with:
 *   https://api.telegram.org/bot<TOKEN>/setWebhook?url=<TRIGGER_URL>&secret_token=<TELEGRAM_SECRET>
 *
 * 1. X-Telegram-Bot-Api-Secret-Token must equal TELEGRAM_SECRET, otherwise 401
 *    (getWebhookInfo then shows that error as the bot's last_error_message).
 * 2. Logs what arrived (message text or button callback_data): `forge logs` / `forge tunnel`.
 * 3. ✅ Approve button (callback_data ap:<proposal id>), only from someone in the `people` table:
 *      approve_proposal(id, person, 'telegram')   fails if it isn't pending -> "Already approved", nothing queued
 *      push { type: 'execute', proposal_id }      queue/consumer.ts runs the plan
 *      answer the button and edit the plan message to "Approved, executing…" (this drops the button)
 *    Any other button just gets answered, so it stops showing the loading clock.
 * Always answers 200 once the secret is valid: otherwise Telegram keeps retrying the same update.
 *
 * TODO (agents):
 * - [ ] ❌ Reject button.
 * - [ ] Text message from a registered person (people.telegram_chat_id) -> written request,
 *       same as "request" in glasses.ts.
 */
import { Queue } from '@forge/events';
import { QUEUE_KEY, type QueueEvent } from '../queue/consumer';
import { call, sql, StdbError } from '../lib/stdb';
import { answerCallbackQuery, editMessage } from '../lib/telegram';
import { header, json, secretMatches, type WebTriggerRequest, type WebTriggerResponse } from '../lib/webtrigger';

const agentRuns = new Queue<QueueEvent>({ key: QUEUE_KEY });

interface CallbackQuery {
  id: string;
  data?: string;
  from: { id: number; first_name?: string };
  message?: { message_id: number; chat: { id: number }; text?: string };
}

interface TelegramUpdate {
  update_id: number;
  message?: { chat: { id: number }; from?: { first_name?: string }; text?: string };
  callback_query?: CallbackQuery;
}

const SAFE_ID = /^[A-Za-z0-9_-]{1,80}$/;   // the proposal id goes inside a SQL string

export async function telegram(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  const given = header(request, 'X-Telegram-Bot-Api-Secret-Token');
  if (!secretMatches(given, process.env.TELEGRAM_SECRET)) {
    console.warn('telegram: rejected update with a wrong or missing secret token');
    return json(401, { error: 'invalid secret token' });
  }

  let update: TelegramUpdate;
  try {
    update = JSON.parse(request.body || '');
  } catch {
    console.warn('telegram: body is not JSON');
    return json(200, { ok: true });
  }

  const callback = update.callback_query;
  if (callback) {
    console.log(`telegram: button from ${callback.from.first_name ?? callback.from.id}: callback_data=${callback.data}`);
    const answer = callback.data?.startsWith('ap:') ? await approve(callback, callback.data.slice(3)) : 'Got it';
    try {
      await answerCallbackQuery(callback.id, answer);
    } catch (e) {
      console.error('telegram: answerCallbackQuery failed:', e);
    }
  } else if (update.message) {
    const m = update.message;
    console.log(`telegram: message from ${m.from?.first_name ?? m.chat.id} (chat ${m.chat.id}): ${m.text ?? '(no text)'}`);
  } else {
    console.log(`telegram: update ${update.update_id} of another type`);
  }
  return json(200, { ok: true });
}

/** Approves the proposal and queues its execution. Returns the text for the button's answer. */
async function approve(callback: CallbackQuery, proposalId: string): Promise<string> {
  if (!SAFE_ID.test(proposalId)) {
    return 'Unknown plan';
  }
  const [person] = await sql(`SELECT id, name FROM people WHERE telegram_chat_id = '${callback.from.id}'`);
  if (!person) {
    console.warn(`telegram: ${callback.from.id} isn't in people, can't approve ${proposalId}`);
    return "You're not registered to approve plans";
  }
  const [personId, name] = person.map(String);

  try {
    await call('approve_proposal', [proposalId, personId, 'telegram']);
  } catch (e) {
    if (e instanceof StdbError && e.message.includes('already approved')) {
      console.log(`telegram: ${proposalId} was already approved, nothing queued`);
      return 'Already approved';
    }
    console.error(`telegram: approve_proposal ${proposalId} failed:`, e);
    return "Couldn't approve the plan, try again";
  }
  console.log(`telegram: ${proposalId} approved by ${personId}`);

  let status = 'Approved, executing…';
  try {
    await agentRuns.push({ body: { type: 'execute', proposal_id: proposalId } });
  } catch (e) {
    console.error(`telegram: queue push for ${proposalId} failed:`, e);
    status = "Approved, but the execution couldn't be queued";
  }
  if (callback.message) {
    const { chat, message_id, text } = callback.message;
    try {
      await editMessage(String(chat.id), message_id, `${text ?? ''}\n\n✅ ${status} (${name})`);
    } catch (e) {
      console.error('telegram: editMessage failed:', e);
    }
  }
  return status;
}
