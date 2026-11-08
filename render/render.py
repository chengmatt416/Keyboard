#!/usr/bin/env python3
"""STRIP/84 photoreal renders (Blender Cycles via the `bpy` module).

Needs: cad/out/render/* from cad/build_case.py and render/tex/* from render/ui_textures.py
Usage: python render/render.py [--views hero,top,side,rear,detail,exploded] [--samples 160] [--scale 1.0]
"""
import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parent.parent
MESH = ROOT / "cad" / "out" / "render"
TEX = ROOT / "render" / "tex"
OUT = ROOT / "renders"
PL = json.loads((MESH / "placements.json").read_text(encoding="utf-8"))
FONT = "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf"

TILT = math.radians(PL["tilt_deg"])
LOCAL = Matrix.Translation((0, PL["y0"], PL["z0"])) @ Matrix.Rotation(TILT, 4, "X")
KC, SW = PL["keycap"], PL["sw"]
BEZ = PL["bezel"]

MODS = {"Esc", "Tab", "Caps", "Shift", "Ctrl", "Win", "Alt", "RAlt", "Fn", "RCtrl", "Backspace", "Enter", "RShift",
        "Del", "PgUp", "PgDn", "End", "Up", "Down", "Left", "Right", "PrtSc", "Ins", "Pause",
        "M1", "M2", "M3", "M4", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"}
LEGEND = {"Esc": "esc", "Tab": "tab", "Caps": "caps", "Shift": "shift", "RShift": "shift", "Ctrl": "ctrl", "RCtrl": "ctrl",
          "Win": "win", "Alt": "alt", "RAlt": "alt", "Fn": "fn", "Backspace": "backspace", "Enter": "enter", "Del": "del",
          "PgUp": "pg up", "PgDn": "pg dn", "End": "end", "Up": "↑", "Down": "↓", "Left": "←", "Right": "→",
          "PrtSc": "prt sc", "Ins": "ins", "Pause": "pause", "Space": ""}


# --------------------------------------------------------------------------- materials
def principled(name, base, metallic=0.0, rough=0.5, **kw):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*base, 1)
    b.inputs["Metallic"].default_value = metallic
    b.inputs["Roughness"].default_value = rough
    for k, v in kw.items():
        b.inputs[k].default_value = v
    return m


def add_bump(m, scale=900.0, strength=0.06, distance=0.0002):
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = scale
    nz.inputs["Detail"].default_value = 2.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = distance
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def brushed(m, strength=0.035):
    """Fine bead-blast texture + a hint of anisotropy for anodised aluminium."""
    add_bump(m, scale=2500.0, strength=strength, distance=0.00005)
    b = m.node_tree.nodes["Principled BSDF"]
    try:
        b.inputs["Anisotropic"].default_value = 0.25
    except KeyError:
        pass
    return m


