/**
 * Turns a raw voice transcript (English, from Whisper on the glasses) into something the
 * agents can act on: what the person wants (intent) and, for a request, one clean instruction.
 *
 *   "um so move everything not finished in sprint twelve to sprint thirteen please"
 *     -> { intent: 'request', instruction: 'Move every unfinished issue in Sprint 12 to Sprint 13.' }
 *   "yes go ahead"           -> { intent: 'approve' }
 *   "no cancel that"         -> { intent: 'reject' }
 *   "thank you" / noise      -> { intent: 'unclear', note: '...' }
 *
 * Called by triggers/glasses.ts before anything is created, so it uses FAST_MODEL (Haiku,
 * no thinking): about a second. If Claude fails, the transcript goes through as a request
 * unchanged, so a request is never lost because of this step.
 */
import { askJson } from '../lib/claude';
import { PROJECT_KEY } from '../lib/jira';

export type Intent = 'request' | 'approve' | 'reject' | 'unclear';

export interface Interpretation {
  intent: Intent;
  instruction: string;   // clean instruction for 'request', '' otherwise
  note: string;          // for 'unclear': why, in a few words
}

const SYSTEM = `You clean up voice commands for a Jira assistant. The person speaks English into smart glasses and Whisper transcribes it, so the text can have filler words ("um", "like", "so"), false starts, repeated words, missing punctuation and speech-to-text mistakes.

Decide the intent:
- "request": they ask for something to be done or looked up in Jira (move issues, assign, change status or priority, comment, ...).
- "approve": they confirm the plan they were just shown ("approve", "approved", "yes", "do it", "go ahead", "confirm", "sounds good").
- "reject": they turn the plan down ("reject", "no", "cancel", "don't do it", "stop").
- "unclear": noise, an incomplete sentence, small talk ("thank you", "hello"), or something that isn't a Jira request.

For "request", rewrite it as ONE clear imperative English sentence:
- Keep every concrete detail they said: sprint numbers, issue keys, people's names, priorities, statuses, comment text.
- Write numbers as digits and issue keys as ${PROJECT_KEY}-<number> ("proj fourteen", "project 14" -> ${PROJECT_KEY}-14).
- Fix obvious speech-to-text mistakes in Jira words ("spring" -> "sprint", "bucks"/"bags" -> "bugs", "jeera" -> "Jira", "a sign" -> "assign").
- Drop fillers and politeness. Never add anything they didn't say, and don't guess missing details.
For the other intents, instruction is "".
note: for "unclear", a few words on what's missing; otherwise "".`;

const SCHEMA = {
  type: 'object',
  properties: {
    intent: { type: 'string', enum: ['request', 'approve', 'reject', 'unclear'] },
    instruction: { type: 'string' },
    note: { type: 'string' },
  },
  required: ['intent', 'instruction', 'note'],
  additionalProperties: false,
};

export async function interpret(transcript: string): Promise<Interpretation> {
  try {
    const result = await askJson<Interpretation>(SYSTEM, transcript, SCHEMA);
    const instruction = result.instruction.trim();
    if (result.intent === 'request' && !instruction) {
      return { intent: 'request', instruction: transcript, note: '' };
    }
    console.log(`interpret: "${transcript}" -> ${result.intent} "${instruction}"`);
    return { ...result, instruction };
  } catch (e) {
    console.error('interpret: failed, using the transcript as a request:', e);
    return { intent: 'request', instruction: transcript, note: '' };
  }
}
