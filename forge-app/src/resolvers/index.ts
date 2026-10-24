/**
 * Issue panel resolver (src/frontend/index.jsx calls it with invoke()).
 * Comes from the jira-issue-panel-ui-kit template, converted to TypeScript.
 *
 * TODO (agents):
 * - [ ] Replace 'getText' with what the panel should show: the state of this
 *       issue's requests, read from stdb (lib/stdb.ts).
 */
import Resolver from '@forge/resolver';

const resolver = new Resolver();

resolver.define('getText', (req) => {
  console.log(req);
  return 'Hello, world!';
});

export const handler = resolver.getDefinitions();
