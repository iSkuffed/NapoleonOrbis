#!/usr/bin/env python3
"""Generate in-game flag image sets for every non-vanilla faction.

  python tools/flags.py          build work/mods/flags/ui/flags/gn_<key>/* + data/world1805/flags_sources.json
                                 + work/flags_src/contact_sheet.png
  python tools/flags.py check    assert every target faction has all 24 files at the right size/format

Layout copied from vanilla ui/flags/<faction>/ (data.pack; see research/09): 24 files
  large.tga 512x256 RGB24 raw | large.dds 512x256 DXT5+mips | flag_132.tga 132x66 RGBA RLE
  flag_animation0000..0011.tga 200x100 RGBA RLE | hud_left/hud_right.tga 40x79 RGBA RLE
  id_flag_infantry/cavalry/artillery.tga 112x64 RGBA raw | id_flag_naval.tga 64x64 RGBA raw
  mini_flag.tga 44x22 RGBA RLE | portrait_flags.tga 140x116 RGBA raw | small.tga 19x24 RGBA RLE
All TGAs are bottom-left origin (descriptor 0x08 / 0x00) like vanilla.

Art: every image is drawn here from code (no downloads, no CA art). Historical designs are
plain geometry (stripes, canton, crescent); the rest are a colour_primary/secondary pattern
picked from the faction key. A target = every faction whose "vanilla" field is not true.
"""
import json, math, os, struct, subprocess, sys, tempfile, zlib
import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACTIONS = os.path.join(ROOT, "data/world1805/factions.json")
SOURCES = os.path.join(ROOT, "data/world1805/flags_sources.json")
OUT = os.path.join(ROOT, "work/mods/flags/ui/flags")
DIR = lambda key: "gn_" + key   # own prefix: vanilla data.pack has morocco / mysore / united_states (Empire sets without the unit id flags)
SHEET = os.path.join(ROOT, "work/flags_src/contact_sheet.png")
MW, MH = 1024, 512  # master canvas (2:1), downsampled for every output

# name -> (width, height, mode, tga type 2 raw / 10 RLE, bpp); dds checked separately
SPEC = {"large.tga": (512, 256, 24, 2), "flag_132.tga": (132, 66, 32, 10), "hud_left.tga": (40, 79, 32, 10),
        "hud_right.tga": (40, 79, 32, 10), "id_flag_infantry.tga": (112, 64, 32, 2),
        "id_flag_cavalry.tga": (112, 64, 32, 2), "id_flag_artillery.tga": (112, 64, 32, 2),
        "id_flag_naval.tga": (64, 64, 32, 2), "mini_flag.tga": (44, 22, 32, 10),
        "portrait_flags.tga": (140, 116, 32, 2), "small.tga": (19, 24, 32, 10)}
SPEC.update({f"flag_animation{i:04d}.tga": (200, 100, 32, 10) for i in range(12)})
FILES = sorted(SPEC) + ["large.dds"]

