#!/usr/bin/env python3
"""STRIP/84 v0.4 - parametric enclosure generator (CadQuery).

Reads ../design/strip84.json and writes:
  out/step/*.step       printable parts + full assembly (with component envelopes)
  out/stl/mjf/*.stl     one-piece parts for MJF / SLS / large-bed printers
  out/stl/fdm/*.stl     the same parts split for a 256 mm bed
  out/stl/test_coupon.stl
  out/render/*.stl      meshes + placements.json used by render/render.py
  out/fit_report.md     interference / clearance checks against real part envelopes

Usage:  python build_case.py [--no-fdm] [--no-render-meshes]
"""
import json
import math
import sys
from pathlib import Path

import cadquery as cq

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
D = json.loads((ROOT / "design" / "strip84.json").read_text(encoding="utf-8"))
OUT = HERE / "out"

F, K, SW, ST = D["frame"], D["keys"], D["mx_switch"], D["stabilizer"]
KC, TB, SS, ENC = D["keycap"], D["touchbar"], D["side_screen"], D["encoder"]
MCU, USB, SCR, FEET = D["mcu_board"], D["usb_port"], D["screws"], D["feet"]

W, DEP = F["width"], F["depth"]
TILT = F["tilt_deg"]
TA = math.radians(TILT)
Y0, Z0 = F["grid_front_y"], F["plate_top_z_at_grid_front"]
BEZ = F["bezel_above_plate"]
P = K["pitch"]
GX0 = K["grid_x0"]
GRID_W, GRID_V = 16 * P, 6 * P
ZB = F["case_bottom_z"]
FLOOR = ZB + F["bottom_plate_t"]          # top of bottom plate (inside floor)
BIG = 1000.0


# --------------------------------------------------------------------------- helpers
def to_world(shape):
    """Local plate frame (x, v, w) -> world."""
    return shape.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), TILT).translate(cq.Vector(0, Y0, Z0))


def l2w(x, v, w):
    return (x, Y0 + v * math.cos(TA) - w * math.sin(TA), Z0 + v * math.sin(TA) + w * math.cos(TA))


def w2l(y, z):
    """world (y, z) -> local (v, w)"""
    dy, dz = y - Y0, z - Z0
    return dy * math.cos(TA) + dz * math.sin(TA), -dy * math.sin(TA) + dz * math.cos(TA)


def rrect_solid(cx, cy, w, h, z0, z1, r=0.0):
    wp = cq.Workplane("XY").workplane(offset=z0).center(cx, cy).rect(w, h).extrude(z1 - z0)
    if r > 0:
        wp = wp.edges("|Z").fillet(min(r, w / 2 - 0.01, h / 2 - 0.01))
    return wp.val()


def lbox(x0, x1, v0, v1, w0, w1, r=0.0):
    return to_world(rrect_solid((x0 + x1) / 2, (v0 + v1) / 2, x1 - x0, v1 - v0, w0, w1, r))


def lbox_c(cx, cv, w, h, w0, w1, r=0.0):
    return to_world(rrect_solid(cx, cv, w, h, w0, w1, r))


def below_w(wmax):
    return lbox(-BIG, BIG, -BIG, BIG, -BIG, wmax)


def above_w(wmin):
    return lbox(-BIG, BIG, -BIG, BIG, wmin, BIG)


def fuse_all(shapes):
    shapes = [s for s in shapes if s is not None]
    if not shapes:
        return None
    return shapes[0].fuse(*shapes[1:]).clean() if len(shapes) > 1 else shapes[0]


def comp(shapes):
    return cq.Compound.makeCompound(shapes)


def single(s, name):
    sol = s.Solids()
    if len(sol) != 1:
        print(f"WARNING {name}: {len(sol)} solids", sorted(round(x.Volume(), 1) for x in sol)[:6])
    return s


def vol(s):
    try:
        return abs(s.Volume())
    except Exception:
        return 0.0


def footprint(inset=0.0, z0=-BIG / 10, z1=BIG / 10):
    r = max(F["corner_r"] - inset, 0.5)
    return rrect_solid(W / 2, DEP / 2, W - 2 * inset, DEP - 2 * inset, z0, z1, r)


def P_at(v):
    """world z of the plate top at local v"""
    return Z0 + v * math.sin(TA)


# --------------------------------------------------------------------------- layout
def key_layout():
    keys = []
    for r, row in enumerate(K["rows"]):
        x = 0.0
        vc = GRID_V - (r + 0.5) * P
        for label, u in row:
            keys.append(dict(label=label, u=u, row=r, x=GX0 + (x + u / 2) * P, v=vc, x0=GX0 + x * P, x1=GX0 + (x + u) * P))
            x += u
        assert abs(x - 16) < 1e-6, f"row {r} is {x}u"
    assert len(keys) == 84, len(keys)
    mat = {lab: (ri, ci) for ri, row in enumerate(K["matrix"]) for ci, lab in enumerate(row)}
    for k in keys:
        k["rc"] = mat[k["label"]]
    return keys


KEYS = key_layout()
MK = D["macro_keys"]
MKEYS = [dict(label=lab, u=1, row=-1, x=MK["center"][0] + dx * P / 2, v=MK["center"][1] + dv * P / 2, rc=io)
         for lab, io, (dx, dv) in zip(MK["labels"], MK["io"], ((-1, 1), (1, 1), (-1, -1), (1, -1)))]
ALLKEYS = KEYS + MKEYS
ENCS = ENC["centers"]


def stab_offsets(u):
    s = ST["spacing"]
    for kname in sorted(s, key=float, reverse=True):
        if u >= float(kname) - 1e-6 and u >= 2:
            return s[kname]
    return None


# --------------------------------------------------------------------------- top case
OPEN = dict(x0=GX0 - K["opening_margin"], x1=GX0 + GRID_W + K["opening_margin"],
            v0=-K["opening_margin"], v1=GRID_V + K["opening_margin"])
OPEN2 = dict(x0=MK["center"][0] - P - K["opening_margin"], x1=MK["center"][0] + P + K["opening_margin"],
             v0=MK["center"][1] - P - K["opening_margin"], v1=MK["center"][1] + P + K["opening_margin"])


