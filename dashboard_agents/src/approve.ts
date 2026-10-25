/**
 * The panel's Approve button: the same `approve` the glasses send
 * (forge-app/src/triggers/glasses.ts), with via "panel".
 *
 *   POST <VITE_GLASSES_WEBTRIGGER_URL>
 *   x-secret: <VITE_APPROVAL_SECRET>
 *   { "type": "approve", "proposal_id": "p-...", "person": "<VITE_PERSON_ID>", "request_id": "<uuid>", "via": "panel" }
 *
 * glasses.ts answers CORS (OPTIONS preflight + Access-Control-Allow-Origin), so the browser
 * can call it. The result shows up in the panel by itself: the proposal leaves `pending` in stdb.
 */
const URL = import.meta.env.VITE_GLASSES_WEBTRIGGER_URL as string | undefined
const SECRET = import.meta.env.VITE_APPROVAL_SECRET as string | undefined
const PERSON = (import.meta.env.VITE_PERSON_ID as string | undefined) || 'emiliano'

export const approveConfigured = Boolean(URL && SECRET)

/** Returns the trigger's `result` ('approved', 'already', 'not_registered', ...). Throws on HTTP errors. */
export async function approveFromPanel(proposalId: string): Promise<string> {
  if (!URL || !SECRET) {
    throw new Error('VITE_GLASSES_WEBTRIGGER_URL and VITE_APPROVAL_SECRET are missing in .env.local')
  }
  const response = await fetch(URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-secret': SECRET },
    body: JSON.stringify({
      type: 'approve',
      proposal_id: proposalId,
      person: PERSON,
      request_id: crypto.randomUUID(),
      via: 'panel',
    }),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error ?? `HTTP ${response.status}`)
  }
  return String(data.result ?? 'ok')
}
