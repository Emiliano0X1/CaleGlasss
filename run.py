"""Arranque. Solo lee argumentos y llama a app.start(). Sin lógica.  (SWE 2)

Uso:
    python run.py --mock              # simulador: F8 = ojo cerrado, F9 = pausa
    python run.py --video ojo.mp4     # pipeline real sobre un video grabado
    python run.py --camera 1          # pipeline real con la cámara endoscópica
    python run.py --camera 1 --demo   # igual, con el monitor en modo demo
"""
import argparse

from eyeclick import app


def main():
    p = argparse.ArgumentParser(description="EyeClick: clics con el ojo")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", help="simulador con F8")
    mode.add_argument("--video", metavar="RUTA", help="usar un video grabado")
    mode.add_argument("--camera", type=int, metavar="N", help="índice de cámara")
    p.add_argument("--demo", action="store_true", help="monitor en modo demo")
    args = p.parse_args()
    app.start(mock=args.mock, video=args.video, camera=args.camera, demo=args.demo)


if __name__ == "__main__":
    main()