# --- historical designs (own drawing of simple geometry); everything else is "pattern" ----------
RED, WHITE, BLACK, YEL = (200, 16, 46), (255, 255, 255), (0, 0, 0), (250, 205, 20)
HIST = {
    "united_states": ("usa1795", {}, "15 stars, 15 stripes (1795-1818); stars in 3 rows of 5"),
    "haiti": ("hbands", {"c": [BLACK, RED]}, "Dessalines 1804-06 black/red; orientation (horizontal) and the 'Liberte ou la Mort' motto not rendered"),
    "morocco": ("plain", {"c": RED}, "plain red Alaouite flag; star added only in 1915"),
    "egypt": ("crescent", {"c": RED, "fg": WHITE}, "Ottoman-style red field, white crescent and star; eyalet flag assumed, not documented for Muhammad Ali 1805"),
    "tunis": ("crescent", {"c": RED, "fg": WHITE}, "red field with crescent and star; Husainid flag in exactly 1805 uncertain"),
    "oman": ("plain", {"c": RED}, "plain red Omani/Muscat flag"),
    "siam": ("plain", {"c": RED}, "plain red Siamese flag (white elephant only from 1817)"),
    "qing": ("border", {"c": (255, 205, 0), "b": RED}, "Bordered Yellow banner of the Eight Banners (yellow, red border); dragon flag is 1862, no 1805 national flag existed"),
    "dai_viet": ("plain", {"c": (245, 200, 20)}, "plain yellow Nguyen banner; exact Gia Long design uncertain"),
    "maratha_peshwa": ("hoist", {"c": (255, 153, 0), "h": (150, 30, 30)}, "saffron Bhagwa Dhwaj field + red hoist band (band added to tell Maratha houses apart; real flag plain saffron swallowtail)"),
    "maratha_scindia": ("hoist", {"c": (255, 153, 0), "h": (30, 120, 60)}, "saffron Bhagwa Dhwaj field + green hoist band (band added to tell Maratha houses apart)"),
    "maratha_holkar": ("hoist", {"c": (255, 153, 0), "h": (30, 60, 140)}, "saffron Bhagwa Dhwaj field + blue hoist band (band added to tell Maratha houses apart)"),
    "maratha_bhonsle": ("hoist", {"c": (255, 153, 0), "h": (240, 240, 240)}, "saffron Bhagwa Dhwaj field + white hoist band (band added to tell Maratha houses apart)"),
    "sikh_empire": ("plain", {"c": (255, 165, 0)}, "saffron Nishan Sahib field; khanda emblem omitted"),
    "nepal": ("border", {"c": (200, 20, 50), "b": (0, 56, 147)}, "crimson with blue border (Gorkha banner); sun/moon charge omitted, 1805 form uncertain"),
    "east_india_company": ("eic", {}, "13 red/white stripes, 1801 Union canton (St Patrick saltire simplified: not counter-changed)"),
    "russian_american_company": ("rac", {}, "1806 RAC flag: white-blue-red tricolour, black double-headed eagle canton (silhouette; crown, regalia and motto ribbon omitted)"),
}
# star/crescent charge helpers draw on a mask so they work over any field


def hexcol(c):
    return tuple(int(v) for v in c)


def star_poly(cx, cy, R, pts=5, rot=-math.pi / 2):
    r = R * 0.382 if pts == 5 else R * 0.5
    return [(cx + (R if i % 2 == 0 else r) * math.cos(rot + i * math.pi / pts),
             cy + (R if i % 2 == 0 else r) * math.sin(rot + i * math.pi / pts)) for i in range(pts * 2)]


def union_jack(w, h):
    im = Image.new("RGB", (w, h), (1, 33, 105))
    d = ImageDraw.Draw(im)
    for a, b in (((0, 0), (w, h)), ((0, h), (w, 0))):
        d.line([a, b], fill=WHITE, width=int(h * 0.2))
    for a, b in (((0, 0), (w, h)), ((0, h), (w, 0))):
        d.line([a, b], fill=RED, width=int(h * 0.07))
    d.rectangle([0, h * 0.5 - h * 0.17, w, h * 0.5 + h * 0.17], fill=WHITE)
    d.rectangle([w * 0.5 - h * 0.17, 0, w * 0.5 + h * 0.17, h], fill=WHITE)
    d.rectangle([0, h * 0.5 - h * 0.1, w, h * 0.5 + h * 0.1], fill=RED)
    d.rectangle([w * 0.5 - h * 0.1, 0, w * 0.5 + h * 0.1, h], fill=RED)
    return im


def stripes(d, colours, x0, y0, x1, y1, vertical=False):
    n = len(colours)
    for i, c in enumerate(colours):
        if vertical:
            d.rectangle([x0 + (x1 - x0) * i / n, y0, x0 + (x1 - x0) * (i + 1) / n, y1], fill=c)
        else:
            d.rectangle([x0, y0 + (y1 - y0) * i / n, x1, y0 + (y1 - y0) * (i + 1) / n], fill=c)


