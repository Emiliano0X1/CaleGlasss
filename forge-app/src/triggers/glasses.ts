/**
 * Web trigger `glasses`: pedidos por voz y aprobaciones desde los lentes.
 * Lo llama eyeclick/bridge/forge_client.py con un POST.
 *
 * Cuerpo esperado (acordarlo con forge_client.py):
 *   { "kind": "request", "text": "crea un ticket para ..." }
 *   { "kind": "approval", "planId": "...", "approved": true }
 *
 * TODO (agentes):
 * - [ ] Validar el cuerpo y un token compartido (header) para que nadie más dispare la app.
 * - [ ] request: crear el pedido en SpacetimeDB (lib/stdb.ts) y encolar un trabajo
 *       { type: 'route', requestId } en la cola `agent-jobs` (@forge/events Queue).
 * - [ ] approval: marcar el plan como aprobado/rechazado y encolar { type: 'execute', planId }.
 * - [ ] Responder rápido (200 con el requestId); el trabajo pesado va por la cola.
 */

// TODO: reemplazar por los tipos de web trigger de Forge si el SDK los exporta.
export interface WebTriggerRequest {
  body: string;
  headers: Record<string, string[]>;
}

export interface WebTriggerResponse {
  statusCode: number;
  headers?: Record<string, string[]>;
  body?: string;
}

export async function glasses(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  // TODO (agentes)
  throw new Error('TODO: triggers/glasses');
}
