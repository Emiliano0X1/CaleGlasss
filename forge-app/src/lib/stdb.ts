/**
 * SpacetimeDB over HTTP (module in stdb/, database `agentes` on maincloud).
 *
 * What's written here is what bridge/live_state.py (glasses overlay) and dashboard/
 * read. It uses @forge/api's fetch, which only reaches the domains listed in
 * manifest.yml (permissions.external.fetch.backend: maincloud.spacetimedb.com).
 *
 *   call('create_work', [id, type, text, request_id, depends_on])
 *   sql('SELECT * FROM work_items')
 *
 * Writes authenticate with the STDB_TOKEN encrypted variable (an identity created with
 * POST /v1/identity, see stdb/README.md). STDB_HOST and STDB_DATABASE are optional overrides.
 *
 * TODO (agents):
 * - [ ] setStatus(requestId, status, message) once stdb/ has a reducer for it.
 */
import { fetch } from '@forge/api';

const HOST = process.env.STDB_HOST ?? 'https://maincloud.spacetimedb.com';
const DATABASE = process.env.STDB_DATABASE ?? 'agentes';

export type RequestStatus =
  | 'received'
  | 'routing'
  | 'working'
  | 'waiting_approval'
  | 'executing'
  | 'done'
  | 'failed';

export class StdbError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }

  /** The reducer refused the call (its SenderError, e.g. "depends on ... which isn't done"):
   *  maincloud answers those with HTTP 530. Calling again gives the same answer. */
  get rejected(): boolean {
    return this.status === 530 || (this.status >= 400 && this.status < 500);
  }
}

/** Calls a reducer. HTTP takes all its arguments as one JSON array, in order. */
export async function call(reducer: string, args: unknown[]): Promise<void> {
  const token = process.env.STDB_TOKEN;
  if (!token) {
    throw new StdbError('STDB_TOKEN is not set (forge variables set --encrypt STDB_TOKEN ...)', 500);
  }
  const res = await fetch(`${url()}/call/${reducer}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  });
  if (!res.ok) {
    throw new StdbError(`${reducer} failed: HTTP ${res.status} ${await res.text()}`, res.status);
  }
}

/** Runs a SQL query and returns the rows of the first result (each row is an array of values). */
export async function sql(query: string): Promise<unknown[][]> {
  const res = await fetch(`${url()}/sql`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: query,
  });
  if (!res.ok) {
    throw new StdbError(`sql failed: HTTP ${res.status} ${await res.text()}`, res.status);
  }
  const results = (await res.json()) as { rows: unknown[][] }[];
  return results[0]?.rows ?? [];
}

function url(): string {
  return `${HOST}/v1/database/${DATABASE}`;
}
