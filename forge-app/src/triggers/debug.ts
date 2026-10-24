/**
 * Web trigger `debug`: prueba que Forge puede leer Jira como app.
 *
 * Busca con JQL los issues de un sprint y devuelve el JSON de Jira tal cual
 * (summary, status, assignee, priority). Por defecto el Sprint 12 del seed
 * (scripts/demo_ids.txt); otro sprint con ?sprint=<id>, p. ej. ?sprint=5208.
 *
 *   forge webtrigger create -f debug-webtrigger -s one-atlas-hyek.atlassian.net -p jira -e development
 *   curl "<URL>"                 # Sprint 12
 *   curl "<URL>?sprint=5208"     # Sprint 13
 *
 * Solo para depurar: cualquiera con la URL puede leer el sprint.
 *
 * TODO (agentes):
 * - [ ] Pasar la búsqueda a lib/jira.ts (searchIssues) cuando se implemente.
 * - [ ] Quitar este web trigger (o protegerlo con un token) antes del demo.
 */
import api, { route } from '@forge/api';
import type { WebTriggerRequest, WebTriggerResponse } from './glasses';

const DEFAULT_SPRINT = '5207';   // Sprint 12 (scripts/demo_ids.txt)
const FIELDS = 'summary,status,assignee,priority';

export async function debug(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  const sprint = request.queryParameters?.sprint?.[0] ?? DEFAULT_SPRINT;
  if (!/^\d+$/.test(sprint)) {
    return json(400, { error: `sprint debe ser un número, llegó "${sprint}"` });
  }

  const jql = `sprint=${sprint}`;
  const res = await api.asApp().requestJira(route`/rest/api/3/search/jql?jql=${jql}&fields=${FIELDS}`, {
    headers: { Accept: 'application/json' },
  });
  const data = await res.json();
  console.log(`debug: sprint ${sprint} -> HTTP ${res.status}, ${data.issues?.length ?? 0} issues`);

  if (res.status === 401 || res.status === 403) {
    return json(res.status, {
      hint: 'Falta un scope: agrégalo en manifest.yml, forge deploy y forge install --upgrade',
      jira: data,
    });
  }
  return json(res.status, data);
}

function json(statusCode: number, body: unknown): WebTriggerResponse {
  return {
    statusCode,
    headers: { 'Content-Type': ['application/json'] },
    body: JSON.stringify(body),
  };
}
