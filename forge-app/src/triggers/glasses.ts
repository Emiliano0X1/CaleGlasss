/**
 * `glasses` web trigger: voice requests and approvals from the glasses.
 * Called by eyeclick/bridge/forge_client.py with a POST.
 *
 * Expected body (agree on it with forge_client.py):
 *   { "kind": "request", "text": "create a ticket for ..." }
 *   { "kind": "approval", "planId": "...", "approved": true }
 *
 * TODO (agents):
 * - [ ] Validate the body and a shared token (header) so nobody else can trigger the app.
 * - [ ] request: create the request in SpacetimeDB (lib/stdb.ts) and enqueue a job
 *       { type: 'route', requestId } on the `agent-jobs` queue (@forge/events Queue).
 * - [ ] approval: mark the plan approved/rejected and enqueue { type: 'execute', planId }.
 * - [ ] Answer fast (200 with the requestId); the heavy work goes through the queue.
 */

// TODO: replace with Forge's web trigger types if the SDK exports them.
export interface WebTriggerRequest {
  body: string;
  headers: Record<string, string[]>;
  queryParameters?: Record<string, string[]>;
}

export interface WebTriggerResponse {
  statusCode: number;
  headers?: Record<string, string[]>;
  body?: string;
}

export async function glasses(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  // TODO (agents)
  throw new Error('TODO: triggers/glasses');
}