def build_top_case():
    sk, dsk = F["skin"], F["deck_skin"]
    # outer body: vertical walls cut by the tilted bezel plane
    outer = footprint(0, ZB, 80).cut(above_w(BEZ))
    # round the top perimeter, chamfer the bottom perimeter (shadow line)
    top_face = max((f for f in outer.Faces() if f.normalAt().z > 0.9), key=lambda f: f.Center().z)
    outer = outer.fillet(F["top_edge_round"], top_face.Edges())
    bot_face = min(outer.Faces(), key=lambda f: f.Center().z)
    outer = outer.chamfer(F["bottom_chamfer"], None, bot_face.Edges())

    cavity = footprint(F["wall"], -10, 80).intersect(below_w(BEZ - sk))
    body = outer.cut(cavity)
    # bottom-plate rabbet
    body = body.cut(footprint(F["rabbet"], -10, FLOOR))

    adds = []
    # thicker rear deck around the touch bar glass
    deck = lbox(0, W, OPEN["v1"] + K["lip_t"] - 0.5, 400, BEZ - dsk, BEZ - sk + 0.01).intersect(footprint(F["wall"] - 0.01, -10, 80))
    adds.append(deck)
    # key-opening lip and integrated plate
    lt = K["lip_t"]
    for O in (OPEN, OPEN2):
        adds.append(lbox(O["x0"] - lt, O["x1"] + lt, O["v0"] - lt, O["v1"] + lt, -SW["plate_total"], BEZ, K["opening_r"] + lt))
    # bosses for the bottom plate (M3 heat-set inserts)
    bd = SCR["boss_d"]
    for x, y in SCR["bottom_xy_world"]:
        adds.append(cq.Solid.makeCylinder(bd / 2, 80, cq.Vector(x, y, FLOOR)).intersect(below_w(BEZ - sk + 0.01)))
    for x, v in SCR["bottom_xv_local"]:
        y, _ = l2w(x, v, 0)[1:]
        inside_grid = any(O["x0"] < x < O["x1"] and O["v0"] < v < O["v1"] for O in (OPEN, OPEN2))
        wtop = -SW["plate_total"] + 0.01 if inside_grid else BEZ - sk + 0.01
        if v > OPEN["v1"]:
            wtop = BEZ - dsk + 0.01
        adds.append(cq.Solid.makeCylinder(bd / 2, 80, cq.Vector(x, y, FLOOR)).intersect(below_w(wtop)))
    # M2 bosses for the touch-bar cassette and the side-screen retainer
    for x, v in SCR["cassette_front_xv"] + SCR["cassette_rear_xv"]:
        adds.append(lbox_c(x, v, SCR["m2_boss_d"], SCR["m2_boss_d"], cassette_top_w(), BEZ - dsk + 0.01, SCR["m2_boss_d"] / 2 - 0.01)
                    .intersect(footprint(0.5, -10, 80)))
    ret_top = screen_retainer_top_w()
    for x, v in SCR["retainer_xv"]:
        adds.append(lbox_c(x, v, SCR["m2_boss_d"], SCR["m2_boss_d"], ret_top, BEZ - sk + 0.01, SCR["m2_boss_d"] / 2 - 0.01)
                    .intersect(footprint(0.5, -10, 80)))
    # stiffening ribs under the left control column and the front band
    for v in (OPEN2["v0"] - lt - 1.5,):
        adds.append(lbox(F["wall"] - 0.5, OPEN["x0"] - lt + 0.5, v - 0.8, v + 0.8, BEZ - sk - 4, BEZ - sk + 0.01))
    body = body.fuse(*adds).clean()

    for O in (OPEN, OPEN2):
        body = body.fuse(lbox(O["x0"], O["x1"], O["v0"], O["v1"], -SW["plate_total"], 0, K["opening_r"]))

    cuts = []
    # key openings above the plates (main grid + 2x2 macro cluster)
    for O in (OPEN, OPEN2):
        cuts.append(lbox(O["x0"], O["x1"], O["v0"], O["v1"], 0, BEZ + 5, K["opening_r"]))
    # switch cut-outs (14.00) through the 1.5 mm skin and reliefs below it for the clips
    for k in ALLKEYS:
        c = SW["cutout"]
        cuts.append(lbox_c(k["x"], k["v"], c, c, -SW["plate_total"] - 1, 1, SW["cutout_r"]))
        cuts.append(lbox_c(k["x"], k["v"], SW["relief_x"], SW["relief_v"], -SW["plate_total"] - 1, -SW["plate_skin"], 0.8))
        s = stab_offsets(k["u"])
        if s:
            for sx in (-s, s):
                cuts.append(lbox(k["x"] + sx - ST["w"] / 2, k["x"] + sx + ST["w"] / 2, k["v"] - ST["front"], k["v"] + ST["rear"],
                                 -SW["plate_total"] - 1, 1, ST["r"]))
                cuts.append(lbox(k["x"] + sx - ST["relief_w"] / 2, k["x"] + sx + ST["relief_w"] / 2, k["v"] - ST["relief_front"],
                                 k["v"] + ST["relief_rear"], -SW["plate_total"] - 1, -SW["plate_skin"], 0.8))
            ch0, ch1 = ST["wire_channel"]
            cuts.append(lbox(k["x"] - s, k["x"] + s, k["v"] - ch1, k["v"] - ch0, -SW["plate_total"] - 1, -SW["plate_skin"]))
    # touch bar: glass pocket + LCD opening
    gw, gh, gt = TB["glass"]
    gc = TB["glass_clear"]
    cuts.append(lbox_c(TB["center_x"], TB["center_v"], gw + 2 * gc, gh + 2 * gc, BEZ - gt, BEZ + 5, TB["glass_r"]))
    cuts.append(lbox_c(TB["center_x"], TB["center_v"], gw - 2 * TB["ledge"], gh - 2 * TB["ledge"], -30, BEZ, 1.0))
    # side screen: chamfered window, panel recess
    sx, sv = SS["center"]
    aw, ah = SS["active"]
    win_lo = lbox_c(sx, sv + SS["active_offset_v"], aw + .4, ah + .4, BEZ - SS["recess"] - 2, BEZ - 0.79, SS["window_r"])
    win_ch = to_world(cq.Solid.makeLoft([
        rrect_wire(sx, sv + SS["active_offset_v"], aw + .4, ah + .4, SS["window_r"], BEZ - 0.8),
        rrect_wire(sx, sv + SS["active_offset_v"], aw + 2.0, ah + 2.0, SS["window_r"] + .8, BEZ + 0.001)], True))
    pw, ph, pt = SS["panel"]
    cuts += [win_lo, win_ch, lbox_c(sx, sv, pw + .4, ph + .4, BEZ - sk - 1, BEZ - SS["recess"], 1.0)]
    # encoder holes
    for ex, ev in ENCS:
        cuts.append(to_world(cq.Solid.makeCylinder(ENC["hole"] / 2, 20, cq.Vector(ex, ev, BEZ - 10))))
    # M3 insert holes (from below) / M2 pilot holes
    for x, y in SCR["bottom_xy_world"]:
        cuts.append(cq.Solid.makeCylinder(SCR["insert_hole"] / 2, SCR["insert_depth"] + 0.01, cq.Vector(x, y, FLOOR - 0.01)))
    for x, v in SCR["bottom_xv_local"]:
        y = l2w(x, v, 0)[1]
        cuts.append(cq.Solid.makeCylinder(SCR["insert_hole"] / 2, SCR["insert_depth"] + 0.01, cq.Vector(x, y, FLOOR - 0.01)))
    for x, v in SCR["cassette_front_xv"] + SCR["cassette_rear_xv"]:
        cuts.append(to_world(cq.Solid.makeCylinder(SCR["m2_pilot"] / 2, (BEZ - F["deck_skin"] + 1.0) - cassette_top_w(), cq.Vector(x, v, cassette_top_w() - 0.01))))
    for x, v in SCR["retainer_xv"]:
        cuts.append(to_world(cq.Solid.makeCylinder(SCR["m2_pilot"] / 2, (BEZ - 1.0) - screen_retainer_top_w(), cq.Vector(x, v, screen_retainer_top_w() - 0.01))))
    # USB-C through the rear wall
    ux, uz = usb_center()
    hw, hh, hr = USB["hole"]
    hole = cq.Workplane("XZ").workplane(offset=-(DEP + 1)).center(ux, uz).rect(hw, hh).extrude(F["wall"] + 2).edges("|Y").fillet(hr).val()
    cuts.append(hole)
    pw_, ph_ = USB["pocket"]
    pocket = cq.Workplane("XZ").workplane(offset=-(DEP - USB["wall_left"])).center(MCU["center_x"], uz).rect(pw_, ph_).extrude(F["wall"]).edges("|Y").fillet(2.0).val()
    cuts.append(pocket)

    body = body.cut(fuse_all(cuts)).clean()
    return body


