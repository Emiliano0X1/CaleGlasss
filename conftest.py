# Hace que pytest pueda importar el paquete eyeclick desde la raíz.

# scripts/test_reset.py is a script (resets the demo), not a test: don't let pytest import it.
collect_ignore = ["scripts"]