def screen_mat(name, img_path, strength, matte=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(str(img_path))
    tex.interpolation = "Cubic"
    b.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1)
    b.inputs["Roughness"].default_value = 0.30 if matte else 0.06
    b.inputs["Coat Weight"].default_value = 0.0 if matte else 1.0
    b.inputs["Coat Roughness"].default_value = 0.02
    nt.links.new(tex.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = strength
    return m


def build_materials(colorway):
    M = {}
    case_col = {"graphite": (0.018, 0.019, 0.021), "stone": (0.42, 0.41, 0.39)}[colorway]
    M["case"] = add_bump(principled("MJF PA12 dyed", case_col, 0.0, 0.62, **{"Coat Weight": 0.12, "Coat Roughness": 0.35}))
    M["silver"] = brushed(principled("Alu silver", (0.80, 0.80, 0.79), 1.0, 0.30))
    M["graphite"] = brushed(principled("Alu graphite", (0.13, 0.135, 0.145), 1.0, 0.33))
    M["copper"] = brushed(principled("Alu copper", (0.86, 0.42, 0.22), 1.0, 0.30))
    M["leg_dark"] = principled("Legend dark", (0.012, 0.012, 0.014), 0.0, 0.6)
    M["leg_light"] = principled("Legend light", (0.92, 0.92, 0.90), 0.0, 0.5)
    M["knob"] = brushed(principled("Alu knob", (0.78, 0.78, 0.77), 1.0, 0.22), 0.02)
    M["housing"] = principled("Switch housing", (0.02, 0.02, 0.022), 0.0, 0.35)
    M["stem"] = principled("Blue stem", (0.05, 0.25, 0.85), 0.0, 0.3)
    M["rubber"] = principled("Rubber", (0.01, 0.01, 0.01), 0.0, 0.85)
    M["pcb"] = principled("PCB", (0.03, 0.07, 0.05), 0.0, 0.4, **{"Coat Weight": 0.6})
    M["chip"] = principled("Chip", (0.55, 0.56, 0.57), 1.0, 0.35)
    M["mask"] = principled("Glass mask", (0.0, 0.0, 0.0), 0.0, 0.05, **{"Coat Weight": 1.0, "Coat Roughness": 0.02})
    M["floor"] = principled("Backdrop", (0.62, 0.60, 0.57), 0.0, 0.55)
    M["touchbar"] = screen_mat("Touch Bar (AG glass)", TEX / "touchbar.png", 3.2, matte=True)
    M["screen"] = screen_mat("Side screen", TEX / "side_screen.png", 2.2)
    return M


# --------------------------------------------------------------------------- geometry helpers
ROOTOBJ = None


def root():
    global ROOTOBJ
    if ROOTOBJ is None:
        ROOTOBJ = bpy.data.objects.new("STRIP84", None)
        bpy.context.scene.collection.objects.link(ROOTOBJ)
        ROOTOBJ.scale = (0.001, 0.001, 0.001)
    return ROOTOBJ


def import_stl(name, path, mat, smooth_deg=32.0):
    bpy.ops.wm.stl_import(filepath=str(path))
    ob = bpy.context.selected_objects[0]
    ob.name = name
    me = ob.data
    me.materials.clear()
    me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    try:
        me.set_sharp_from_angle(angle=math.radians(smooth_deg))
    except Exception:
        pass
    ob.parent = root()
    return ob


def instance(src, name, matrix, mat=None):
    ob = bpy.data.objects.new(name, src.data)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = root()
    ob.matrix_basis = matrix
    if mat is not None:
        ob.material_slots[0].link = "OBJECT"
        ob.material_slots[0].material = mat
    return ob


def rrect_prism(name, w, h, r, t, mat, n=10):
    """Rounded-rect slab centred at the origin, top at z=0, planar UVs on the top face."""
    import bmesh
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180), (w / 2 - r, -h / 2 + r, 270)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    top = [bm.verts.new((x, y, 0)) for x, y in pts]
    bot = [bm.verts.new((x, y, -t)) for x, y in pts]
    ft = bm.faces.new(top)
    fb = bm.faces.new(list(reversed(bot)))
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        bm.faces.new((top[j], top[i], bot[i], bot[j]))
    uv = bm.loops.layers.uv.new()
    for f in bm.faces:
        for l in f.loops:
            x, y, _ = l.vert.co
            l[uv].uv = ((x + w / 2) / w, (y + h / 2) / h)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mat)
    ob.parent = root()
    return ob


def text_obj(name, body, size, mat, matrix):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.font = FONT_DATA
    cu.size = size
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.extrude = 0.03
    cu.resolution_u = 6
    ob = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(ob)
    cu.materials.append(mat)
    ob.parent = root()
    ob.matrix_basis = matrix
    return ob


def L(x, v, w):
    return LOCAL @ Matrix.Translation((x, v, w))