def rrect_wire(cx, cy, w, h, r, z):
    return _rrect_wire2(cx, cy, w, h, r, z)


def _rrect_wire2(cx, cy, w, h, r, z):
    f = cq.Workplane("XY").workplane(offset=z).center(cx, cy).rect(w, h).extrude(1).edges("|Z").fillet(r).faces("<Z").val()
    return f.outerWire()


def cassette_top_w():
    gt = TB["glass"][2]
    return BEZ - gt - TB["lcd"][2] - TB["foam"]


def screen_retainer_top_w():
    return BEZ - SS["recess"] - SS["panel"][2] - SS["module_pcb"][2] - 0.3


def usb_center():
    x = MCU["center_x"] + MCU["usb_offset_x"]
    z = MCU["board_bottom_z"] + MCU["size"][2] + MCU["usb_receptacle"][2] / 2
    return x, z


# --------------------------------------------------------------------------- other printed parts
def build_bottom_plate():
    t = F["bottom_plate_t"]
    g = F["bottom_plate_gap"]
    bp = footprint(F["rabbet"] + g, ZB, ZB + t)
    cuts = []
    holes = [(x, y) for x, y in SCR["bottom_xy_world"]] + [(x, l2w(x, v, 0)[1]) for x, v in SCR["bottom_xv_local"]]
    for x, y in holes:
        cuts.append(cq.Solid.makeCylinder(SCR["clear_hole"] / 2, t + 2, cq.Vector(x, y, ZB - 1)))
        cuts.append(cq.Solid.makeCone(SCR["csk_d"] / 2, 0, SCR["csk_d"] / 2, cq.Vector(x, y, ZB - 0.01)))
    for x, y in FEET["xy"]:
        cuts.append(cq.Solid.makeCylinder(FEET["d"] / 2, FEET["recess"], cq.Vector(x, y, ZB - 0.01)))
    # sled screws (M3 + nut) for the MCU board sled
    for x, y in sled_screws():
        cuts.append(cq.Solid.makeCylinder(SCR["clear_hole"] / 2, t + 2, cq.Vector(x, y, ZB - 1)))
        cuts.append(cq.Solid.makeCone(SCR["csk_d"] / 2, 0, SCR["csk_d"] / 2, cq.Vector(x, y, ZB - 0.01)))
    bp = bp.cut(fuse_all(cuts))
    # debossed label on the underside
    try:
        txt = (cq.Workplane("XY").workplane(offset=ZB - 0.01).center(W / 2, DEP / 2)
               .text("STRIP / 84   rev " + D["rev"], 7, 0.4, combine=False, halign="center", valign="center",
                     font="Inter", kind="bold").val())
        txt = txt.mirror("YZ", cq.Vector(W / 2, 0, 0))
        bp = bp.cut(txt)
    except Exception as e:  # font missing is not fatal
        print("label skipped:", e)
    return bp.clean()


def sled_geom():
    bw, bl, bt = MCU["size"]
    y1 = DEP - USB["wall_left"] - MCU["rear_gap"]           # board rear edge (USB face)
    return bw, bl, bt, y1


def sled_screws():
    bw, bl, bt, y1 = sled_geom()
    cx = MCU["center_x"]
    return [(cx, y1 - bl - 4.0), (cx, y1 - bl * 0.45)]


