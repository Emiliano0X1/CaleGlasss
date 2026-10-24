// Punto de entrada de forge-app: manifest.yml apunta a estos handlers (index.<nombre>).
//
//   glasses   -> triggers/glasses.ts   pedidos por voz y aprobaciones desde los lentes
//   telegram  -> triggers/telegram.ts  botón ✅ y pedidos escritos
//   consumer  -> queue/consumer.ts     despacha los trabajos: router, agent, execute

export { glasses } from './triggers/glasses';
export { telegram } from './triggers/telegram';
export { consumer } from './queue/consumer';
