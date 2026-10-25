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
DRAG_AT = 3.00              # desde aquí se arrastra: botón apretado hasta abrir el ojo

# --- Antirrebote y detección (SWE 1) ---
FRAMES_TO_CHANGE = 3        # frames seguidos para cambiar abierto/cerrado
LOST_FRAMES = 5             # frames 'lost' seguidos para emitir EYE_LOST

# --- Acciones (SWE 2) ---
CLICK_COOLDOWN = 0.50       # segundos sin aceptar otro clic
DOUBLE_WINDOW = 1.50        # dos clics izquierdos en menos de esto = doble clic
DOUBLE_RADIUS = 40          # ...si el cursor no se movió más de esto (px) entre los dos
DISPATCH_MS = 10            # cada cuánto el bus reparte eventos en el hilo principal
MONITOR_MS = 33             # cada cuánto el monitor redibuja (~30 FPS)

# --- Dictado (micrófono lavalier, faster-whisper en la laptop) ---
DICTATION_MODEL = "base"    # tiny / base / small: más grande = más preciso y más lento
DICTATION_LANGUAGE = "en"   # "es" para español, None = detectar (falla en frases cortas)
DICTATION_DEVICE = None     # None = micrófono predeterminado de Windows, o parte del nombre ("USBAudio")
DICTATION_SILENCE_S = 1.5   # tras hablar, este silencio termina el dictado
DICTATION_WAIT_S = 6.0      # si no se habla en este tiempo, se cancela
DICTATION_MAX_S = 30.0      # tope de una frase
DICTATION_AUTO = True       # arrancar solo al hablar con el foco en un cuadro de texto (va a preview)
DICTATION_AUTO_RMS = 0.012  # nivel mínimo de la voz de quien lleva el lavalier (ver la autoprueba)
DICTATION_PREVIEW_S = 10.0  # preview sin confirmar (parpadeo izquierdo) en este tiempo = descartar