def build_board_sled():
    bw, bl, bt, y1 = sled_geom()
    cx = MCU["center_x"]
    zb = MCU["board_bottom_z"]
    base_t = 2.0
    y0 = y1 - bl - 8.0
    base = rrect_solid(cx, (y0 + y1 - 3) / 2, bw + 8, y1 - 3 - y0, FLOOR, FLOOR + base_t, 2.0)
    rails = []
    for s in (-1, 1):
        rx = cx + s * (bw / 2 + 1.0)
        rails.append(rrect_solid(cx + s * (bw / 2 + 1.25), y1 - bl / 2 - 1.5, 2.1, bl - 6, FLOOR, zb + bt, 0.8))
    stop = rrect_solid(cx, y1 - bl - 1.75, bw + 4.6, 3.0, FLOOR, zb + bt, 0.8)
    sled = base.fuse(*rails, stop)
    # support posts under the board
    for dx in (-bw / 2 + 3, bw / 2 - 3):
        for yy in (y1 - 8, y1 - bl + 8):
            sled = sled.fuse(rrect_solid(cx + dx, yy, 4, 4, FLOOR, zb, 1.0))
    for x, y in sled_screws():
        sled = sled.fuse(cq.Solid.makeCylinder(4.5, 4.0, cq.Vector(x, y, FLOOR)))
        sled = sled.cut(cq.Solid.makeCylinder(SCR["clear_hole"] / 2, 10, cq.Vector(x, y, FLOOR - 1)))
        nut = cq.Workplane("XY").workplane(offset=FLOOR + 1.6).center(x, y).polygon(6, 6.4).extrude(5).val()
        sled = sled.cut(nut)
    return sled.clean()


def build_cassette():
    gw, gh, gt = TB["glass"]
    lw, lh, lt = TB["lcd"]
    top = cassette_top_w()
    t = TB["cassette_t"]
    v_front = SCR["cassette_front_xv"][0][1]
    v_rear = SCR["cassette_rear_xv"][0][1]
    v_back = v_rear + 0.2
    cw = gw - 4.0
    body = lbox(TB["center_x"] - cw / 2, TB["center_x"] + cw / 2, v_front + 4.0, v_back, top - t, top, 3.0)
    tabs = []
    for x, v in SCR["cassette_front_xv"]:
        tabs.append(lbox_c(x, v + 2.2, 9.0, 9.0, top - t, top, 2.0))
    body = body.fuse(*tabs)
    # pocket edges that locate the LCD (0.3 clearance) and foam
    lip = lbox_c(TB["center_x"], TB["center_v"], lw + 0.6 + 3.0, lh + 0.6 + 3.0, top, top + 1.2, 1.5).cut(
        lbox_c(TB["center_x"], TB["center_v"], lw + 0.6, lh + 0.6, top - 1, top + 2, 0.8))
    lip = lip.intersect(lbox(-BIG, BIG, v_front + 4.0, v_back, -BIG, BIG))
    for x, v in SCR["cassette_rear_xv"]:
        lip = lip.cut(lbox_c(x, v, SCR["m2_boss_d"] + 0.8, SCR["m2_boss_d"] + 0.8, -BIG, BIG, SCR["m2_boss_d"] / 2 + 0.39))
    body = body.fuse(lip)
    cuts = []
    for x, v in SCR["cassette_front_xv"] + SCR["cassette_rear_xv"]:
        cuts.append(to_world(cq.Solid.makeCylinder(1.15, 10, cq.Vector(x, v, top - 5))))
    sw_, sh_ = TB["fpc_slot"]
    for sx in (TB["center_x"] - lw / 2 + 30, TB["center_x"] + lw / 2 - 30):
        cuts.append(lbox_c(sx, TB["center_v"], sw_, sh_, top - 5, top + 5, 1.0))
    # lightening slots
    for i in range(6):
        sx = TB["center_x"] - 125 + i * 50
        cuts.append(lbox_c(sx, TB["center_v"], 30, 10, top - 5, top + 5, 2.0))
    return body.cut(fuse_all(cuts)).clean()


def build_screen_retainer():
    """Cross bar that presses the 1.69" module PCB up against the skin (bosses left/right of the PCB)."""
    sx, sv = SS["center"]
    mw, mh, mt = SS["module_pcb"]
    top = screen_retainer_top_w()
    (x0, v0), (x1, v1) = SCR["retainer_xv"]
    bar = lbox(x0 - 3.0, x1 + 1.8, sv - 5, sv + 5, top - 2.0, top, 2.4)
    pads = [lbox_c(sx, sv + s * (mh / 2 - 4), mw - 4, 6, top - 2.0, top, 1.0) for s in (-1, 1)]
    spine = lbox_c(sx, sv, 8, mh - 2, top - 2.0, top, 1.5)
    ret = bar.fuse(*pads, spine)
    for x, v in SCR["retainer_xv"]:
        ret = ret.cut(to_world(cq.Solid.makeCylinder(1.15, 10, cq.Vector(x, v, top - 5))))
    return ret.clean()