PATTERNS = ["hband", "vband", "diag", "cross", "saltire", "disc", "triangle", "quarters"]


def pattern(kind, p, s, d, im):
    W, H = im.size
    if kind == "hband":
        stripes(d, [p, s], 0, 0, W, H)
    elif kind == "vband":
        stripes(d, [p, s], 0, 0, W, H, True)
    elif kind == "diag":
        d.rectangle([0, 0, W, H], fill=p)
        d.polygon([(W, 0), (W, H), (0, H)], fill=s)
    elif kind == "cross":  # Nordic offset cross
        d.rectangle([0, 0, W, H], fill=p)
        d.rectangle([0, H * 0.4, W, H * 0.6], fill=s)
        d.rectangle([W * 0.3, 0, W * 0.45, H], fill=s)
    elif kind == "saltire":
        d.rectangle([0, 0, W, H], fill=p)
        for a, b in (((0, 0), (W, H)), ((0, H), (W, 0))):
            d.line([a, b], fill=s, width=int(H * 0.16))
    elif kind == "disc":
        d.rectangle([0, 0, W, H], fill=p)
        r = H * 0.3
        d.ellipse([W / 2 - r, H / 2 - r, W / 2 + r, H / 2 + r], fill=s)
    elif kind == "triangle":
        d.rectangle([0, 0, W, H], fill=s)
        d.polygon([(0, 0), (W * 0.55, H / 2), (0, H)], fill=p)
    elif kind == "quarters":
        d.rectangle([0, 0, W, H], fill=p)
        d.rectangle([0, 0, W / 2, H / 2], fill=s)
        d.rectangle([W / 2, H / 2, W, H], fill=s)


def paste_mask(im, colour, mask):
    im.paste(Image.new("RGB", im.size, colour), (0, 0), mask)


def crescent(im, fg):
    W, H = im.size
    m = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(m)
    cx, cy, r = W * 0.42, H / 2, H * 0.28
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    r2 = r * 0.8
    d.ellipse([cx + r * 0.3 - r2, cy - r2, cx + r * 0.3 + r2, cy + r2], fill=0)
    d.polygon(star_poly(W * 0.58, H / 2, H * 0.14), fill=255)
    paste_mask(im, fg, m)


def eagle(d, cx, cy, s, c=BLACK):
    """Double-headed eagle silhouette, s = height, centred on (cx, cy)."""
    P = lambda pts: [(cx + x * s, cy + y * s) for x, y in pts]
    for k in (1, -1):  # wings, then heads on necks
        d.polygon(P([(0.04 * k, -0.18), (0.62 * k, -0.48), (0.55 * k, -0.25), (0.6 * k, -0.2), (0.48 * k, 0.02), (0.5 * k, 0.08), (0.12 * k, 0.12)]), fill=c)
        d.polygon(P([(0.02 * k, -0.2), (0.16 * k, -0.38), (0.22 * k, -0.36), (0.1 * k, -0.15)]), fill=c)
        d.ellipse(P([(0.13 * k - 0.07, -0.47), (0.13 * k + 0.07, -0.33)]), fill=c)
        d.polygon(P([(0.18 * k, -0.43), (0.3 * k, -0.4), (0.19 * k, -0.37)]), fill=c)  # beak
    d.ellipse(P([(-0.13, -0.22), (0.13, 0.25)]), fill=c)  # body
    d.polygon(P([(-0.06, 0.2), (0.06, 0.2), (0.2, 0.5), (-0.2, 0.5)]), fill=c)  # tail


