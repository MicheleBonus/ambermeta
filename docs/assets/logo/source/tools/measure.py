"""Measure the shapes of the original logo bitmap: letter boxes, the M's nodes, the drop's chain.

    python measure.py ../ambermeta_logo_original.png WORKDIR

Writes WORKDIR/measure.json and three masks of the drop (drop_filled/dark/holes.npy) for
build_svg.py. Needs numpy, opencv-python-headless, and pillow.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

SRC = Path(sys.argv[1])
S = Path(sys.argv[2])
S.mkdir(parents=True, exist_ok=True)
im = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float32)
ink = (im.mean(axis=2) < 200).astype(np.uint8)
n, cc, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
comps = sorted([i for i in range(1, n) if stats[i, 4] > 5000], key=lambda i: stats[i, 0])
names = ["drop", "m", "b", "e1", "r", "M", "e2", "t", "a"]
out = {"bbox": {k: [int(v) for v in stats[i][:4]] for k, i in zip(names, comps)}}

# M: the nodes are the blobs where the distance transform is well above the stroke half-width
M = (cc == comps[names.index("M")]).astype(np.uint8)
dt = cv2.distanceTransform(M, cv2.DIST_L2, 5)
core = (dt > dt.max() * 0.6).astype(np.uint8)
k, lab, st, cen = cv2.connectedComponentsWithStats(core, 8)
nodes = []
for j in range(1, k):
    ys, xs = np.nonzero(lab == j)
    nodes.append([float(xs.mean()), float(ys.mean()), float(dt[ys, xs].max())])
nodes.sort(key=lambda p: (p[1], p[0]))
out["M_nodes"] = nodes
x0, y0, w0, h0 = stats[comps[names.index("M")]][:4]
row = int(y0 + h0 * 0.62)
runs = np.diff(np.concatenate([[0], M[row], [0]]))
starts, ends = np.nonzero(runs == 1)[0], np.nonzero(runs == -1)[0]
out["M_vertical_runs_at_row"] = [row, [[int(s), int(e - s)] for s, e in zip(starts, ends)]]
tl = min(nodes, key=lambda p: p[0] + p[1])
mid = max([p for p in nodes if p[1] < y0 + h0 * 0.6], key=lambda p: p[1])
mx, my = (tl[0] + mid[0]) / 2, (tl[1] + mid[1]) / 2
out["M_diag_halfwidth"] = float(dt[int(my) - 3:int(my) + 4, int(mx) - 3:int(mx) + 4].max())

# drop: silhouette, white holes (highlight and chain), dark-amber shade
D = (cc == comps[0]).astype(np.uint8)
cnts, _ = cv2.findContours(D, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
filled = np.zeros_like(D)
cv2.drawContours(filled, cnts, -1, 1, -1)
holes = (filled == 1) & (D == 0)
k, lab, st, cen = cv2.connectedComponentsWithStats(holes.astype(np.uint8), 8)
out["drop_holes"] = [[int(v) for v in st[j][:5]] for j in range(1, k) if st[j][4] > 50]
H = holes.astype(np.uint8)
dth = cv2.distanceTransform(H, cv2.DIST_L2, 5)
core = (dth > dth.max() * 0.6).astype(np.uint8)
k, lab, st, cen = cv2.connectedComponentsWithStats(core, 8)
cn = []
for j in range(1, k):
    ys, xs = np.nonzero(lab == j)
    cn.append([float(xs.mean()), float(ys.mean()), float(dth[ys, xs].max())])
out["chain_nodes"] = cn
cxm = int(np.mean([c[0] for c in cn]))
ys = np.nonzero(H[:, cxm])[0]
out["chain_bar_at_x"] = [cxm, int(ys.min()), int(ys.max())]
dark = (np.abs(im[..., 0] - 0xCC) < 18) & (np.abs(im[..., 1] - 0x84) < 18) & (im[..., 2] < 60) & (filled == 1)
np.save(S / "drop_filled.npy", filled)
np.save(S / "drop_dark.npy", dark)
np.save(S / "drop_holes.npy", holes)
json.dump(out, open(S / "measure.json", "w"), indent=1)
print("wrote", S / "measure.json")
