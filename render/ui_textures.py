#!/usr/bin/env python3
"""Draw the Touch Bar and side-screen UI used as emissive textures in the renders.

Touch Bar texture covers the whole cover glass (357 x 30 mm); the 349 x 22 mm active
area is drawn, the rest stays black (glass mask).  Side screen = 240 x 280 px panel at 4x.
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
D = json.loads((ROOT / "design" / "strip84.json").read_text(encoding="utf-8"))
OUT = Path(__file__).resolve().parent / "tex"
FONT_DIR = Path("/usr/share/fonts/opentype/inter")

BG = (6, 7, 8)
TILE = (26, 29, 31)
TILE_HI = (36, 40, 43)
TXT = (226, 228, 226)
DIM = (128, 134, 136)
ACC = (232, 128, 64)        # copper / amber, matches the Esc keycap
OK = (120, 200, 150)


def font(size, weight="Medium"):
    for name in (f"Inter-{weight}.otf", "Inter-Regular.otf"):
        p = FONT_DIR / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def icon(d, kind, cx, cy, s, col):
    w = max(2, int(s * 0.09))
    if kind == "terminal":
        d.rounded_rectangle([cx - s * .55, cy - s * .42, cx + s * .55, cy + s * .42], radius=s * .1, outline=col, width=w)
        d.line([cx - s * .32, cy - s * .15, cx - s * .12, cy, cx - s * .32, cy + s * .15], fill=col, width=w, joint="curve")
        d.line([cx - s * .02, cy + s * .17, cx + s * .28, cy + s * .17], fill=col, width=w)
    elif kind == "build":
        d.polygon([(cx - s * .1, cy - s * .5), (cx - s * .4, cy + s * .08), (cx - s * .02, cy + s * .08),
                   (cx - s * .12, cy + s * .5), (cx + s * .4, cy - s * .12), (cx + s * .02, cy - s * .12), (cx + s * .14, cy - s * .5)], fill=col)
    elif kind == "tests":
        d.ellipse([cx - s * .45, cy - s * .45, cx + s * .45, cy + s * .45], outline=col, width=w)
        d.line([cx - s * .2, cy + s * .02, cx - s * .04, cy + s * .18, cx + s * .24, cy - s * .16], fill=col, width=w, joint="curve")
    elif kind == "git":
        r = s * .1
        pts = [(cx - s * .25, cy - s * .35), (cx - s * .25, cy + s * .35), (cx + s * .25, cy - s * .1)]
        d.line([pts[0], pts[1]], fill=col, width=w)
        d.line([(cx + s * .25, cy - s * .1 + r), (cx + s * .25, cy + s * .05), (cx - s * .25, cy + s * .2)], fill=col, width=w)
        for x, y in pts:
            d.ellipse([x - r * 1.4, y - r * 1.4, x + r * 1.4, y + r * 1.4], fill=BG, outline=col, width=w)
    elif kind == "speaker":
        d.polygon([(cx - s * .45, cy - s * .15), (cx - s * .25, cy - s * .15), (cx, cy - s * .4), (cx, cy + s * .4),
                   (cx - s * .25, cy + s * .15), (cx - s * .45, cy + s * .15)], fill=col)
        d.arc([cx - s * .15, cy - s * .3, cx + s * .3, cy + s * .3], -50, 50, fill=col, width=w)
        d.arc([cx - s * .15, cy - s * .5, cx + s * .5, cy + s * .5], -50, 50, fill=col, width=w)
    elif kind == "sun":
        d.ellipse([cx - s * .2, cy - s * .2, cx + s * .2, cy + s * .2], fill=col)
        import math
        for i in range(8):
            a = i * math.pi / 4
            d.line([cx + math.cos(a) * s * .32, cy + math.sin(a) * s * .32, cx + math.cos(a) * s * .46, cy + math.sin(a) * s * .46], fill=col, width=w)


def touchbar(ppm=10):
    gw, gh, _ = D["touchbar"]["glass"]
    aw, ah = D["touchbar"]["active"]
    W, H = int(gw * ppm), int(gh * ppm)
    img = Image.new("RGB", (W, H), (0, 0, 0))
    ax0, ay0 = int((gw - aw) / 2 * ppm), int((gh - ah) / 2 * ppm)
    ax1, ay1 = ax0 + int(aw * ppm), ay0 + int(ah * ppm)
    d = ImageDraw.Draw(img)
    d.rectangle([ax0, ay0, ax1, ay1], fill=BG)
    pad = int(1.6 * ppm)
    y0, y1 = ay0 + pad, ay1 - pad
    hh = y1 - y0
    x = ax0 + pad
    f_lab = font(int(3.0 * ppm), "SemiBold")
    f_small = font(int(2.3 * ppm), "Medium")
    f_big = font(int(4.2 * ppm), "SemiBold")

    # left: device/target pill
    pw = int(30 * ppm)
    d.rounded_rectangle([x, y0, x + pw, y1], radius=hh // 2, fill=TILE)
    d.ellipse([x + hh * .35, y0 + hh * .38, x + hh * .35 + hh * .24, y0 + hh * .62], fill=OK)
    d.text((x + hh * .85, (y0 + y1) / 2), "USB · A", font=f_lab, fill=TXT, anchor="lm")
    x += pw + pad

    # app actions
    for label, ic, active in (("Terminal", "terminal", False), ("Build", "build", True), ("Tests", "tests", False), ("Git", "git", False)):
        bw = int(36 * ppm)
        d.rounded_rectangle([x, y0, x + bw, y1], radius=int(1.6 * ppm), fill=TILE_HI if active else TILE)
        col = ACC if active else TXT
        icon(d, ic, x + hh * .62, (y0 + y1) / 2, hh * .52, col)
        d.text((x + hh * 1.15, (y0 + y1) / 2), label, font=f_lab, fill=col, anchor="lm")
        x += bw + pad

    # build progress
    bw = int(62 * ppm)
    d.rounded_rectangle([x, y0, x + bw, y1], radius=int(1.6 * ppm), fill=TILE)
    d.text((x + pad, y0 + hh * .32), "project.build", font=f_small, fill=DIM, anchor="lm")
    d.text((x + bw - pad, y0 + hh * .32), "42%", font=f_small, fill=ACC, anchor="rm")
    by = y0 + hh * .72
    d.rounded_rectangle([x + pad, by - 4, x + bw - pad, by + 4], radius=4, fill=(48, 52, 55))
    d.rounded_rectangle([x + pad, by - 4, x + pad + (bw - 2 * pad) * .42, by + 4], radius=4, fill=ACC)
    x += bw + pad

    # volume slider
    sw = int(82 * ppm)
    cy = (y0 + y1) / 2
    icon(d, "speaker", x + hh * .4, cy, hh * .55, TXT)
    sx0, sx1 = x + hh * .95, x + sw - hh * 1.3
    d.rounded_rectangle([sx0, cy - 5, sx1, cy + 5], radius=5, fill=(52, 56, 59))
    tx = sx0 + (sx1 - sx0) * .64
    d.rounded_rectangle([sx0, cy - 5, tx, cy + 5], radius=5, fill=TXT)
    d.ellipse([tx - hh * .3, cy - hh * .3, tx + hh * .3, cy + hh * .3], fill=(245, 245, 242))
    d.text((x + sw - hh * .2, cy), "64", font=f_lab, fill=TXT, anchor="rm")
    x += sw + pad

    # clock
    d.text((ax1 - pad, cy), "14:32", font=f_big, fill=TXT, anchor="rm")

    # soft bloom
    glow = img.filter(ImageFilter.GaussianBlur(6))
    img = Image.blend(img, glow, 0.18)
    return img


def side_screen(scale=4):
    W, H = 240 * scale, 280 * scale
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    s = scale
    d.text((16 * s, 22 * s), "TARGET", font=font(13 * s, "SemiBold"), fill=DIM, anchor="lm")
    d.ellipse([206 * s, 16 * s, 218 * s, 28 * s], fill=OK)
    d.text((14 * s, 84 * s), "A", font=font(92 * s, "Bold"), fill=TXT, anchor="lm")
    d.text((92 * s, 66 * s), "USB-C", font=font(20 * s, "SemiBold"), fill=TXT, anchor="lm")
    d.text((92 * s, 92 * s), "MacBook Pro", font=font(15 * s, "Medium"), fill=DIM, anchor="lm")
    d.line([16 * s, 140 * s, 224 * s, 140 * s], fill=(40, 44, 46), width=2 * s)
    d.text((16 * s, 166 * s), "B", font=font(28 * s, "Bold"), fill=DIM, anchor="lm")
    d.text((48 * s, 160 * s), "BLE", font=font(15 * s, "SemiBold"), fill=DIM, anchor="lm")
    d.text((48 * s, 178 * s), "iPad · standby", font=font(13 * s, "Medium"), fill=(90, 96, 98), anchor="lm")
    # layer pills
    for i, lab in enumerate(("BASE", "FN", "CODE")):
        x0 = 16 * s + i * 70 * s
        on = i == 0
        d.rounded_rectangle([x0, 214 * s, x0 + 62 * s, 238 * s], radius=12 * s, fill=ACC if on else (30, 33, 35))
        d.text((x0 + 31 * s, 226 * s), lab, font=font(12 * s, "SemiBold"), fill=(20, 12, 8) if on else DIM, anchor="mm")
    d.text((16 * s, 262 * s), "knob 1 → target   knob 2 → volume", font=font(11 * s, "Medium"), fill=(84, 90, 92), anchor="lm")
    return img


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    touchbar().save(OUT / "touchbar.png")
    side_screen().save(OUT / "side_screen.png")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
