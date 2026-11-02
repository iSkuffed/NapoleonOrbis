#!/usr/bin/env python3
"""Campaign-map lookup image (campaign_maps/<map>/europe_lookup.tga) from a regions.esf. Format decoded 2026-10-19.

Format (vanilla nap_europe, 182312 bytes): 605x300 8-bit colour-mapped TGA (type 1, 256 x BGR24 palette, descriptor 0x08 =
bottom-left origin, rows stored south first), 8 zero bytes + 'TRUEVISION-XFILE.\\0' footer. It is a region-ownership picture:
pixel -> palette colour; the colour is the region's r,g,b in db regions_tables (72/72 vanilla land regions match), every
sea region is one shared colour (43,120,139), black (0,0,0) is "no region" (off-map filler land, outside the sea
regions) and the 1 px outline round land regions. Palette index is NOT a region index: palette = white sentinel at 169,
the used colours sorted by hue at 170..253, white at 254, black at 255 (we reproduce the layout, not CA's exact sort).
The image shares its pixel grid with europe_map.tga / stratradar (the same 605x300 frame).

World mapping: pixel (i, j) centre = (x0 + (i+.5)*sx, ytop - (j+.5)*sy), j = 0 at the north edge. Vanilla was fitted
(VANILLA_BOX): x -393.4..336.9, y 180.0..-181.9 (~ the bbox of the non-filler regions, square 1.206 u pixels; not the playable
theatre). The world image is the proj.THEATRE crop that world_build.minimap() squeezes into 605x300, so use WORLD_BOX.

Known differences from vanilla (self-check below, ~96% of pixels): outline pixels only approximately (CA's line rasteriser
is unknown), 0.2% tiny islands that vanilla paints in an extra dark shade of the region colour (we use the region colour),
and a strip of the Norway/Finland/Russia north-east coast that vanilla's lookup colours but its regions.esf marks as filler.

  .venv/bin/python tools/lookup_tga.py             # self-check against the vanilla lookup (read-only)
  .venv/bin/python tools/lookup_tga.py build [regions.esf] [--table T] [--out DIR]
        # world lookup -> work/world/lookup/europe_lookup.tga + .png (default: work/mods/world_m1 regions.esf, vanilla table)
"""
import colorsys, os, struct, sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbtable, esf, geo, proj  # noqa: E402
import regions_model as rm  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 605, 300
SEA, BLACK, WHITE = (43, 120, 139), (0, 0, 0), (255, 255, 255)
FILLER = ('eur_map_west', 'eur_map_east')           # off-theatre land: no region (black)
SEA_LIKE = ('eur_lakes',)                           # vanilla draws the lakes as sea
ALIAS = {'eur_tyrolland': 'eur_tyrol'}              # no table row; vanilla paints it with Tyrol's colour
VANILLA_BOX = (-393.43, 180.045, 1.20706, 1.206225)  # x0, ytop, sx, sy (fitted to the vanilla lookup)
WORLD_BOX = (proj.THEATRE_MIN[0], proj.THEATRE_MAX[1],
             (proj.THEATRE_MAX[0] - proj.THEATRE_MIN[0]) / W, (proj.THEATRE_MAX[1] - proj.THEATRE_MIN[1]) / H)
VAN_TABLE = os.path.join(ROOT, 'work/vanilla/db/regions_tables/regions')
VAN_LOOKUP = geo.GAME + '/campaign_maps/nap_europe/europe_lookup.tga'
VAN_REGIONS = geo.GAME + '/campaign_maps/nap_europe/regions.esf'
WORLD_REGIONS = os.path.join(ROOT, 'work/mods/world_m1/campaign_maps/nap_world/regions.esf')
OUT = os.path.join(ROOT, 'work/world/lookup')


def colours(table=VAN_TABLE):
    """{region key: (r, g, b)} from a db regions_tables/regions file."""
    return {r[0]: tuple(r[2:5]) for r in dbtable.load(table)['rows']}


