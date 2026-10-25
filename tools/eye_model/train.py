"""Entrena la red chica abierto/cerrado con los videos etiquetados (dataset.py).

Desde la carpeta CaleGlasss (con los .mp4 ahí):
    pip install -r tools/eye_model/requirements-train.txt
    python tools/eye_model/dataset.py . eyes.npz                 # lee los videos y las etiquetas
    python tools/eye_model/train.py eyes.npz exp                 # qué tanto generaliza (~12 min)
    python tools/eye_model/train.py eyes.npz final eyeclick/vision/eye_model.onnx   # ~6 min
Después recalibrar en la app. IN_W/IN_H deben ser iguales a los de eyeclick/vision/model.py.
Para un video nuevo: agregarlo a VIDEOS en dataset.py con sus rangos de ojo abierto.

Aumentos: cualquier rotación (cámara de cabeza), espejos, zoom y desplazamiento (ojo a
medio cuadro / fuera del cuadro), brillo, contraste, gamma, color, desenfoque y ruido.
La normalización (media/desviación por canal de cada imagen) va DENTRO del modelo, así
la app solo le pasa el frame reducido.
"""
import math
import sys
import time

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

IN_W, IN_H = 64, 48
torch.set_num_threads(8)
rng = np.random.default_rng(0)


class EyeNet(nn.Module):
    def __init__(self):
        super().__init__()

        def block(i, o):
            return nn.Sequential(nn.Conv2d(i, o, 3, padding=1, bias=False), nn.BatchNorm2d(o), nn.ReLU())
        self.f = nn.Sequential(block(3, 16), nn.MaxPool2d(2), block(16, 32), nn.MaxPool2d(2),
                               block(32, 64), nn.MaxPool2d(2), block(64, 64))
        self.drop = nn.Dropout(0.3)
        self.fc = nn.Linear(128, 1)

    def forward(self, x):                    # x: (N, 3, H, W) en 0..255, BGR
        m = x.mean(dim=(2, 3), keepdim=True)
        s = x.std(dim=(2, 3), keepdim=True) + 4.0
        h = self.f((x - m) / s)
        h = torch.cat([h.mean(dim=(2, 3)), h.amax(dim=(2, 3))], 1)
        return self.fc(self.drop(h)).squeeze(1)      # logit de "abierto"


def augment(img):
    h, w = img.shape[:2]
    ang = rng.uniform(0, 360)
    scale = math.exp(rng.uniform(math.log(0.8), math.log(1.6)))      # >1 = zoom: ojo recortado
    cx, cy = w / 2 + rng.uniform(-0.25, 0.25) * w, h / 2 + rng.uniform(-0.25, 0.25) * h
    M = cv2.getRotationMatrix2D((cx, cy), ang, scale)
    M[:, 2] += (w / 2 - cx, h / 2 - cy)
    out = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
    if rng.random() < 0.5:
        out = out[:, ::-1]
    out = cv2.resize(out, (IN_W, IN_H), interpolation=cv2.INTER_AREA).astype(np.float32)
    out = out * rng.uniform(0.5, 1.6) + rng.uniform(-25, 25)                 # exposición
    out = out * rng.uniform(0.85, 1.15, size=3)                              # balance de color
    out = 255 * (np.clip(out, 0, 255) / 255) ** rng.uniform(0.7, 1.4)       # gamma
    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (3, 3), rng.uniform(0.3, 1.2))
    out = out + rng.normal(0, rng.uniform(0, 6), out.shape)
    return np.clip(out, 0, 255)


def plain(img):
    return cv2.resize(img, (IN_W, IN_H), interpolation=cv2.INTER_AREA).astype(np.float32)


def batch(X, idx, aug):
    arr = np.stack([augment(X[i]) if aug else plain(X[i]) for i in idx]).astype(np.float32)
    return torch.from_numpy(arr.transpose(0, 3, 1, 2).copy())


def train(X, y, epochs=30, bs=96, seed=0):
    torch.manual_seed(seed)
    net = EyeNet()
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-3)
    steps = epochs * math.ceil(len(X) / bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=steps)
    pos_w = torch.tensor((y == 0).sum() / max(1, (y == 1).sum()), dtype=torch.float32)
    yt = torch.from_numpy(y.astype(np.float32))
    for ep in range(epochs):
        net.train()
        perm = rng.permutation(len(X))
        tot = 0.0
        for k in range(0, len(X), bs):
            idx = perm[k:k + bs]
            logit = net(batch(X, idx, True))
            # pesar las clases para que "cerrado" (menos frames) cuente igual
            wts = torch.where(yt[idx] == 1, pos_w, torch.tensor(1.0))
            loss = F.binary_cross_entropy_with_logits(logit, yt[idx], weight=wts)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot += loss.item() * len(idx)
        if ep % 10 == 9 or ep == epochs - 1:
            print(f"    epoch {ep + 1}: loss {tot / len(X):.3f}", flush=True)
    return net.eval()