def build_test_coupon():
    """Small print to validate switch / stab / encoder / insert fits before the full case."""
    L, Wd = 112.0, 44.0
    t_total = SW["plate_total"]
    base = rrect_solid(L / 2, Wd / 2, L, Wd, 0, t_total, 3.0)
    cuts, adds = [], []
    xs = [12, 33, 54]
    for x, c in zip(xs, (13.9, 14.0, 14.1)):
        cuts.append(rrect_solid(x, 12, c, c, -1, t_total + 1, SW["cutout_r"]))
        cuts.append(rrect_solid(x, 12, SW["relief_x"], SW["relief_v"], -1, t_total - SW["plate_skin"], 0.8))
    # 1.4 mm skin variant
    cuts.append(rrect_solid(75, 12, 14.0, 14.0, -1, t_total + 1, SW["cutout_r"]))
    cuts.append(rrect_solid(75, 12, SW["relief_x"], SW["relief_v"], -1, t_total - 1.4, 0.8))
    # 2u stabilised key
    kx, kv = 40, 32
    s = ST["spacing"]["2"]
    cuts.append(rrect_solid(kx, kv, 14, 14, -1, t_total + 1, SW["cutout_r"]))
    cuts.append(rrect_solid(kx, kv, SW["relief_x"], SW["relief_v"], -1, t_total - SW["plate_skin"], 0.8))
    for sx in (-s, s):
        cuts.append(rrect_solid(kx + sx, kv + (ST["rear"] - ST["front"]) / 2, ST["w"], ST["front"] + ST["rear"], -1, t_total + 1, ST["r"]))
        cuts.append(rrect_solid(kx + sx, kv + (ST["relief_rear"] - ST["relief_front"]) / 2, ST["relief_w"], ST["relief_front"] + ST["relief_rear"], -1, t_total - SW["plate_skin"], 0.8))
    # the stab rectangle sits 8 mm toward the front (-y here) and 6 mm toward the rear (+y)
    # encoder hole in a 2 mm skin, insert boss
    cuts.append(cq.Solid.makeCylinder(ENC["hole"] / 2, 20, cq.Vector(96, 12, -1)))
    cuts.append(rrect_solid(96, 12, 16, 16, -1, t_total - 2.0, 2.0))
    adds.append(cq.Solid.makeCylinder(SCR["boss_d"] / 2, 8, cq.Vector(96, 33, -8 + t_total)))
    c = base.fuse(*adds)
    for t_ in cuts:
        c = c.cut(t_)
    c = c.cut(cq.Solid.makeCylinder(SCR["insert_hole"] / 2, SCR["insert_depth"], cq.Vector(96, 33, -8 + t_total - 0.01)))
    try:
        for x, lab in zip(xs + [75], ("13.9", "14.0", "14.1", "t1.4")):
            c = c.cut(cq.Workplane("XY").workplane(offset=t_total - 0.4).center(x, 1.0 + 1.4)
                      .text(lab, 3.2, 1, combine=False, halign="center", valign="center", font="Inter", kind="bold").val())
    except Exception as e:
        print("coupon labels skipped:", e)
    return c.clean()


# --------------------------------------------------------------------------- real-part envelopes (fit checks + render)
def env_switch_below(k):
    """MX housing + pins + solder/diode allowance below the plate, 19.05 square."""
    w0 = -(SW["below_plate_housing"] + SW["pin_len"] + SW["wiring_allowance"])
    return lbox_c(k["x"], k["v"], 14.0, 14.0, w0, -SW["plate_skin"]).fuse(
        lbox_c(k["x"], k["v"], P - 0.2, P - 0.2, w0, -SW["below_plate_housing"]))


def env_keycap(k):
    """Keycap footprint from fully pressed skirt to unpressed top."""
    w = k["u"] * P - KC["gap"]
    return lbox_c(k["x"], k["v"], w, KC["depth_bottom"], KC["skirt_above_plate"] - SW["travel"],
                  KC["skirt_above_plate"] + KC["height"], 1.0)


def env_stab(k):
    s = stab_offsets(k["u"])
    if not s:
        return None
    parts = [lbox(k["x"] + sx - 3.3, k["x"] + sx + 3.3, k["v"] - 7.8, k["v"] + 5.8, -ST["housing_below_plate"], -SW["plate_skin"] - 0.01) for sx in (-s, s)]
    parts.append(lbox(k["x"] - s, k["x"] + s, k["v"] - 9.0, k["v"] - 4.5, -ST["housing_below_plate"] + 2.5, -SW["plate_skin"] - 0.01))
    return fuse_all(parts)


def env_encoder():
    bw, bh, bt = ENC["body"]
    top = BEZ - F["skin"]
    parts = []
    for ex, ev in ENCS:
        parts.append(lbox_c(ex, ev, bw, bh, top - bt, top - 0.6))
        parts.append(lbox_c(ex, ev, bw, bh + 2, top - bt - ENC["pins"], top - bt))
        parts.append(to_world(cq.Solid.makeCylinder(3.5, F["skin"] + 0.6 + 2.0, cq.Vector(ex, ev, top - 0.6))))
    return fuse_all(parts)


def env_knob():
    d, h = ENC["knob"]
    return fuse_all([to_world(cq.Solid.makeCylinder(d / 2, h, cq.Vector(ex, ev, BEZ + 0.8))) for ex, ev in ENCS])


def env_screen():
    sx, sv = SS["center"]
    pw, ph, pt = SS["panel"]
    mw, mh, mt = SS["module_pcb"]
    ptop = BEZ - SS["recess"]
    panel = lbox_c(sx, sv, pw, ph, ptop - pt, ptop, 1.0)
    pcb = lbox_c(sx, sv, mw, mh, ptop - pt - mt, ptop - pt - 0.01, 1.0)
    return panel, pcb


def env_touchbar():
    gw, gh, gt = TB["glass"]
    lw, lh, lt = TB["lcd"]
    glass = lbox_c(TB["center_x"], TB["center_v"], gw, gh, BEZ - gt, BEZ, TB["glass_r"])
    lcd = lbox_c(TB["center_x"], TB["center_v"], lw, lh, BEZ - gt - lt, BEZ - gt - 0.001, 0.5)
    return glass, lcd


def env_board():
    bw, bl, bt, y1 = sled_geom()
    cx = MCU["center_x"]
    zb = MCU["board_bottom_z"]
    pcb = rrect_solid(cx, y1 - bl / 2, bw, bl, zb, zb + bt, 0.5)
    module = rrect_solid(cx, y1 - bl + 10, 18, 25.5, zb + bt, zb + bt + 3.2, 0.3)
    rw, rl, rh = MCU["usb_receptacle"]
    ux, uz = usb_center()
    rec = rrect_solid(ux, y1 - rl / 2 + 0.3, rw, rl, zb + bt, zb + bt + rh, 1.0)
    rec2 = rrect_solid(cx - MCU["usb_offset_x"], y1 - rl / 2 + 0.3, rw, rl, zb + bt, zb + bt + rh, 1.0)
    headers = [rrect_solid(cx + s * (bw / 2 - 1.27), y1 - bl / 2, 2.6, bl - 6, zb + bt, zb + bt + 2.5) for s in (-1, 1)]
    return pcb, fuse_all([module, rec, rec2] + headers)


