// forge-app entry point: manifest.yml points at these handlers (index.<name>).
//
//   handler   -> resolvers/index.ts    issue panel resolver (active)
//   debug     -> triggers/debug.ts     web trigger that reads a sprint with JQL (active)
//   glasses   -> triggers/glasses.ts   voice requests and approvals from the glasses
//   telegram  -> triggers/telegram.ts  ✅ button and written requests
//   consumer  -> queue/consumer.ts     dispatches the jobs: router, agent, execute
//
// glasses, telegram and consumer are still commented out in manifest.yml.

export { handler } from './resolvers';
export { debug } from './triggers/debug';
export { glasses } from './triggers/glasses';
export { telegram } from './triggers/telegram';
export { consumer } from './queue/consumer';