def _label_polys(e, col):
    """[(kind_label, polygon)]: label 'sea' | 'river' | (r, g, b) region colour; filler land skipped."""
    import shapely
    rd, out = e.root.find('region_data'), []
    V = rm.verts(rd).astype(np.float64)
    names = [rm.vals(it)[0].value for it in rd.find('regions').items]
    kinds = [rm.vals(it)[1].value for it in rd.find('regions').items]
    for ri, ai, it, ar in rm.iter_areas(rd):
        n, k = names[ri], kinds[ri]
        if n in FILLER:
            continue
        if k == 'sea' or n in SEA_LIKE:
            lab = 'sea'
        elif k == 'river':
            lab = 'river'
        elif ALIAS.get(n, n) in col:
            lab = col[ALIAS.get(n, n)]
        else:
            raise KeyError(f'land region {n!r} has no colour (regions_tables row)')
        rs = rm.rings(ar)
        out.append((lab, shapely.Polygon([V[i] for o, i, _ in rs if o][0], [V[i] for o, i, _ in rs if not o])))
    return out


def render(e, col, box=VANILLA_BOX, border=True):
    """-> (rgb uint8 (H, W, 3), row 0 = north) region picture of the esf Esf `e` over `box` (x0, ytop, sx, sy)."""
    import shapely
    x0, yt, sx, sy = box
    colset = sorted({c for c in col.values()} | {SEA})
    cid = {c: i + 2 for i, c in enumerate(colset)}           # label 0 none, 1 river gap, 2.. colours
    lab = np.zeros((H, W), np.int32)
    river = np.zeros((H, W), bool)
    polys = _label_polys(e, col)
    for want in ('sea', 'land', 'river'):                     # land over sea on shared edge pixels
        for l, p in polys:
            if (l if isinstance(l, str) else 'land') != want:
                continue
            b = p.bounds
            i0, i1 = max(0, int((b[0] - x0) / sx) - 1), min(W, int((b[2] - x0) / sx) + 2)
            j0, j1 = max(0, int((yt - b[3]) / sy) - 1), min(H, int((yt - b[1]) / sy) + 2)
            if i1 <= i0 or j1 <= j0:
                continue
            X, Y = np.meshgrid(np.arange(i0, i1) + .5, np.arange(j0, j1) + .5)
            ins = shapely.contains_xy(p, x0 + X * sx, yt - Y * sy)
            if want == 'river':
                river[j0:j1, i0:i1] |= ins
            else:
                lab[j0:j1, i0:i1][ins] = cid[SEA if l == 'sea' else tuple(l)]
    gap = river & (lab == 0)                                  # rivers are cut out of the land areas: take the neighbour
    if gap.any():
        _, (iy, ix) = ndimage.distance_transform_edt(lab == 0, return_indices=True)
        lab[gap] = lab[iy, ix][gap]
    if border:                                                # land pixel touching another region or the sea -> black
        sea, land = lab == cid[SEA], lab >= 2
        land &= ~sea
        edge = np.zeros((H, W), bool)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            N = np.full((H, W), -1, np.int32)
            N[max(0, -dy):H - max(0, dy), max(0, -dx):W - max(0, dx)] = lab[max(0, dy):H - max(0, -dy), max(0, dx):W - max(0, -dx)]
            edge |= (N != lab) & (N >= 1)
        lab[land & edge] = 0
    lut = np.array([BLACK, BLACK] + colset, np.uint8)
    return lut[lab]


def palettise(rgb):
    """rgb (H, W, 3) -> (index (H, W) uint8, palette (256, 3) uint8) in vanilla layout (see module doc)."""
    used = {tuple(int(v) for v in c) for c in rgb.reshape(-1, 3)} - {BLACK}
    srt = sorted(used, key=lambda c: colorsys.rgb_to_hsv(*[v / 255 for v in c]))
    start = min(170, 254 - len(srt))
    assert start >= 2, f'{len(srt)} colours do not fit a 256-entry palette'
    pal = np.zeros((256, 3), np.uint8)
    pal[start - 1] = pal[254] = WHITE
    for i, c in enumerate(srt):
        pal[start + i] = c
    lut = {BLACK: 255, **{c: start + i for i, c in enumerate(srt)}}
    idx = np.zeros(rgb.shape[:2], np.uint8)
    for c, i in lut.items():
        idx[(rgb == c).all(2)] = i
    return idx, pal


