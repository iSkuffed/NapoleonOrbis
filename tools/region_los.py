"""Post-pass on a built startpos: redraw the fog-of-war sight maps of the new regions with vanilla's rules (research/16 Q1).

  python tools/region_los.py IN_startpos.esf REGIONS.esf OUT_startpos.esf

The build clones eur_ireland, so every new REGION's LINE_OF_SIGHT is Ireland's bitmap moved to the new settlement
(Siberia stays dark), and the settlement disc sits up to 5 u off-centre.  Vanilla's rules, measured on the 45 lit vanilla
regions and 33 settlement discs (the self-check below re-measures them on the input file):
  REGION      cell (c, r) is lit iff its corner point box_min + 1.25 (c, r) lies inside the region's polygon (all areas of
              regions.esf) grown by 10 u; the record's box = the grown polygon's bounds snapped outward to the 1.25 grid.
  SETTLEMENT  one fixed 69-cell pattern in a 9x9 box whose min cell is floor(settlement cell) - 4.
Every region's map is switched on, so any faction made playable later (make_playable.py) starts with its own land lit;
vanilla only lit the 5 shroud factions' regions.  A capture still turns a region's map off, as in vanilla.
"""
import copy, json, math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, shapely
import esf, campaign_misc as cm, regions_model as rm
from esf import Val

FIX, C, GROW = 2 ** 20, cm.QT_CELL, 10.0
MIN_IOU = 0.95