# --------------------------------------------------------------------------- scene
def build_scene(M, explode=False, cable=False):
    E = (lambda dz: Matrix.Translation((0, 0, dz))) if explode else (lambda dz: Matrix.Identity(4))
    ex = {"caps": 105, "switch": 58, "knob": 78, "glass": 40, "screen": -34, "enc": -30, "ret": -46, "cas": -38,
          "mcp": -60, "mcu": -62, "bottom": -88} if explode else {}
    g = lambda k: ex.get(k, 0)
    objs = {}
    objs["top"] = import_stl("top_case", MESH / "top_case.stl", M["case"], 25)
    objs["bottom"] = import_stl("bottom_plate", MESH / "bottom_plate.stl", M["case"], 25)
    objs["bottom"].matrix_basis = E(g("bottom"))
    objs["cas"] = import_stl("touchbar_cassette", MESH / "touchbar_cassette.stl", M["case"], 25)
    objs["cas"].matrix_basis = E(g("cas"))
    objs["sled"] = import_stl("mcu_sled", MESH / "mcu_sled.stl", M["case"], 25)
    objs["sled"].matrix_basis = E(g("mcu"))
    objs["ret"] = import_stl("screen_retainer", MESH / "screen_retainer.stl", M["case"], 25)
    objs["ret"].matrix_basis = E(g("ret"))
    if explode:
        for n, mat, k in (("mcu_pcb", M["pcb"], "mcu"), ("mcu_parts", M["chip"], "mcu"), ("mcp_pcb", M["pcb"], "mcp"), ("mcp_parts", M["housing"], "mcp"),
                          ("screen_pcb", M["pcb"], "screen"), ("encoder", M["chip"], "enc"), ("touch_lcd", M["housing"], "glass")):
            o = import_stl(n, MESH / f"{n}.stl", mat)
            o.matrix_basis = E(g(k))

    # feet
    for x, y in ((22, 18), (344, 18), (22, 153), (344, 153)):
        bpy.ops.mesh.primitive_cylinder_add(radius=6.35, depth=3.0, location=(0, 0, 0))
        f = bpy.context.object
        f.data.materials.append(M["rubber"])
        f.parent = root()
        f.matrix_basis = E(g("bottom")) @ Matrix.Translation((x, y, 1.5))

    # keycaps, legends, switches
    cap_src = {}
    sw_src = import_stl("switch_src", MESH / "switch.stl", M["housing"])
    stem_src = import_stl("stem_src", MESH / "stem.stl", M["stem"])
    sw_src.hide_render = stem_src.hide_render = True
    sw_src.hide_viewport = stem_src.hide_viewport = True
    for k in PL["keys"]:
        u = k["u"]
        if u not in cap_src:
            cap_src[u] = import_stl(f"cap_src_{u:g}", MESH / f"keycap_{u:g}u.stl", M["silver"], 40)
            cap_src[u].hide_render = cap_src[u].hide_viewport = True
        lab = k["label"]
        mat = M["copper"] if lab == "Esc" else (M["graphite"] if lab in MODS else M["silver"])
        legm = M["leg_dark"] if mat is not M["graphite"] else M["leg_light"]
        mtx = E(g("caps")) @ L(k["x"], k["v"], KC["skirt_above_plate"])
        instance(cap_src[u], f"cap_{lab}", mtx, mat)
        body = LEGEND.get(lab, lab)
        if body:
            size = 5.2 if len(body) == 1 else (4.0 if len(body) <= 3 else 3.0)
            tz = KC["height"] - KC["dish"] + 0.07
            text_obj(f"leg_{lab}", body, size, legm, E(g("caps")) @ L(k["x"], k["v"] + 0.3, KC["skirt_above_plate"] + tz))
        instance(sw_src, f"sw_{lab}", E(g("switch")) @ L(k["x"], k["v"], 0))
        instance(stem_src, f"stem_{lab}", E(g("switch")) @ L(k["x"], k["v"], 0))

    # knob
    kn = None
    for i, (ex_, ev_) in enumerate(PL["encoder"]["centers"]):
        if kn is None:
            kn = import_stl("knob_1", MESH / "knob.stl", M["knob"], 30)
            ob = kn
        else:
            ob = instance(kn, f"knob_{i + 1}", Matrix.Identity(4))
        ob.matrix_basis = E(g("knob")) @ L(ex_, ev_, BEZ + 0.8) @ Matrix.Rotation(math.radians(-28 + 70 * i), 4, "Z")

    # touch bar glass with UI
    tb = PL["touchbar"]
    gw, gh, gt = tb["glass"]
    glass = rrect_prism("touchbar_glass", gw, gh, 2.0, gt, M["touchbar"])
    glass.matrix_basis = E(g("glass")) @ L(tb["center"][0], tb["center"][1], BEZ - 0.02)

    # side screen
    sc = PL["screen"]
    pw, ph, pt = sc["panel"]
    aw, ah = sc["active"]
    ptop = BEZ - sc["recess"]
    mask = rrect_prism("screen_mask", pw, ph, 1.0, pt, M["mask"])
    mask.matrix_basis = E(g("screen")) @ L(sc["center"][0], sc["center"][1], ptop - 0.01)
    disp = rrect_prism("screen_disp", aw, ah, 2.6, 0.2, M["screen"])
    disp.matrix_basis = E(g("screen")) @ L(sc["center"][0], sc["center"][1], ptop)

    if cable:   # USB-C cable plugged into the native port
        ux, uz = PL["usb"]
        y0 = PL["depth"] - 0.6
        plug = rrect_prism("usb_overmold", 12.2, 6.6, 2.4, 22.0, M["rubber"])
        plug.matrix_basis = Matrix.Translation((ux, y0, uz)) @ Matrix.Rotation(math.radians(90), 4, "X") @ Matrix.Translation((0, 0, 0))
        shell = rrect_prism("usb_shell", 8.3, 2.5, 1.1, 6.0, M["chip"])
        shell.matrix_basis = Matrix.Translation((ux, y0 - 6.0, uz)) @ Matrix.Rotation(math.radians(90), 4, "X")
        bpy.ops.mesh.primitive_cylinder_add(radius=2.0, depth=180, vertices=48)
        cb = bpy.context.object
        cb.data.materials.append(M["rubber"])
        for p_ in cb.data.polygons:
            p_.use_smooth = True
        cb.parent = root()
        ang = math.atan2(uz - 2.0, 180)
        cb.matrix_basis = (Matrix.Translation((ux, y0 + 22.0, uz)) @ Matrix.Rotation(-ang, 4, "X")
                           @ Matrix.Translation((0, 90, 0)) @ Matrix.Rotation(math.radians(90), 4, "X"))
    return objs


