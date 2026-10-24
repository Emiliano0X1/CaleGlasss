/**
 * Writes the state to SpacetimeDB (module in stdb/).
 *
 * What's written here is what bridge/live_state.py (glasses overlay) and dashboard/
 * read. One row per request, with its status and latest message:
 *   received -> routing -> working -> waiting_approval -> executing -> done | failed
 *
 * TODO (agents):
 * - [ ] Agree on the tables and reducers with stdb/.
 * - [ ] Call the reducers over HTTP from Forge (host in manifest.yml).
 * - [ ] Functions: createRequest, setStatus(requestId, status, message), savePlan, getPlan.
 */

export type RequestStatus =
  | 'received'
  | 'routing'
  | 'working'
  | 'waiting_approval'
  | 'executing'
  | 'done'
  | 'failed';

export async function setStatus(requestId: string, status: RequestStatus, message: string): Promise<void> {
  // TODO (agents)
  throw new Error('TODO: lib/stdb');
}