@torch.no_grad()
def logits(net, X):
    out = []
    for k in range(0, len(X), 256):
        out.append(net(batch(X, range(k, min(len(X), k + 256)), False)).numpy())
    return np.concatenate(out)


def load(path):
    d = np.load(path)
    return {n: (d[n + "_X"], d[n + "_y"], d[n + "_v"]) for n in ("ojo", "ojo2", "ojo3")}


def calib_cut(lg, o_rng, c_rng, k=0.4, fps=17.2):
    """Corte como en la app: entre las medianas de los frames de calibración, más cerca de cerrado."""
    step = max(1, round(fps / 10))
    o = lg[list(range(*o_rng, step))[:30]]
    c = lg[list(range(*c_rng, step))[:30]]
    lo, hi = np.median(c), np.median(o)
    return lo + k * (hi - lo), hi - lo


def clicks(status, fps=17.2):
    """Simula BlinkFSM con los estados por frame: lista de (tipo, duración)."""
    from eyeclick.events import EventType as E
    from eyeclick.logic.blink_fsm import BlinkFSM
    evs = []
    fsm = BlinkFSM(evs.append)
    for i, s in enumerate(status):
        fsm.update(s, i / fps)
    return [(e.type.name, round(e.duration, 2)) for e in evs if e.type in (E.CLICK_LEFT, E.CLICK_RIGHT)]


CAL3 = {"A": ((61, 94), (175, 210)), "B": ((264, 300), (370, 420)), "C": ((0, 50), (310, 345))}


def report(name, lg, y, v, cal_sets=None):
    acc0 = (((lg > 0) == y) & v).sum() / v.sum()
    line = f"  {name}: acc@0 {acc0:.1%}"
    if cal_sets:
        for cn, (o, c) in cal_sets.items():
            cut, sep = calib_cut(lg, o, c)
            acc = (((lg > cut) == y) & v).sum() / v.sum()
            line += f" | calib {cn} {acc:.1%} (sep {sep:.1f})"
    print(line, flush=True)


def experiments(path):
    sys.path.insert(0, ".")
    D = load(path)
    print("1) entrena ojo+ojo2, prueba ojo3 (ángulo nunca visto)")
    Xtr = np.concatenate([D["ojo"][0][D["ojo"][2]], D["ojo2"][0][D["ojo2"][2]]])
    ytr = np.concatenate([D["ojo"][1][D["ojo"][2]], D["ojo2"][1][D["ojo2"][2]]])
    t0 = time.time()
    net = train(Xtr, ytr)
    print(f"    ({time.time() - t0:.0f} s)")
    X3, y3, v3 = D["ojo3"]
    report("ojo3", logits(net, X3), y3, v3, CAL3)

    print("2) entrena ojo+ojo2+ojo3[0:300], prueba ojo3[300:] (mismo ángulo, otros parpadeos)")
    cut = 300
    m3 = v3.copy()
    m3[cut:] = False
    Xtr2 = np.concatenate([Xtr, X3[m3]])
    ytr2 = np.concatenate([ytr, y3[m3]])
    net2 = train(Xtr2, ytr2)
    lg = logits(net2, X3)
    v_test = v3.copy()
    v_test[:cut] = False
    report("ojo3[300:]", lg, y3, v_test, {"B'": ((264, 300), (175, 210))})
    st = np.where(lg > calib_cut(lg, (264, 300), (175, 210))[0], "open", "closed")
    print("    clics simulados en ojo3[300:]:", clicks(list(st[cut:])))
    print("    clics reales esperados: RIGHT(2.5 s) , cancel(3.6 s), RIGHT(2.0 s), LEFT(0.75 s)")

    print("3) entrena ojo2+ojo3, prueba ojo (cámara en la mano)")
    Xtr3 = np.concatenate([D["ojo2"][0][D["ojo2"][2]], X3[v3]])
    ytr3 = np.concatenate([D["ojo2"][1][D["ojo2"][2]], y3[v3]])
    net3 = train(Xtr3, ytr3)
    X1, y1, v1 = D["ojo"]
    report("ojo", logits(net3, X1), y1, v1)


def final(path, out):
    sys.path.insert(0, ".")
    D = load(path)
    X = np.concatenate([D[n][0][D[n][2]] for n in D])
    y = np.concatenate([D[n][1][D[n][2]] for n in D])
    net = train(X, y, epochs=40)
    for n, (Xn, yn, vn) in D.items():
        report(n + " (entrenado)", logits(net, Xn), yn, vn)
    dummy = torch.zeros(1, 3, IN_H, IN_W)
    torch.onnx.export(net, dummy, out, input_names=["bgr"], output_names=["logit_open"],
                      dynamic_axes={"bgr": {0: "n"}, "logit_open": {0: "n"}}, opset_version=17,
                      dynamo=False)
    torch.save(net.state_dict(), out.replace(".onnx", ".pt"))
    print("exportado", out)


if __name__ == "__main__":
    if sys.argv[2] == "exp":
        experiments(sys.argv[1])
    else:
        final(sys.argv[1], sys.argv[3])
