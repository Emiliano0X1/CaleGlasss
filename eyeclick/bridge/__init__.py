"""glasses-bridge: voz + agentes, en el mismo proceso que EyeClick.

    listener.py      -> suscriptor del bus; el gesto de parpadeo prende/apaga el micrófono
    stt.py           -> audio -> texto con faster-whisper (local)
    forge_client.py  -> POST del texto al web trigger `glasses` de forge-app
    live_state.py    -> lee el estado en SpacetimeDB y actualiza el overlay

Nada de esto bloquea el hilo principal: grabar, transcribir, enviar y leer
SpacetimeDB corren en sus propios hilos (ver README, "Agent team").
"""