def env_usb_plug():
    """Typical USB-C cable: 8.4 x 2.6 shell, 12.2 x 6.6 overmold, mated."""
    ux, uz = usb_center()
    bw, bl, bt, y1 = sled_geom()
    face = y1 + 0.3                       # receptacle face (protrudes 0.3)
    shell = rrect_solid(ux, face + 3.0, 8.4, 6.0, uz - 1.3, uz + 1.3, 1.2)
    over = cq.Workplane("XZ").workplane(offset=-(face + 6.0)).center(ux, uz).rect(12.2, 6.6).extrude(25).edges("|Y").fillet(2.4).val()
    return shell, over


def env_mcp_board():
    yc = DEP - F["wall"] - 1.0 - 12.0
    return rrect_solid(234.5, yc, 80, 24, FLOOR + 4, FLOOR + 5.6, 1.0), rrect_solid(234.5, yc, 76, 20, FLOOR + 5.6, FLOOR + 5.6 + 8.0, 0.5)


# --------------------------------------------------------------------------- fit report
def fit_checks(top, bottom, cassette, sled, retainer):
    rows, fails = [], 0

    def chk(name, a, b, note=""):
        nonlocal fails
        v = vol(a.intersect(b)) if (a is not None and b is not None) else 0.0
        ok = v < 1e-3
        fails += (not ok)
        rows.append((name, "PASS" if ok else f"FAIL ({v:.2f} mm³)", note))

    case = top.fuse(bottom)
    sw_env = comp([env_switch_below(k) for k in ALLKEYS])
    cap_env = comp([env_keycap(k) for k in ALLKEYS])
    stab_env = comp([e for e in (env_stab(k) for k in KEYS) if e is not None])
    chk("84 + 4 macro MX switches: housing + pins + 2 mm wiring vs case/plate", sw_env, case, "housing below plate 5.0, pins 3.3")
    chk("88 keycaps (pressed → unpressed) vs bezel / lip", cap_env, top, f"keycap gap to opening wall ≥ {K['opening_margin'] + KC['gap'] / 2:.2f} mm")
    chk("4 stabiliser sets (housings + wire) vs case", stab_env, case)
    enc = env_encoder()
    chk("2 × EC11 body, pins and bushing vs case", enc, case)
    chk("2 knobs vs case", env_knob(), top)
    panel, pcb = env_screen()
    chk("1.69\" panel vs case", panel, top)
    chk("1.69\" module PCB vs case", pcb, top)
    chk("Screen retainer vs case", retainer, case)
    glass, lcd = env_touchbar()
    chk("Touch-bar cover glass vs pocket", glass, top)
    chk("Touch-bar LCD vs deck", lcd, top)
    chk("Cassette vs case", cassette, case)
    chk("Cassette vs LCD", cassette, lcd)
    b_pcb, b_parts = env_board()
    chk("ESP32-S3 board vs case", b_pcb.fuse(b_parts), case)
    chk("ESP32-S3 board vs sled", b_pcb.fuse(b_parts), sled)
    chk("ESP32-S3 board vs screen module", b_pcb.fuse(b_parts), pcb)
    chk("ESP32-S3 board vs encoders", b_pcb.fuse(b_parts), enc)
    chk("Knobs vs macro keycaps", env_knob(), cap_env)
    chk("Macro switch wiring vs encoders", sw_env, enc)
    chk("Macro switch wiring vs screen module", sw_env, pcb)
    chk("ESP32-S3 board vs cassette", b_pcb.fuse(b_parts), cassette)
    chk("Sled vs case", sled, top)
    shell, over = env_usb_plug()
    chk("USB-C plug shell vs rear wall", shell, top, "mated 6.0 mm")
    chk("USB-C plug overmold (12.2 × 6.6) vs rear wall", over, top)
    m_pcb, m_parts = env_mcp_board()
    chk("MCP23017 perfboard (80 × 24, DIP sockets) vs case", m_pcb.fuse(m_parts), case, "free bay under the touch bar")
    chk("MCP perfboard vs cassette", m_pcb.fuse(m_parts), cassette)

    # numeric clearances
    nums = []
    v_front = 0.5 * P
    pin_tip = P_at(v_front) - SW["below_plate_housing"] - SW["pin_len"]
    nums.append(("Front row: switch pin tips → floor", f"{pin_tip - FLOOR:.2f} mm"))
    nums.append(("Front row: room left for diodes / wire below pins", f"{pin_tip - FLOOR:.2f} mm (≥ 2.0 required)"))
    keytop_rear = l2w(0, GRID_V - 0.5 * P, KC["skirt_above_plate"] + KC["height"])[2]
    keytop_front = l2w(0, 0.5 * P, KC["skirt_above_plate"] + KC["height"])[2]
    nums.append(("Keytop height, front row / F-row (render envelope)", f"{keytop_front:.1f} / {keytop_rear:.1f} mm"))
    bb = top.BoundingBox()
    nums.append(("Case height front edge / rear edge", f"{l2w(0, w2l(0.0, 0)[0], BEZ)[2]:.1f} / {bb.zmax:.1f} mm"))
    nums.append(("Case footprint", f"{bb.xlen:.1f} × {bb.ylen:.1f} mm"))
    nums.append(("Typing angle", f"{TILT:.1f}°"))
    nums.append(("Keycap → opening wall gap", f"{K['opening_margin'] + KC['gap'] / 2:.2f} mm per side"))
    nums.append(("Touch-bar glass top vs bezel", "flush (pocket depth = glass thickness)"))
    return rows, nums, fails


