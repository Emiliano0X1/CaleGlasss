"""Etiquetas a mano de los tres videos y caché de frames pequeños para entrenar.

Abierto = rangos (inclusivos) donde se ve el ojo abierto, aunque el iris esté fuera del
cuadro. Todo lo demás es cerrado. Las etiquetas de ojo/ojo2 salen de hojas cada 4/3
frames, así que alrededor de cada cambio se ignoran MARGIN frames (no se sabe el frame
exacto). SKIP = frames dudosos (párpado a medio cerrar) que no cuentan.
"""
import sys

import cv2
import numpy as np

VIDEOS = {
    "ojo3": dict(margin=1, skip=[], open=[
        (0, 171), (212, 260), (264, 304), (348, 364), (428, 460), (495, 519), (533, 539)]),
    "ojo2": dict(margin=3, skip=[], open=[
        (0, 52), (65, 88), (116, 124), (128, 175), (203, 247), (266, 289), (341, 367), (416, 445),
        (497, 529), (533, 553), (596, 649), (710, 730), (737, 742), (767, 786)]),
    "ojo": dict(margin=4, skip=[(150, 158), (326, 330), (386, 394), (1210, 1218), (1582, 1586),
                                (1790, 1798), (2074, 2078)], open=[
        (0, 60), (96, 124), (132, 148), (160, 200), (208, 220), (256, 324), (376, 384), (396, 424),
        (432, 456), (464, 560), (600, 600), (628, 660), (668, 708), (736, 748), (764, 788), (804, 820),
        (852, 860), (868, 1028), (1052, 1056), (1064, 1076), (1112, 1288), (1360, 1476), (1484, 1580),
        (1640, 1640), (1648, 1692), (1700, 1788), (1800, 1864), (1908, 1988), (1996, 2008),
        (2032, 2040), (2060, 2072), (2092, 2108), (2116, 2164)]),
}
SIZE = (128, 96)        # caché; el modelo entrena con recortes más chicos


def labels(name, n):
    v = VIDEOS[name]
    lab = np.zeros(n, np.int64)
    valid = np.ones(n, bool)
    for a, b in v["open"]:
        lab[a:b + 1] = 1
    for a, b in v["open"]:          # el cambio real está en algún lugar a menos de margin
        valid[max(0, a - v["margin"]):a] = False
        valid[b + 1:b + 1 + v["margin"]] = False
    for a, b in v["skip"]:
        valid[a:b + 1] = False
    return lab, valid


def build(root, out):
    data = {}
    for name in VIDEOS:
        cap = cv2.VideoCapture(f"{root}/{name}.mp4")
        frames = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(cv2.resize(f, SIZE, interpolation=cv2.INTER_AREA))
        X = np.array(frames)
        lab, valid = labels(name, len(X))
        data[name + "_X"], data[name + "_y"], data[name + "_v"] = X, lab, valid
        print(name, X.shape, "open", int(lab[valid].sum()), "closed", int((1 - lab[valid]).sum()),
              "ignored", int((~valid).sum()))
    np.savez_compressed(out, **data)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
