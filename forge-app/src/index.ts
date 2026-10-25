// forge-app entry point: manifest.yml points at these handlers (index.<name>).
//
//   handler   -> resolvers/index.ts    issue panel resolver
//   debug     -> triggers/debug.ts     web trigger that reads a sprint with JQL
//   glasses   -> triggers/glasses.ts   requests from the glasses: stdb + receipt + queue
//   telegram  -> triggers/telegram.ts  Telegram bot webhook (buttons, messages)
//   consume   -> queue/consumer.ts     `agent-runs` queue consumer: run the agent / execute an approved plan

export { handler } from './resolvers';
export { debug } from './triggers/debug';
export { glasses } from './triggers/glasses';
export { telegram } from './triggers/telegram';
export { consume } from './queue/consumer';
