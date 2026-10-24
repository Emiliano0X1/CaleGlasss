// Punto de entrada de forge-app: manifest.yml apunta a estos handlers (index.<nombre>).
//
//   handler   -> resolvers/index.ts    resolver del panel de issue (activo)
//   debug     -> triggers/debug.ts     web trigger que lee un sprint por JQL (activo)
//   glasses   -> triggers/glasses.ts   pedidos por voz y aprobaciones desde los lentes
//   telegram  -> triggers/telegram.ts  botón ✅ y pedidos escritos
//   consumer  -> queue/consumer.ts     despacha los trabajos: router, agent, execute
//
// glasses, telegram y consumer todavía están comentados en manifest.yml.

export { handler } from './resolvers';
export { debug } from './triggers/debug';
export { glasses } from './triggers/glasses';
export { telegram } from './triggers/telegram';
export { consumer } from './queue/consumer';
