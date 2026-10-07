"""Rebuild the AmberMeta logo as SVG: geometric M and chain, traced drop, Kumbh Sans Bold text.

    python build_svg.py WORKDIR ../font/KumbhSans-Bold.ttf OUTDIR

WORKDIR is the folder that measure.py wrote. Writes three files into OUTDIR:
  ambermeta_logo.svg       text as outlines (renders identically everywhere)
  ambermeta_logo_text.svg  text as editable <text> (needs Kumbh Sans installed)
  ambermeta_icon.svg       the drop alone (icon, favicon)
Needs numpy, opencv-python-headless, potracer, and fonttools. A variable Kumbh Sans font file
also works; it is instantiated at weight 700.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import potrace
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

S = Path(sys.argv[1])
FONT = Path(sys.argv[2])
OUT = Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
m = json.load(open(S / "measure.json"))
AMBER, DARK, SLATE, WHITE = "#E8A00A", "#CC8404", "#243442", "#FFFFFF"


# ---------------------------------------------------------------- tracing
def trace(mask, alphamax=1.2, turdsize=20):
    bm = potrace.Bitmap(~mask.astype(bool))  # potracer fills False pixels
    plist = bm.trace(turdsize=turdsize, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY,
                     alphamax=alphamax, opticurve=True, opttolerance=0.4)
    d = []
    for curve in plist:
        p = curve.start_point
        d.append(f"M{p.x:.1f},{p.y:.1f}")
        for seg in curve.segments:
            if seg.is_corner:
                d.append(f"L{seg.c.x:.1f},{seg.c.y:.1f}L{seg.end_point.x:.1f},{seg.end_point.y:.1f}")
            else:
                d.append(f"C{seg.c1.x:.1f},{seg.c1.y:.1f} {seg.c2.x:.1f},{seg.c2.y:.1f} "
                         f"{seg.end_point.x:.1f},{seg.end_point.y:.1f}")
        d.append("Z")
    return "".join(d)


filled = np.load(S / "drop_filled.npy").astype(np.uint8)
dark = np.load(S / "drop_dark.npy").astype(np.uint8)
holes = np.load(S / "drop_holes.npy").astype(np.uint8)
k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, k5)
dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, k5)
n, lab, st, _ = cv2.connectedComponentsWithStats(dark, 8)
dark = (lab == 1 + int(np.argmax(st[1:, 4]))).astype(np.uint8)
dark = cv2.dilate(dark, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))  # past the edge; clipped below
# highlight = the upper hole (the lower hole is the chain, redrawn geometrically)
n, lab, st, _ = cv2.connectedComponentsWithStats(holes, 8)
hl = (lab == 1 + int(np.argmin(st[1:, 1]))).astype(np.uint8)

drop_d = trace(filled, alphamax=1.3)
shade_d = trace(dark, alphamax=1.3)
hl_d = trace(hl, alphamax=1.2, turdsize=5)
(c1x, c1y, r1), (c2x, c2y, r2) = sorted(m["chain_nodes"])
cy = (c1y + c2y) / 2
r_chain = 32.0
bx, by0, by1 = m["chain_bar_at_x"]
bar_h = by1 - by0 + 1

# ---------------------------------------------------------------- M
nodes = m["M_nodes"]
xl = np.mean([p[0] for p in nodes if p[0] < 1700])
xr = np.mean([p[0] for p in nodes if p[0] > 1900])
yt = np.mean([p[1] for p in nodes if p[1] < 250])
yb = np.mean([p[1] for p in nodes if p[1] > 350])
mid = [p for p in nodes if 250 < p[1] < 350][0]
xm, ym = (xl + xr) / 2, mid[1]
R_M, R_MID, W_M = 45.0, 42.5, 36.0

# ---------------------------------------------------------------- text (Kumbh Sans Bold)
font = TTFont(FONT)
if "fvar" in font:
    font = instancer.instantiateVariableFont(font, {"wght": 700, "YOPQ": 300})
gs = font.getGlyphSet()
cmap = font.getBestCmap()
upem = font["head"].unitsPerEm


def bounds(ch):
    bp = BoundsPen(gs)
    gs[cmap[ord(ch)]].draw(bp)
    return bp.bounds


bb = m["bbox"]
xmin, ymin, xmax, ymax = bounds("b")
scale = bb["b"][3] / (ymax - ymin)                # match the ascender letter
baseline = bb["m"][1] + bb["m"][3]               # flat bottom of m
glyphs = []                                      # (char, origin_x, color)
for key, ch, col in (("m", "m", AMBER), ("b", "b", AMBER), ("e1", "e", AMBER), ("r", "r", AMBER),
                     ("e2", "e", SLATE), ("t", "t", SLATE), ("a", "a", SLATE)):
    x0, _, x1, _ = bounds(ch)
    cx_t = bb[key][0] + bb[key][2] / 2
    glyphs.append((ch, cx_t - scale * (x0 + x1) / 2, col))


def glyph_path(ch, ox):
    pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}")
    gs[cmap[ord(ch)]].draw(TransformPen(pen, (scale, 0, 0, -scale, ox, baseline)))
    return pen.getCommands()


# ---------------------------------------------------------------- SVG
x_lo = bb["drop"][0] - 40
x_hi = bb["a"][0] + bb["a"][2] + 40
y_lo = bb["drop"][1] - 40
y_hi = max(bb["drop"][1] + bb["drop"][3], baseline) + 40
VB = f'{x_lo:.0f} {y_lo:.0f} {x_hi - x_lo:.0f} {y_hi - y_lo:.0f}'


def drop_group():
    return f"""  <g id="drop">
    <clipPath id="drop-clip"><path d="{drop_d}"/></clipPath>
    <path id="drop-body" d="{drop_d}" fill="{AMBER}"/>
    <path id="drop-shade" d="{shade_d}" fill="{DARK}" clip-path="url(#drop-clip)"/>
    <path id="drop-highlight" d="{hl_d}" fill="{WHITE}"/>
    <g id="chain" fill="{WHITE}">
      <rect x="{c1x:.1f}" y="{cy - bar_h / 2:.1f}" width="{c2x - c1x:.1f}" height="{bar_h:.1f}"/>
      <circle cx="{c1x:.1f}" cy="{cy:.1f}" r="{r_chain}"/>
      <circle cx="{c2x:.1f}" cy="{cy:.1f}" r="{r_chain}"/>
    </g>
  </g>"""


def m_group():
    return f"""  <g id="M">
    <g fill="none" stroke="{SLATE}" stroke-width="{W_M}" stroke-linecap="round" stroke-linejoin="round">
      <path d="M{xl:.1f},{yb:.1f} V{yt:.1f} L{xm:.1f},{ym:.1f} L{xr:.1f},{yt:.1f} V{yb:.1f}"/>
    </g>
    <g fill="{SLATE}">
      <circle cx="{xl:.1f}" cy="{yt:.1f}" r="{R_M}"/><circle cx="{xr:.1f}" cy="{yt:.1f}" r="{R_M}"/>
      <circle cx="{xm:.1f}" cy="{ym:.1f}" r="{R_MID}"/>
      <circle cx="{xl:.1f}" cy="{yb:.1f}" r="{R_M}"/><circle cx="{xr:.1f}" cy="{yb:.1f}" r="{R_M}"/>
    </g>
  </g>"""


def outlined_text():
    amb = "".join(glyph_path(c, ox) for c, ox, col in glyphs if col == AMBER)
    sla = "".join(glyph_path(c, ox) for c, ox, col in glyphs if col == SLATE)
    return (f'  <path id="text-mber" d="{amb}" fill="{AMBER}"/>\n'
            f'  <path id="text-eta" d="{sla}" fill="{SLATE}"/>')


def live_text():
    fs = scale * upem
    out = []
    for word, col in (("mber", AMBER), ("eta", SLATE)):
        xs = " ".join(f"{ox:.1f}" for c, ox, cl in glyphs if cl == col)
        out.append(f'  <text id="text-{word}" x="{xs}" y="{baseline:.1f}" fill="{col}" '
                   f'font-family="Kumbh Sans" font-weight="700" font-size="{fs:.2f}">{word}</text>')
    return "\n".join(out)


HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{w:.0f}" height="{h:.0f}">\n'
        '  <title>AmberMeta</title>\n')
w, h = x_hi - x_lo, y_hi - y_lo
(OUT / "ambermeta_logo.svg").write_text(
    HEAD.format(vb=VB, w=w, h=h) + drop_group() + "\n" + outlined_text() + "\n" + m_group() + "\n</svg>\n",
    encoding="utf-8")
(OUT / "ambermeta_logo_text.svg").write_text(
    HEAD.format(vb=VB, w=w, h=h) + drop_group() + "\n" + live_text() + "\n" + m_group() + "\n</svg>\n",
    encoding="utf-8")
dx, dy, dw, dh = bb["drop"]
pad = 20
side = max(dw, dh) + 2 * pad
ivb = f"{dx + dw / 2 - side / 2:.0f} {dy - pad:.0f} {side:.0f} {side:.0f}"
(OUT / "ambermeta_icon.svg").write_text(
    HEAD.format(vb=ivb, w=512, h=512) + drop_group() + "\n</svg>\n", encoding="utf-8")
print("scale", round(scale, 4), "font-size px", round(scale * upem, 1), "baseline", baseline,
      "b top", round(baseline - scale * ymax, 1), "target", bb["b"][1])
print("M", round(xl, 1), round(xr, 1), round(yt, 1), round(yb, 1), round(xm, 1), round(ym, 1))
