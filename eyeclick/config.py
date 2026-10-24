"""Umbrales compartidos (SWE 1 + SWE 2).

Todos los números ajustables viven aquí para afinarlos en un solo lugar.
Si cambias algo, avisa al otro SWE antes de hacer merge.
"""

# --- Cámara (SWE 1) ---
CAMERA_INDEX = 1            # 0 suele ser la webcam integrada
FRAME_W, FRAME_H = 640, 480
VIEW_W, VIEW_H = 320, 240   # tamaño de la EyeView que dibuja el monitor

# --- Tiempos del cierre del ojo, en segundos (SWE 1 los usa, SWE 2 los muestra) ---
MIN_BLINK = 0.40            # menos que esto = parpadeo natural
LEFT_AT = 0.50              # desde aquí, abrir = clic izquierdo (bip 1)
RIGHT_AT = 1.20             # desde aquí, abrir = clic derecho (bip 2)
CANCEL_AT = 3.00            # desde aquí se cancela (descanso)

# --- Antirrebote y detección (SWE 1) ---
FRAMES_TO_CHANGE = 3        # frames seguidos para cambiar abierto/cerrado
LOST_FRAMES = 5             # frames 'lost' seguidos para emitir EYE_LOST

# --- Acciones (SWE 2) ---
CLICK_COOLDOWN = 0.50       # segundos sin aceptar otro clic
DISPATCH_MS = 10            # cada cuánto el bus reparte eventos en el hilo principal
MONITOR_MS = 33             # cada cuánto el monitor redibuja (~30 FPS)
