/**
 * Consumer of the `agent-jobs` queue: one job per step, so a Forge function
 * never runs past its time limit.
 *
 *   { type: 'route',   requestId } -> agents/router.ts picks the agent(s) and enqueues 'agent'
 *   { type: 'agent',   jobId }     -> runs jira_agent or reporter; leaves a plan waiting for approval
 *   { type: 'execute', planId }    -> execute/actions.ts applies the approved plan
 *
 * Each step writes its state to SpacetimeDB (lib/stdb.ts) so the glasses overlay
 * (bridge/live_state.py) and the dashboard see it live.
 *
 * TODO (agents):
 * - [ ] @forge/resolver resolver with resolver.define('job', ...) (method `job` in manifest.yml)
 *       exported as `consumer = resolver.getDefinitions()`.
 * - [ ] Dispatch on job.type; errors -> 'failed' state in stdb, no endless retries.
 * - [ ] Notify through Telegram when a plan is waiting for approval.
 */

export type Job =
  | { type: 'route'; requestId: string }
  | { type: 'agent'; jobId: string }
  | { type: 'execute'; planId: string };

export async function handleJob(job: Job): Promise<void> {
  // TODO (agents)
  throw new Error(`TODO: queue/consumer (${job.type})`);
}

// TODO (agents): replace with @forge/resolver's resolver.getDefinitions().
export const consumer = async (event: { payload: Job }): Promise<void> => handleJob(event.payload);