def studio(M, floor_z=0.0):
    sc = bpy.context.scene
    # sweep backdrop
    import bmesh
    me = bpy.data.meshes.new("sweep")
    bm = bmesh.new()
    prof = []
    R = 0.6
    for i in range(25):
        a = math.radians(90 * i / 24)
        prof.append((R - R * math.cos(a) * 0 + 0, R - R * math.sin(a)))
    pts = [(-2.0, 0.0)] + [(1.0 + R * math.sin(math.radians(90 * i / 24)), R - R * math.cos(math.radians(90 * i / 24))) for i in range(25)] + [(1.6, 2.5)]
    row = []
    for xx in (-3.0, 3.0):
        row.append([bm.verts.new((xx, y, z + floor_z)) for y, z in pts])
    for i in range(len(pts) - 1):
        bm.faces.new((row[0][i], row[1][i], row[1][i + 1], row[0][i + 1]))
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("sweep", me)
    sc.collection.objects.link(ob)
    me.materials.append(M["floor"])
    for p in me.polygons:
        p.use_smooth = True

    w = bpy.data.worlds.new("World")
    sc.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.55, 0.56, 0.58, 1)
    bg.inputs["Strength"].default_value = 0.35


def area(name, loc, target, size, power, color=(1, 1, 1), shape="RECTANGLE", size_y=None):
    ld = bpy.data.lights.new(name, "AREA")
    ld.energy = power
    ld.shape = shape
    ld.size = size
    if size_y:
        ld.size_y = size_y
    ld.color = color
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    d = Vector(target) - Vector(loc)
    ob.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return ob