def draw_master(key, f):
    """Return (RGB master 1024x512, design name, note)."""
    im = Image.new("RGB", (MW, MH))
    d = ImageDraw.Draw(im)
    pc, sc = hexcol(f["colour_primary"]), hexcol(f["colour_secondary"])
    if key in HIST:
        kind, a, note = HIST[key]
        if kind == "plain":
            d.rectangle([0, 0, MW, MH], fill=a["c"])
        elif kind == "hbands":
            stripes(d, a["c"], 0, 0, MW, MH)
        elif kind == "crescent":
            d.rectangle([0, 0, MW, MH], fill=a["c"])
            crescent(im, a["fg"])
        elif kind == "border":
            d.rectangle([0, 0, MW, MH], fill=a["b"])
            m = MH * 0.09
            d.rectangle([m, m, MW - m, MH - m], fill=a["c"])
        elif kind == "hoist":
            d.rectangle([0, 0, MW, MH], fill=a["c"])
            d.rectangle([0, 0, MW * 0.1, MH], fill=a["h"])
        elif kind == "usa1795":
            stripes(d, [RED, WHITE] * 7 + [RED], 0, 0, MW, MH)
            ch, cw = MH * 8 / 15, MW * 0.42
            d.rectangle([0, 0, cw, ch], fill=(10, 49, 97))
            for r in range(3):
                for c in range(5):
                    d.polygon(star_poly(cw * (c + 0.5) / 5, ch * (r + 0.5) / 3, ch * 0.1), fill=WHITE)
        elif kind == "eic":
            stripes(d, [RED, WHITE] * 6 + [RED], 0, 0, MW, MH)
            ch, cw = MH * 7 / 13, MW * 0.45
            im.paste(union_jack(int(cw), int(ch)), (0, 0))
        elif kind == "rac":
            stripes(d, [WHITE, (0, 57, 166), (213, 43, 30)], 0, 0, MW, MH)
            eagle(d, MW * 0.14, MH / 6, MH * 0.31)
        return im, kind, note
    pat = PATTERNS[zlib.crc32(key.encode()) % len(PATTERNS)]
    pattern(pat, pc, sc, d, im)
    return im, "pattern:" + pat, "generated from colour_primary/colour_secondary (placeholder; no 1805 design chosen)"


# --- derived assets -------------------------------------------------------------------------


def poly_mask(size, pts, ss=4):
    m = Image.new("L", (size[0] * ss, size[1] * ss), 0)
    ImageDraw.Draw(m).polygon([(x * ss, y * ss) for x, y in pts], fill=255)
    return m.resize(size, Image.LANCZOS)


def shaped(flag, size, mask):
    im = flag.resize(size, Image.LANCZOS).convert("RGBA")
    im.putalpha(mask)
    return im


