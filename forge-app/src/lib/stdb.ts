/**
 * Escritura del estado en SpacetimeDB (módulo en stdb/).
 *
 * Lo que se escribe aquí es lo que leen bridge/live_state.py (overlay de los
 * lentes) y dashboard/. Una fila por pedido, con su estado y el último mensaje:
 *   received -> routing -> working -> waiting_approval -> executing -> done | failed
 *
 * TODO (agentes):
 * - [ ] Acordar las tablas y reducers con stdb/.
 * - [ ] Llamar a los reducers por HTTP desde Forge (host en manifest.yml).
 * - [ ] Funciones: createRequest, setStatus(requestId, status, message), savePlan, getPlan.
 */

export type RequestStatus =
  | 'received'
  | 'routing'
  | 'working'
  | 'waiting_approval'
  | 'executing'
  | 'done'
  | 'failed';

export async function setStatus(requestId: string, status: RequestStatus, message: string): Promise<void> {
  // TODO (agentes)
  throw new Error('TODO: lib/stdb');
}