def camera(name, loc, target, lens=60, ortho=None, fstop=None, focus=None, shift=(0, 0)):
    cd = bpy.data.cameras.new(name)
    if ortho:
        cd.type = "ORTHO"
        cd.ortho_scale = ortho
    else:
        cd.lens = lens
    cd.sensor_width = 36
    cd.shift_x, cd.shift_y = shift
    cd.clip_start = 0.01
    cd.clip_end = 20
    if fstop:
        cd.dof.use_dof = True
        cd.dof.aperture_fstop = fstop
        cd.dof.focus_distance = focus if focus else (Vector(target) - Vector(loc)).length
    ob = bpy.data.objects.new(name, cd)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = (Vector(target) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    return ob


def setup_render(samples, w, h):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.015
    sc.cycles.use_denoising = True
    try:
        sc.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    sc.cycles.max_bounces = 10
    sc.cycles.glossy_bounces = 6
    sc.cycles.transparent_max_bounces = 4
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    sc.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            pass
    sc.view_settings.exposure = 0.0
    sc.render.threads_mode = "AUTO"


CENTER = Vector((0.183, 0.0795, 0.018))


VIEWS = {
    # name: (camera kwargs, lights, resolution)
    "hero": dict(cam=dict(loc=(0.183 - 0.30, 0.0795 - 0.47, 0.30), target=(0.176, 0.084, 0.006), lens=62, fstop=32), res=(2400, 1500), expo=0.0),
    "top": dict(cam=dict(loc=(0.183, 0.0795, 1.2), target=(0.183, 0.0795, 0.0), ortho=0.405), res=(2400, 1320), expo=-0.15),
    "side": dict(cam=dict(loc=(0.183 + 1.0, 0.0795, 0.030), target=(0.183, 0.0795, 0.030), ortho=0.205), res=(2400, 820), expo=0.45),
    "rear": dict(cam=dict(loc=(-0.13, 0.159 + 0.29, 0.095), target=(0.075, 0.138, 0.012), lens=70, fstop=9), res=(2400, 1500), expo=0.1),
    "detail": dict(cam=dict(loc=(0.036 - 0.07, 0.072 - 0.215, 0.235), target=(0.040, 0.074, 0.018), lens=72, fstop=11), res=(2400, 1600), expo=0.1),
    "exploded": dict(cam=dict(loc=(0.183 - 0.42, 0.0795 - 0.62, 0.48), target=(0.183, 0.084, 0.018), lens=55, fstop=32), res=(2400, 1800), expo=0.05),
}


def lights_for(view):
    c = CENTER
    if view == "side":
        area("key", (c.x + 0.6, c.y - 0.5, c.z + 0.6), c, 1.2, 16)
        area("rim", (c.x + 0.2, c.y + 0.7, c.z + 0.35), c, 0.8, 9)
        area("fill", (c.x + 0.8, c.y + 0.1, c.z + 0.05), c, 0.6, 2.5)
        return
    area("key", (c.x - 0.55, c.y - 0.35, c.z + 0.75), c, 1.0, 16, size_y=0.6)
    area("fill", (c.x + 0.75, c.y - 0.3, c.z + 0.35), c, 1.2, 4.5)
    area("rim", (c.x - 0.1, c.y + 0.75, c.z + 0.40), c, 1.4, 11, size_y=0.25)
    if view != "top":
        area("top", (c.x, c.y, c.z + 1.0), c, 0.9, 5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", default=",".join(VIEWS))
    ap.add_argument("--samples", type=int, default=160)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--colorway", default="graphite")
    ap.add_argument("--suffix", default="")
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    OUT.mkdir(exist_ok=True)
    global FONT_DATA
    for view in a.views.split(","):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        global ROOTOBJ
        ROOTOBJ = None
        FONT_DATA = bpy.data.fonts.load(FONT)
        M = build_materials(a.colorway)
        build_scene(M, explode=(view == "exploded"), cable=(view == "rear"))
        studio(M, floor_z=-0.090 if view == "exploded" else 0.0)
        lights_for(view)
        v = VIEWS[view]
        cam = camera(view, **v["cam"])
        bpy.context.scene.camera = cam
        w, h = v["res"]
        setup_render(a.samples, int(w * a.scale), int(h * a.scale))
        bpy.context.scene.view_settings.exposure = v["expo"]
        out = OUT / f"STRIP84_{view}{a.suffix}.png"
        bpy.context.scene.render.filepath = str(out)
        print("rendering", view, "->", out, flush=True)
        bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
