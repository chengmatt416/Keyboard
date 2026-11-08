#!/usr/bin/env python3
"""Cross-sections through the case with the real-part envelopes (renders/STRIP84_section.png)."""
from pathlib import Path

import cadquery as cq
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection

import build_case as b

ROOT = Path(__file__).resolve().parent.parent
plt.rcParams["font.family"] = "Inter"

C = dict(case="#2b2d31", part="#9aa3ab", cap="#c9ccd0", glass="#111214", pcb="#2f6b4c", wire="#e0a35a", usb="#55595e")


def section_polys(shape, x):
    plane = cq.Face.makePlane(2000, 2000, cq.Vector(x, 0, 0), cq.Vector(1, 0, 0))
    sec = shape.intersect(plane)
    polys = []
    for f in sec.Faces():
        vs, tris = f.tessellate(0.05, 0.2)
        for t in tris:
            polys.append([(vs[i].y, vs[i].z) for i in t])
    return polys


def draw(ax, x, items, title):
    for shape, col, alpha in items:
        if shape is None:
            continue
        p = section_polys(shape, x)
        if p:
            ax.add_collection(PolyCollection(p, facecolors=col, edgecolors=col, linewidths=0.15, alpha=alpha))
    ax.axhline(0, color="#999", lw=0.6)
    ax.set_aspect("equal")
    ax.set_xlim(-4, b.DEP + 4)
    ax.set_ylim(-3, 42)
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold", color="#222")
    ax.tick_params(labelsize=7, colors="#666")
    ax.set_xlabel("Y (mm, front → rear)", fontsize=7, color="#666")
    ax.set_ylabel("Z (mm)", fontsize=7, color="#666")
    for s in ax.spines.values():
        s.set_color("#ccc")


def main():
    top = b.build_top_case()
    bot = b.build_bottom_plate()
    cas = b.build_cassette()
    sled = b.build_board_sled()
    ret = b.build_screen_retainer()
    glass, lcd = b.env_touchbar()
    panel, pcb = b.env_screen()
    bp, bparts = b.env_board()
    shell, over = b.env_usb_plug()
    mcp, mcpp = b.env_mcp_board()
    sw = b.switch_solid()
    keys = b.KEYS
    sws = cq.Compound.makeCompound([b.to_world(sw.translate(cq.Vector(k["x"], k["v"], 0))) for k in keys])
    caps = cq.Compound.makeCompound([b.env_keycap(k) for k in keys])
    wiring = cq.Compound.makeCompound([b.env_switch_below(k) for k in keys])
    stabs = cq.Compound.makeCompound([e for e in (b.env_stab(k) for k in keys) if e is not None])
    enc = b.env_encoder()
    knob = b.env_knob()

    fig, axs = plt.subplots(2, 1, figsize=(15, 8.6), dpi=200)
    fig.patch.set_facecolor("white")
    kx = [k for k in keys if k["label"] == "G"][0]["x"]
    common = [(top, C["case"], 1), (bot, C["case"], 1), (cas, "#4a4d52", 1), (glass, C["glass"], 1), (lcd, C["pcb"], 0.9)]
    draw(axs[0], kx, common + [(wiring, C["wire"], 0.25), (sws, C["part"], 0.9), (caps, C["cap"], 0.55), (stabs, "#7b8a99", 0.9),
                               (mcp, C["pcb"], 0.9), (mcpp, "#666", 0.9)],
         f"Section A  x = {kx:.1f} mm (through the G column) — switches, keycaps (pressed↔unpressed envelope), 2 mm wiring zone, touch-bar stack")
    draw(axs[1], 28.0, common + [(sled, "#4a4d52", 1), (bp, C["pcb"], 1), (bparts, "#888", 1), (ret, "#4a4d52", 1), (panel, C["glass"], 1),
                                 (pcb, C["pcb"], 1), (enc, C["part"], 1), (knob, C["cap"], 0.8), (shell, C["usb"], 1), (over, "#222", 0.8)],
         "Section B  x = 28 mm (left control column) — knob + EC11, 1.69\" screen + retainer, ESP32-S3 on sled, USB-C cable mated")
    legend = [("printed case", C["case"]), ("printed inner parts", "#4a4d52"), ("switch / EC11", C["part"]), ("keycap envelope", C["cap"]),
              ("wiring allowance", C["wire"]), ("PCB / LCD", C["pcb"]), ("glass", C["glass"])]
    for i, (t, c) in enumerate(legend):
        fig.text(0.07 + i * 0.125, 0.015, "■ " + t, color=c if c not in (C["cap"],) else "#888", fontsize=8)
    fig.suptitle("STRIP / 84  v0.4 — stack-up check against real-part envelopes (1 : 1, mm)", x=0.07, ha="left", fontsize=12, fontweight="bold")
    fig.tight_layout(rect=(0, 0.03, 1, 0.96))
    out = ROOT / "renders" / "STRIP84_section.png"
    fig.savefig(out, facecolor="white")
    print("wrote", out)


if __name__ == "__main__":
    main()