def lit(los):
    """LINE_OF_SIGHT -> set of lit (c, r) cells."""
    _, _, b = cm.qtba_decode(los.find('QUAD_TREE_BIT_ARRAY'))
    out = set()
    for (bx, by), (lo, hi) in b.items():
        v = lo | hi << 32
        out |= {(bx * 8 + i % 8, by * 8 + i // 8) for i in range(64) if v >> i & 1}
    return out


def region_cells(G, bmin):
    """Cells whose corner point lies in G, and the outward-snapped box (cell units)."""
    x0, y0, x1, y1 = G.bounds
    box = (math.floor((x0 - bmin[0]) / C), math.floor((y0 - bmin[1]) / C), math.ceil((x1 - bmin[0]) / C), math.ceil((y1 - bmin[1]) / C))
    cc, rr = np.meshgrid(np.arange(box[0], box[2] + 1), np.arange(box[1], box[3] + 1))
    m = shapely.contains_xy(G, bmin[0] + cc * C, bmin[1] + rr * C)
    return set(zip(cc[m].tolist(), rr[m].tolist())), box


def settle_cells(pattern, pos, bmin):
    c0, r0 = (math.floor((p - b) / C) - 4 for p, b in zip(pos, bmin))
    return {(c0 + c, r0 + r) for c, r in pattern}, (c0, r0, c0 + 9, r0 + 9)


def write(los, tpl, cells, box, bmin):
    """Switch los on and set its box and bitmap (tpl: a lit record, for the layout of an 'off' one)."""
    if len(los.children) == 1:
        los.children[:] = copy.deepcopy(tpl.children)
    q = los.find('QUAD_TREE_BIT_ARRAY')
    W, H = q.children[0].value, q.children[1].value
    cells = {(c, r) for c, r in cells if 0 <= c < W and 0 <= r < H}      # outline + 10 u clipped to the world box
    box = (max(box[0], 0), max(box[1], 0), min(box[2], W), min(box[3], H))
    blocks = {}
    for c, r in cells:
        lo, hi = blocks.get((c // 8, r // 8), (0, 0))
        i = (r % 8) * 8 + c % 8
        blocks[(c // 8, r // 8)] = (lo | 1 << i, hi) if i < 32 else (lo, hi | 1 << (i - 32))
    q.children[:] = cm.qtba_encode(W, H, blocks, q.children[3].version).children
    los.children[0] = Val(0x01, True)
    los.children[1] = Val(0x0c, (bmin[0] + box[0] * C, bmin[1] + box[1] * C))
    los.children[2] = Val(0x0c, (bmin[0] + box[2] * C, bmin[1] + box[3] * C))
    assert lit(los) == cells


def main(src, regions, dst):
    rd = esf.load(regions).root.find('region_data')
    bmin = tuple(float(v) for v in rd.children[1].value)           # the world box min: cells count from it
    names = [it[0].value for it in rd.find('regions').items]
    parts = {}
    for code, p in rm.area_polygons(rd).items():
        parts.setdefault(names[code >> 16], []).append(p)
    del rd
    sp = esf.load(src)
    ra = cm.first_rec(sp.root, 'REGIONS_ARRAY')
    regs = [it[0] for it in ra.items]
    res = lambda g: g.find('SETTLEMENT').children[0]
    W, H = next(r.children[21].find('QUAD_TREE_BIT_ARRAY') for r in regs if r.children[21].children[0].value).children[:2]
    assert bmin == (-W.value * C / 2, -H.value * C / 2), (bmin, W.value, H.value)
    R = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data/world1805/regions.json')))
    new = {r['key'] for r in R}
    built = {g.children[0].value for g in regs}
    redo = new | {r['split_of'] for r in R if r.get('split_of') and r['key'] in built}   # a split's vanilla region: redrawn
    van = [g for g in regs if g.children[0].value.startswith('eur_') and g.children[0].value not in new]
    assert len(van) == 72, len(van)
    tpl_r = next(g.children[21] for g in van if g.children[21].children[0].value)
    tpl_s = res(next(g for g in van if g.children[0].value == 'eur_ireland')).find('LINE_OF_SIGHT')
    grow = lambda k: shapely.union_all(parts[k]).buffer(GROW, quad_segs=16)
    pos = lambda g: (res(g).children[10].value / FIX, res(g).children[11].value / FIX)
    # self-check: the rules redraw vanilla's own lit maps (cell IoU >= 0.95; the discs exactly)
    _, sbox = settle_cells([], pos(next(g for g in van if g.children[0].value == 'eur_ireland')), bmin)
    pattern = {(c - sbox[0], r - sbox[1]) for c, r in lit(tpl_s)}
    assert len(pattern) == 69, len(pattern)
    ious = {}
    for g in van:
        k = g.children[0].value
        if g.children[21].children[0].value and k not in redo:        # a split's region: CA's map no longer fits it
            S = lit(g.children[21]); R, _ = region_cells(grow(k), bmin)
            ious[k] = len(S & R) / len(S | R)
        sl = res(g).find('LINE_OF_SIGHT')
        if sl.children[0].value:
            assert lit(sl) == settle_cells(pattern, pos(g), bmin)[0], k
    worst = min(ious, key=ious.get)
    print(f'self-check: {len(ious)} lit vanilla regions, cell IoU min {ious[worst]:.3f} ({worst}) mean '
          f'{sum(ious.values()) / len(ious):.3f}; vanilla settlement discs match the pattern')
    assert ious[worst] >= MIN_IOU, (worst, ious[worst])
    # redraw: new regions (cloned maps) and the vanilla regions that start dark; lit vanilla maps stay as CA drew them
    n = {'region': 0, 'region_on': 0, 'settlement': 0, 'settlement_on': 0}
    for g in regs:
        k = g.children[0].value
        los, sl = g.children[21], res(g).find('LINE_OF_SIGHT')
        if k in redo or not k.startswith('eur_') or not los.children[0].value:
            n['region_on'] += not los.children[0].value
            cells, box = region_cells(grow(k), bmin)
            write(los, tpl_r, cells, box, bmin); n['region'] += 1
            sx, sy = pos(g)
            assert (math.floor((sx - bmin[0]) / C), math.floor((sy - bmin[1]) / C)) in cells, k
        if k in redo or not k.startswith('eur_') or not sl.children[0].value:
            n['settlement_on'] += not sl.children[0].value
            write(sl, tpl_s, *settle_cells(pattern, pos(g), bmin), bmin); n['settlement'] += 1
    print('redrawn', n)
    open(dst, 'wb').write(esf.dumps(sp))
    print('wrote', dst)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
