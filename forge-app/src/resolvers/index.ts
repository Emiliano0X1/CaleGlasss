/**
 * Resolver del panel de issue (src/frontend/index.jsx lo llama con invoke()).
 * Viene de la plantilla jira-issue-panel-ui-kit, pasado a TypeScript.
 *
 * TODO (agentes):
 * - [ ] Cambiar 'getText' por lo que muestre el panel: estado de los pedidos de
 *       este issue leído de stdb (lib/stdb.ts).
 */
import Resolver from '@forge/resolver';

const resolver = new Resolver();

resolver.define('getText', (req) => {
  console.log(req);
  return 'Hello, world!';
});

export const handler = resolver.getDefinitions();
