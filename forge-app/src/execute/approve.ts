/**
 * Approving or rejecting a proposal, the same for the button (triggers/telegram.ts) and
 * for voice (triggers/glasses.ts, "approve" / "reject").
 *
 *   approve(id, person, via)   approve_proposal in stdb, then { type: 'execute' } to the queue
 *   reject(id, person, via)    reject_proposal; nothing changes in Jira
 *   latestPending()            the newest pending proposal: what "approve" by voice refers to
 *   updatePlanMessage(id, line) edits the plan's Telegram message (plan_messages): adds the
 *                              line and drops the ✅ button. false if the message isn't known
 *
 * stdb only accepts pending proposals, so approving twice (two taps, a tap and a voice
 * "approve", a retry) runs the plan once: the second one gets 'already'.
 */
import { Queue } from '@forge/events';
import { QUEUE_KEY, type QueueEvent } from '../queue/consumer';
import { call, sql, StdbError } from '../lib/stdb';
import { editMessage } from '../lib/telegram';

const agentRuns = new Queue<QueueEvent>({ key: QUEUE_KEY });

export type ApprovalResult = 'approved' | 'already' | 'queue_failed';

export async function approve(proposalId: string, person: string, via: string): Promise<ApprovalResult> {
  try {
    await call('approve_proposal', [proposalId, person, via]);
  } catch (e) {
    if (e instanceof StdbError && e.message.includes('already approved')) {
      console.log(`approve: ${proposalId} was already approved, nothing queued`);
      return 'already';
    }
    throw e;
  }
  console.log(`approve: ${proposalId} approved by ${person} via ${via}`);
  try {
    await agentRuns.push({ body: { type: 'execute', proposal_id: proposalId } });
    return 'approved';
  } catch (e) {
    console.error(`approve: queue push for ${proposalId} failed:`, e);
    return 'queue_failed';
  }
}

export async function reject(proposalId: string, person: string, via: string): Promise<'rejected' | 'already'> {
  try {
    await call('reject_proposal', [proposalId, person, via]);
  } catch (e) {
    if (e instanceof StdbError && e.message.includes('already')) {
      return 'already';
    }
    throw e;
  }
  console.log(`reject: ${proposalId} rejected by ${person} via ${via}`);
  return 'rejected';
}

/** Newest pending proposal (by its work item's created_at), or null if there's none. */
export async function latestPending(): Promise<{ id: string; summary: string } | null> {
  const proposals = await sql(`SELECT id, work_id, summary FROM proposals WHERE status = 'pending'`);
  if (proposals.length === 0) {
    return null;
  }
  const works = await sql(`SELECT id, created_at FROM work_items WHERE status = 'proposed'`);
  const createdAt = new Map(works.map(([id, at]) => [String(id), timestamp(at)]));
  const [newest] = proposals
    .map(([id, workId, summary]) => ({ id: String(id), summary: String(summary), at: createdAt.get(String(workId)) ?? 0 }))
    .sort((a, b) => b.at - a.at);
  return { id: newest.id, summary: newest.summary };
}

export async function updatePlanMessage(proposalId: string, line: string): Promise<boolean> {
  const [row] = await sql(`SELECT chat_id, message_id, text FROM plan_messages WHERE proposal_id = '${proposalId}'`);
  if (!row) {
    return false;
  }
  try {
    await editMessage(String(row[0]), Number(row[1]), `${row[2]}\n\n${line}`);
    return true;
  } catch (e) {
    console.error(`approve: editing the plan message of ${proposalId} failed:`, e);
    return false;
  }
}

/** stdb's SQL over HTTP returns a timestamp as [microseconds since the epoch]. */
function timestamp(value: unknown): number {
  return Number(Array.isArray(value) ? value[0] : value) || 0;
}
