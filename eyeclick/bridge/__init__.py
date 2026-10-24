"""glasses-bridge: voice + agents, in the same process as EyeClick.

    listener.py      -> bus subscriber; the blink gesture turns the microphone on/off
    stt.py           -> audio -> text with faster-whisper (local)
    forge_client.py  -> POSTs the text to forge-app's `glasses` web trigger
    live_state.py    -> reads the state in SpacetimeDB and updates the overlay

None of this blocks the main thread: recording, transcribing, sending and reading
SpacetimeDB run on their own threads (see README, "Agent team").
"""