# --------------------------------------------------------------------------- render meshes
def keycap_solid(u):
    w = u * P - KC["gap"]
    d = KC["depth_bottom"]
    wt, dt = w - KC["top_inset_w"], KC["depth_top"]
    h = KC["height"]
    bot = _rrect_wire2(0, 0, w, d, 1.6, 0)
    top = _rrect_wire2(0, 0.3, wt, dt, 2.6, h)
    cap = cq.Solid.makeLoft([bot, top], True)
    try:
        topf = max(cap.Faces(), key=lambda f: f.Center().z)
        cap = cap.fillet(1.0, topf.Edges())
    except Exception:
        pass
    R = 60.0
    dish = cq.Solid.makeCylinder(R, w + 10, cq.Vector(-w / 2 - 5, 0.3, h + R - KC["dish"]), cq.Vector(1, 0, 0))
    cap = cap.cut(dish)
    return cap


def switch_solid():
    bottom = rrect_solid(0, 0, 13.9, 13.9, -SW["below_plate_housing"], 0, 0.6)
    top = cq.Solid.makeLoft([_rrect_wire2(0, 0, 15.4, 15.4, 1.0, 0), _rrect_wire2(0, 0, 11.4, 12.4, 1.5, SW["above_plate_housing"])], True)
    pins = fuse_all([cq.Solid.makeCylinder(0.75, 3.3, cq.Vector(-3.81, 2.54, -8.3)), cq.Solid.makeCylinder(0.75, 3.3, cq.Vector(2.54, 5.08, -8.3)),
                     cq.Solid.makeCylinder(2.0, 3.3, cq.Vector(0, 0, -8.3))])
    return top.fuse(bottom, pins).clean()


def stem_solid():
    a = rrect_solid(0, 0, 4.0, 1.3, SW["above_plate_housing"] - 0.5, SW["above_plate_stem"])
    b = rrect_solid(0, 0, 1.2, 4.0, SW["above_plate_housing"] - 0.5, SW["above_plate_stem"])
    c = rrect_solid(0, 0, 6.5, 6.5, SW["above_plate_housing"] - 0.8, SW["above_plate_housing"] + 0.6, 1.0)
    return a.fuse(b, c).clean()


def knob_solid():
    d, h = ENC["knob"]
    k = cq.Solid.makeCylinder(d / 2, h, cq.Vector(0, 0, 0))
    k = k.fillet(0.6, [max(k.Edges(), key=lambda e: e.Center().z)])
    k = k.chamfer(0.5, None, [min(k.Edges(), key=lambda e: e.Center().z)])
    grooves = []
    n = 72
    for i in range(n):
        a = 2 * math.pi * i / n
        g = rrect_solid(0, 0, 0.7, 0.7, 0.8, h - 3.5).rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), 45)
        g = g.translate(cq.Vector(d / 2 * math.cos(a), d / 2 * math.sin(a), 0))
        grooves.append(g)
    k = k.cut(fuse_all(grooves))
    # concave top + indicator
    k = k.cut(cq.Solid.makeSphere(80, cq.Vector(0, 0, h + 80 - 0.5)))
    k = k.cut(cq.Solid.makeCylinder(0.8, 2, cq.Vector(0, d / 2 - 3.2, h - 1.2)))
    return k


def export_stl(shape, path, tol=0.02, ang=0.15):
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shape, str(path), tolerance=tol, angularTolerance=ang)


def export_step(shape, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shape, str(path))


# --------------------------------------------------------------------------- FDM split
def stepped_cutter(target_x):
    """Region left of a seam that follows key boundaries row by row."""
    parts = []
    xs = []
    for r, row in enumerate(K["rows"]):
        bounds, x = [], 0.0
        for _, u in row:
            x += u
            bounds.append(GX0 + x * P)
        bx = min(bounds[:-1], key=lambda b: abs(b - target_x))
        xs.append(bx)
        v1 = GRID_V - r * P
        v0 = v1 - P
        if r == 0:
            v1 = BIG
        if r == len(K["rows"]) - 1:
            v0 = -BIG
        parts.append(lbox(-BIG, bx, v0, v1, -BIG, BIG))
    return fuse_all(parts), xs


def split_x(shape, x):
    left = shape.intersect(rrect_solid(x - BIG / 2, DEP / 2, BIG, BIG, -BIG, BIG))
    right = shape.cut(rrect_solid(x - BIG / 2, DEP / 2, BIG, BIG, -BIG, BIG))
    return left, right


