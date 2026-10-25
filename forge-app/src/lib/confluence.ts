/**
 * Confluence REST calls from Forge, as the app (api.asApp().requestConfluence).
 *
 * Reads (the reporter's tools and its propose() checks, agents/reporter.ts):
 *   searchPages(cql)              GET /wiki/rest/api/search            (CQL only exists in v1)
 *   getPage(id)                   GET /wiki/api/v2/pages/{id}           body in storage format
 *   getSpace(key)                 GET /wiki/api/v2/spaces?keys=KEY
 *   pageByTitle(spaceId, title)   GET /wiki/api/v2/pages?space-id=&title=
 * Write (only execute/actions.ts, after approval):
 *   createPage(...)               POST /wiki/api/v2/pages               body in storage format
 *
 * Scopes (manifest.yml): read:page:confluence, write:page:confluence, read:space:confluence,
 * search:confluence. The app must also be installed on Confluence (forge install --product confluence).
 */
import api, { route } from '@forge/api';
import { siteUrl } from './jira';

export class ConfluenceError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export interface PageSummary {
  id: string;
  title: string;
  space_key: string;
  excerpt: string;
}

export interface Page {
  id: string;
  title: string;
  space_id: string;
  parent_id: string | null;
  body: string;           // storage format (XHTML)
}

export interface Space {
  id: string;
  key: string;
  name: string;
}

/** CQL search for pages, e.g. title = "Sprint reports" or ancestor = 123. Up to `max` results. */
export async function searchPages(cql: string, max = 25): Promise<PageSummary[]> {
  const query = `type = page AND (${cql})`;
  const data = await get(route`/wiki/rest/api/search?cql=${query}&limit=${String(max)}&expand=content.space`);
  return (data.results ?? []).map((r: SearchResult) => ({
    id: String(r.content?.id ?? ''),
    title: r.content?.title ?? r.title ?? '',
    space_key: r.content?.space?.key ?? r.resultGlobalContainer?.title ?? '',
    excerpt: (r.excerpt ?? '').replace(/@@@(end)?hl@@@/g, '').slice(0, 300),
  }));
}

export async function getPage(id: string): Promise<Page> {
  const data = await get(route`/wiki/api/v2/pages/${id}?body-format=storage`);
  return {
    id: String(data.id),
    title: data.title,
    space_id: String(data.spaceId),
    parent_id: data.parentId ? String(data.parentId) : null,
    body: data.body?.storage?.value ?? '',
  };
}

/** The space with that key, or null. */
export async function getSpace(key: string): Promise<Space | null> {
  const data = await get(route`/wiki/api/v2/spaces?keys=${key}`);
  const space = data.results?.[0];
  return space ? { id: String(space.id), key: space.key, name: space.name } : null;
}

/** Id of the current page with exactly that title in the space, or null (Confluence titles are unique per space). */
export async function pageByTitle(spaceId: string, title: string): Promise<string | null> {
  const data = await get(route`/wiki/api/v2/pages?space-id=${spaceId}&title=${title}&status=current`);
  const page = data.results?.[0];
  return page ? String(page.id) : null;
}

/** Creates a page under `parentId`; returns its id and the link to open it. */
export async function createPage(spaceId: string, parentId: string, title: string, storage: string): Promise<{ id: string; url: string }> {
  const res = await api.asApp().requestConfluence(route`/wiki/api/v2/pages`, {
    method: 'POST',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    body: JSON.stringify({
      spaceId,
      parentId,
      status: 'current',
      title,
      body: { representation: 'storage', value: storage },
    }),
  });
  if (!res.ok) {
    throw new ConfluenceError(`Confluence POST /pages ${res.status}: ${(await res.text()).slice(0, 300)}`, res.status);
  }
  const data = await res.json();
  const base = data._links?.base ?? `${await siteUrl()}/wiki`;   // _links.base: https://<site>/wiki
  return { id: String(data.id), url: `${base}${data._links?.webui ?? `/pages/viewpage.action?pageId=${data.id}`}` };
}

interface SearchResult {
  title?: string;
  excerpt?: string;
  content?: { id?: string; title?: string; space?: { key?: string } };
  resultGlobalContainer?: { title?: string };
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function get(path: ReturnType<typeof route>): Promise<any> {
  const res = await api.asApp().requestConfluence(path, { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    throw new ConfluenceError(`Confluence GET ${path.value.split('?')[0]} ${res.status}: ${(await res.text()).slice(0, 300)}`, res.status);
  }
  return res.json();
}