def tga_bytes(idx, pal):
    h, w = idx.shape
    return (struct.pack('<BBBHHBHHHHBB', 0, 1, 1, 0, 256, 24, 0, 0, w, h, 8, 8) + pal[:, ::-1].tobytes()
            + idx[::-1].tobytes() + b'\0' * 8 + b'TRUEVISION-XFILE.\0')


def read_tga(data):
    """-> (index (H, W) row 0 = north, palette (256, 3) rgb)."""
    _, cm, ty, _, ln, bits, _, _, w, h, bpp, desc = struct.unpack_from('<BBBHHBHHHHBB', data)
    assert (cm, ty, ln, bits, bpp, desc) == (1, 1, 256, 24, 8, 8), 'not a vanilla-style lookup TGA'
    pal = np.frombuffer(data, np.uint8, 768, 18).reshape(256, 3)[:, ::-1]
    return np.frombuffer(data, np.uint8, w * h, 786).reshape(h, w)[::-1], pal


def build(regions, table=VAN_TABLE, box=WORLD_BOX):
    """regions.esf path -> (tga bytes, rgb picture)."""
    rgb = render(esf.load(regions), colours(table), box)
    return tga_bytes(*palettise(rgb)), rgb


def demo():
    """Vanilla regions.esf + table -> our lookup, compared with the vanilla file."""
    van = open(VAN_LOOKUP, 'rb').read()
    assert len(van) == 182312
    vi, vp = read_tga(van)
    vrgb = vp[vi]
    data, rgb = build(VAN_REGIONS, VAN_TABLE, VANILLA_BOX)
    assert len(data) == len(van) and data[:18] == van[:18] and data[-26:] == van[-26:], 'header/footer layout'
    oi, op = read_tga(data)
    assert (op[oi] == rgb).all() and op[255].tolist() == [0, 0, 0] and op[169].tolist() == op[254].tolist() == [255] * 3
    same = (rgb == vrgb).all(2)
    # region content (outline pixels excluded): every pixel that is a table colour in vanilla must be that colour in ours
    col = {c: k for k, c in colours().items()}
    tab = np.array([tuple(int(v) for v in c) in col or tuple(int(v) for v in c) == SEA for c in vrgb.reshape(-1, 3)]).reshape(H, W)
    inner = tab & (vrgb != 0).any(2)
    frac, frac_in = same.mean(), same[inner].mean()
    assert frac > 0.955 and frac_in > 0.97, (frac, frac_in)
    # sampled settlements (vanilla regions.esf slot positions): the picture shows the settlement's own region colour
    e = esf.load(VAN_REGIONS)
    m = rm.extract(e)
    x0, yt, sx, sy = VANILLA_BOX
    tab_col, ok, tot = colours(), 0, 0
    for r in m['regions']:
        s = r['settlement']
        if r['kind'] != 'land' or not s or r['name'] not in tab_col:
            continue
        px, py = s['pos']
        i, j = int((px - x0) / sx), int((yt - py) / sy)
        if not (0 <= i < W and 0 <= j < H):
            continue
        tot += 1
        ok += tuple(rgb[j, i]) == tab_col[r['name']] == tuple(vrgb[j, i])
    assert tot >= 50 and ok >= tot - 6, (ok, tot)
    return dict(match=float(frac), match_inner=float(frac_in), settlements=(ok, tot), colours=len(set(map(tuple, op[oi].reshape(-1, 3)))))


def main(argv):
    if argv[:1] != ['build']:
        print('vanilla self-check:', demo())
        print('OK')
        return
    a = argv[1:]
    out, table = OUT, VAN_TABLE
    for flag in ('--out', '--table'):
        if flag in a:
            k = a.index(flag)
            v = a[k + 1]
            del a[k:k + 2]
            out, table = (v, table) if flag == '--out' else (out, v)
    regions = a[0] if a else WORLD_REGIONS
    data, rgb = build(regions, table)
    from PIL import Image
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, 'europe_lookup.tga'), 'wb').write(data)
    Image.fromarray(rgb).resize((W * 2, H * 2), Image.NEAREST).save(os.path.join(out, 'europe_lookup.png'))
    idx, pal = read_tga(data)
    print('wrote', out, len(data), 'bytes,', len(np.unique(idx)), 'palette colours used')


if __name__ == '__main__':
    main(sys.argv[1:])