# --------------------------------------------------------------------------- main
def main():
    do_fdm = "--no-fdm" not in sys.argv
    do_render = "--no-render-meshes" not in sys.argv
    OUT.mkdir(exist_ok=True)
    print("top case ...")
    top = build_top_case()
    print("bottom plate ...")
    bottom = build_bottom_plate()
    print("cassette / sled / retainer / coupon ...")
    cassette = build_cassette()
    sled = build_board_sled()
    retainer = build_screen_retainer()
    coupon = build_test_coupon()

    for n_, s_ in (("top", top), ("bottom", bottom), ("cassette", cassette), ("sled", sled), ("retainer", retainer), ("coupon", coupon)):
        single(s_, n_)
    parts = {"top_case": top, "bottom_plate": bottom, "touchbar_cassette": cassette, "mcu_sled": sled, "screen_retainer": retainer}
    for n, s in parts.items():
        export_step(s, OUT / "step" / f"{n}.step")
        export_stl(s, OUT / "stl" / "mjf" / f"{n}.stl")
    export_stl(coupon, OUT / "stl" / "test_coupon.stl")
    export_step(coupon, OUT / "step" / "test_coupon.step")

    split_info = {}
    if do_fdm:
        print("FDM split ...")
        cutter, seam_xs = stepped_cutter(D["fdm_split"]["top_target_x"])
        tl, tr = top.intersect(cutter), top.cut(cutter)
        bl, br = split_x(bottom, D["fdm_split"]["bottom_x"])
        cl, cr = split_x(cassette, D["fdm_split"]["cassette_x"])
        for n, s in {"top_case_L": tl, "top_case_R": tr, "bottom_plate_L": bl, "bottom_plate_R": br,
                     "touchbar_cassette_L": cl, "touchbar_cassette_R": cr, "mcu_sled": sled, "screen_retainer": retainer}.items():
            export_stl(s, OUT / "stl" / "fdm" / f"{n}.stl")
            bb = s.BoundingBox()
            split_info[n] = (bb.xlen, bb.ylen, bb.zlen)
        split_info["_seam_xs"] = seam_xs

    print("fit checks ...")
    rows, nums, fails = fit_checks(top, bottom, cassette, sled, retainer)

    # print stats
    stats = []
    for n, s in parts.items():
        bb = s.BoundingBox()
        stats.append((n, vol(s) / 1000.0, bb.xlen, bb.ylen, bb.zlen))
    stats.append(("test_coupon", vol(coupon) / 1000.0, *(lambda b: (b.xlen, b.ylen, b.zlen))(coupon.BoundingBox())))

    lines = [f"# STRIP/84 v{D['rev']} fit report", "",
             "Generated by `cad/build_case.py` from `design/strip84.json`. Every check intersects the printed parts with an envelope "
             "built from the real part's dimensions; PASS = zero overlapping volume.", "",
             "| Check | Result | Note |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    lines += ["", "## Key clearances", "", "| Item | Value |", "|---|---|"] + [f"| {a} | {b} |" for a, b in nums]
    lines += ["", "## Printed parts", "", "| Part | Volume cm³ | Bounding box mm |", "|---|---:|---|"]
    lines += [f"| {n} | {v:.1f} | {x:.1f} × {y:.1f} × {z:.1f} |" for n, v, x, y, z in stats]
    if split_info:
        lines += ["", "## FDM split (256 mm bed)", "", f"Top-case seam follows key boundaries at x = {', '.join(f'{x:.2f}' for x in split_info['_seam_xs'])} (rows F→bottom).", "",
                  "| Part | Bounding box mm |", "|---|---|"]
        lines += [f"| {n} | {a:.1f} × {b:.1f} × {c:.1f} |" for n, (a, b, c) in ((k, v) for k, v in split_info.items() if not k.startswith("_"))]
    (OUT / "fit_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    if do_render:
        print("render meshes ...")
        rd = OUT / "render"
        for n, s in parts.items():
            export_stl(s, rd / f"{n}.stl", tol=0.01, ang=0.1)
        export_stl(switch_solid(), rd / "switch.stl")
        export_stl(stem_solid(), rd / "stem.stl")
        export_stl(knob_solid(), rd / "knob.stl", tol=0.01, ang=0.1)
        for u in sorted({k["u"] for k in KEYS}):
            export_stl(keycap_solid(u), rd / f"keycap_{u:g}u.stl", tol=0.008, ang=0.08)
        glass, lcd = env_touchbar()
        export_stl(lcd, rd / "touch_lcd.stl")
        panel, pcb = env_screen()
        export_stl(pcb, rd / "screen_pcb.stl")
        b_pcb, b_parts = env_board()
        export_stl(b_pcb, rd / "mcu_pcb.stl")
        export_stl(b_parts, rd / "mcu_parts.stl")
        export_stl(env_encoder(), rd / "encoder.stl")
        m_pcb, m_parts = env_mcp_board()
        export_stl(m_pcb, rd / "mcp_pcb.stl")
        export_stl(m_parts, rd / "mcp_parts.stl")
        for k in ALLKEYS:
            s = stab_offsets(k["u"])
            k["stab"] = s
        place = dict(tilt_deg=TILT, y0=Y0, z0=Z0, bezel=BEZ, keycap=KC, sw=SW, keys=ALLKEYS,
                     touchbar=dict(center=[TB["center_x"], TB["center_v"]], glass=TB["glass"], active=TB["active"]),
                     screen=dict(center=SS["center"], panel=SS["panel"], active=SS["active"], recess=SS["recess"]),
                     encoder=ENC, usb=list(usb_center()), depth=DEP, width=W, floor=FLOOR, zb=ZB)
        (rd / "placements.json").write_text(json.dumps(place, indent=1), encoding="utf-8")

        # full assembly STEP (case + real-part envelopes) for checking in any CAD tool
        asm = cq.Assembly(name="STRIP84")
        col = {"case": cq.Color(0.12, 0.12, 0.13), "part": cq.Color(0.6, 0.6, 0.62), "glass": cq.Color(0.05, 0.05, 0.06), "pcb": cq.Color(0.1, 0.35, 0.2)}
        asm.add(top, name="top_case", color=col["case"])
        asm.add(bottom, name="bottom_plate", color=col["case"])
        asm.add(cassette, name="touchbar_cassette", color=col["case"])
        asm.add(sled, name="mcu_sled", color=col["case"])
        asm.add(retainer, name="screen_retainer", color=col["case"])
        asm.add(glass, name="touchbar_glass", color=col["glass"])
        asm.add(lcd, name="touchbar_lcd_envelope", color=col["pcb"])
        asm.add(panel, name="side_screen_panel", color=col["glass"])
        asm.add(pcb, name="side_screen_pcb", color=col["pcb"])
        asm.add(b_pcb.fuse(b_parts), name="esp32s3_board", color=col["pcb"])
        asm.add(env_encoder(), name="ec11", color=col["part"])
        # switches / keycaps / knob are added as shared instances so the STEP stays small
        sw = switch_solid()
        caps = {u: keycap_solid(u) for u in sorted({k["u"] for k in KEYS})}
        for i, k in enumerate(ALLKEYS):
            asm.add(sw, name=f"switch_{i:02d}", color=cq.Color(0.2, 0.4, 0.8),
                    loc=cq.Location(cq.Vector(*l2w(k["x"], k["v"], 0)), cq.Vector(1, 0, 0), TILT))
            asm.add(caps[k["u"]], name=f"keycap_{i:02d}", color=col["part"],
                    loc=cq.Location(cq.Vector(*l2w(k["x"], k["v"], KC["skirt_above_plate"])), cq.Vector(1, 0, 0), TILT))
        kn = knob_solid()
        for i, c in enumerate(ENCS):
            asm.add(kn, name=f"knob_{i + 1}", color=col["part"],
                    loc=cq.Location(cq.Vector(*l2w(*c, BEZ + 0.8)), cq.Vector(1, 0, 0), TILT))
        asm.save(str(OUT / "step" / "STRIP84_assembly.step"))

    print("done, fails =", fails)
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
