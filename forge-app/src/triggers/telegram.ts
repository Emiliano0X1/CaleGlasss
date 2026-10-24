/**
 * Web trigger `telegram`: webhook del bot de Telegram.
 *   - Botón ✅ (callback_query) -> aprobar el plan, igual que "approval" en glasses.ts.
 *   - Mensaje de texto          -> pedido escrito, igual que "request" en glasses.ts.
 *
 * TODO (agentes):
 * - [ ] Registrar la URL del web trigger como webhook del bot (setWebhook) con secret_token.
 * - [ ] Verificar el header X-Telegram-Bot-Api-Secret-Token.
 * - [ ] Aceptar solo el chat del equipo (lista de chat ids permitidos).
 * - [ ] Reusar la misma lógica que glasses.ts para crear pedidos y aprobar planes.
 * - [ ] Contestar el callback_query (lib/telegram.ts) para quitar el "cargando" del botón.
 */
import type { WebTriggerRequest, WebTriggerResponse } from './glasses';

export async function telegram(request: WebTriggerRequest): Promise<WebTriggerResponse> {
  // TODO (agentes)
  throw new Error('TODO: triggers/telegram');
}