def pennant(flag, size, flip):
    w, h = size
    pts = [(w * .1, h * .1), (w * .9, h * .1), (w * .9, h * .66), (w * .5, h * .97), (w * .1, h * .66)]
    im = shaped(flag, size, poly_mask(size, pts))
    d = ImageDraw.Draw(im)
    d.line([(w / 2, 0), (w / 2, h * .1)], fill=(210, 190, 120, 255), width=max(1, w // 20))
    im = im.rotate(-6 if flip else 6, resample=Image.BICUBIC, center=(w / 2, 0))
    return im.transpose(Image.FLIP_LEFT_RIGHT) if flip else im


def wave_frames(flag):
    S = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    S.paste(flag.resize((192, 86), Image.LANCZOS).convert("RGBA"), (4, 7))
    a = np.asarray(S, dtype=np.float32)
    ys, xs = np.mgrid[0:100, 0:200].astype(np.float32)
    out = []
    for k in range(12):
        ph = 2 * math.pi * k / 12
        arg = 2 * math.pi * 1.2 * xs / 200 - ph
        dy = 5.0 * (0.25 + 0.75 * xs / 200) * np.sin(arg)
        sy = np.clip(ys - dy, 0, 98.999)
        y0 = sy.astype(np.int32)
        t = (sy - y0)[..., None]
        cols = np.broadcast_to(xs.astype(np.int32), ys.shape)
        v = a[y0, cols] * (1 - t) + a[np.minimum(y0 + 1, 99), cols] * t
        # dark/light cloth ripple from the wave slope
        slope = np.cos(arg) * (0.25 + 0.75 * xs / 200)
        v[..., :3] *= (1 + 0.12 * slope)[..., None]
        out.append(Image.fromarray(np.clip(v, 0, 255).astype(np.uint8), "RGBA"))
    return out


def save_tga(im, path, spec):
    _, _, bpp, ttype = spec
    im = im.convert("RGBA" if bpp == 32 else "RGB")
    im.save(path, format="TGA", compression="tga_rle" if ttype == 10 else None)


def save_dds(master, path):
    with tempfile.TemporaryDirectory() as t:
        p = os.path.join(t, "l.png")
        master.resize((512, 256), Image.LANCZOS).convert("RGBA").save(p)
        subprocess.run(["magick", p, "-define", "dds:compression=dxt5", "-define", "dds:mipmaps=9", path], check=True)


def build_one(key, f, outdir):
    master, kind, note = draw_master(key, f)
    os.makedirs(outdir, exist_ok=True)
    big = master.resize((512, 256), Image.LANCZOS)
    P = lambda n: os.path.join(outdir, n)
    save_tga(big, P("large.tga"), SPEC["large.tga"])
    save_dds(master, P("large.dds"))
    save_tga(big.resize((132, 66), Image.LANCZOS), P("flag_132.tga"), SPEC["flag_132.tga"])
    for i, fr in enumerate(wave_frames(big)):
        save_tga(fr, P(f"flag_animation{i:04d}.tga"), SPEC[f"flag_animation{i:04d}.tga"])
    save_tga(pennant(big, (40, 79), False), P("hud_left.tga"), SPEC["hud_left.tga"])
    save_tga(pennant(big, (40, 79), True), P("hud_right.tga"), SPEC["hud_right.tga"])
    W, H = 112, 64
    save_tga(shaped(big, (W, H), poly_mask((W, H), [(0, 0), (W, 0), (W, H), (0, H)])), P("id_flag_infantry.tga"), SPEC["id_flag_infantry.tga"])
    save_tga(shaped(big, (W, H), poly_mask((W, H), [(0, 0), (W, 0), (W - 27, H / 2), (W, H), (0, H)])), P("id_flag_cavalry.tga"), SPEC["id_flag_cavalry.tga"])
    save_tga(shaped(big, (W, H), poly_mask((W, H), [(0, 0), (W - 27, 0), (W, H / 2), (W - 27, H), (0, H)])), P("id_flag_artillery.tga"), SPEC["id_flag_artillery.tga"])
    nav = shaped(big, (64, 64), poly_mask((64, 64), [(32 + 32 * math.cos(a / 90 * math.pi), 32 + 32 * math.sin(a / 90 * math.pi)) for a in range(180)]))
    ring = Image.new("L", (256, 256), 0)
    ImageDraw.Draw(ring).ellipse([0, 0, 255, 255], fill=255)
    ImageDraw.Draw(ring).ellipse([12, 12, 243, 243], fill=0)
    ring = ring.resize((64, 64), Image.LANCZOS)
    nav.paste((20, 20, 20, 255), (0, 0), ring)
    save_tga(nav, P("id_flag_naval.tga"), SPEC["id_flag_naval.tga"])
    mini = big.resize((44, 22), Image.LANCZOS).convert("RGBA")
    ImageDraw.Draw(mini).rectangle([0, 0, 43, 21], outline=(40, 40, 40, 255))
    save_tga(mini, P("mini_flag.tga"), SPEC["mini_flag.tga"])
    por = Image.new("RGBA", (140, 116), (0, 0, 0, 0))
    por.alpha_composite(pennant(big, (46, 108), False), (0, 4))
    por.alpha_composite(pennant(big, (46, 108), True), (94, 4))
    save_tga(por, P("portrait_flags.tga"), SPEC["portrait_flags.tga"])
    # small: flag sheared into a leaning 19x24 strip
    sm = shaped(big, (19, 24), poly_mask((19, 24), [(17, 1), (17, 18), (9, 24), (1, 24), (1, 15)]))
    save_tga(sm, P("small.tga"), SPEC["small.tga"])
    return big, kind, note


def targets():
    return [f for f in json.load(open(FACTIONS)) if f.get("vanilla") is not True]


def contact_sheet(items):
    cols, tw, th, lab = 6, 200, 100, 16
    rows = math.ceil(len(items) / cols)
    sheet = Image.new("RGB", (cols * (tw + 10) + 10, rows * (th + lab + 10) + 10), (40, 40, 40))
    d = ImageDraw.Draw(sheet)
    for i, (k, im) in enumerate(items):
        x, y = 10 + (i % cols) * (tw + 10), 10 + (i // cols) * (th + lab + 10)
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y))
        d.text((x, y + th + 2), k[:32], fill=(255, 255, 255))
    os.makedirs(os.path.dirname(SHEET), exist_ok=True)
    sheet.save(SHEET)


def build():
    items, rows = [], []
    for f in targets():
        k = f["key"]
        big, kind, note = build_one(k, f, os.path.join(OUT, DIR(k)))
        items.append((k, big))
        rows.append({"key": k, "name": f["name"], "source": "generated", "license": "n/a (own drawing, no external asset)",
                     "url": None, "design": kind, "note": note})
    json.dump(rows, open(SOURCES, "w"), indent=1, ensure_ascii=False)
    contact_sheet(items)
    print(f"built {len(items)} flag sets -> {OUT}; sources -> {SOURCES}; sheet -> {SHEET}")


def tga_header(path):
    with open(path, "rb") as fh:
        idl, cm, it, _, _, _, _, _, w, h, bpp, desc = struct.unpack("<BBBHHBHHHHBB", fh.read(18))
    return idl, cm, it, w, h, bpp, desc


def check():
    bad = []
    ts = targets()
    for f in ts:
        k = f["key"]
        d = os.path.join(OUT, DIR(k))
        have = set(os.listdir(d)) if os.path.isdir(d) else set()
        if have != set(FILES):
            bad.append(f"{k}: file set differs, missing {sorted(set(FILES) - have)} extra {sorted(have - set(FILES))}")
            continue
        for n, (w, h, bpp, ttype) in SPEC.items():
            idl, cm, it, tw, th, tb, desc = tga_header(os.path.join(d, n))
            want = (ttype, w, h, bpp, 0x08 if bpp == 32 else 0x00)
            if (it, tw, th, tb, desc) != want or cm != 0 or idl != 0:
                bad.append(f"{k}/{n}: header {(it, tw, th, tb, desc)} != {want}")
        b = open(os.path.join(d, "large.dds"), "rb").read(128)
        if b[:4] != b"DDS " or struct.unpack("<II", b[12:20]) != (256, 512) or b[84:88] != b"DXT5":
            bad.append(f"{k}/large.dds: bad header")
        # content: large not flat, animation frames opaque in the middle and different from each other
        im = Image.open(os.path.join(d, "large.tga"))
        if np.asarray(im).std() < 5:
            bad.append(f"{k}/large.tga: flat image")
        a0, a6 = (np.asarray(Image.open(os.path.join(d, f"flag_animation{i:04d}.tga"))) for i in (0, 6))
        if a0[50, 100, 3] != 255 or (a0 == a6).all():
            bad.append(f"{k}: animation frames suspicious")
    print(f"checked {len(ts)} target factions x {len(FILES)} files")
    for b in bad:
        print("FAIL", b)
    if bad:
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    check() if sys.argv[1:] == ["check"] else build()
