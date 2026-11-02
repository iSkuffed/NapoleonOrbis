#!/usr/bin/env python3
"""World campaign-map regions.esf for milestone M1 "world ocean" (RoadMap Phase 4, lane D).

Vanilla nap_europe regions.esf is the base. Every vanilla area inside the vanilla theatre VT keeps its geometry, keys,
flags, ids and settlement data; only the four vanilla filler areas that leave VT (eur_map_west #0/#9, eur_map_east
#0/#11) are dropped. Their place, box - union(kept areas), is re-partitioned from our own geography:
  land  = worldgeo.land() (islands < AMIN dropped, lake holes filled, simplified TOL) -> impassable filler
          land in eur_map_west / eur_map_east (split at x = XS), together with the off-theatre frame;
  water = sea, split into the zones of data/world1805/seas.json; water not connected to the ocean (lakes, Caspian)
          is filler land too, matching the pathfinding grid (world sea = largest water body).
Two variants:
  regions_reuse.esf  no new keys: zones map onto existing vanilla sea regions ('reuse' in seas.json)
  regions.esf        new wld_* sea regions, appended after the 101 vanilla regions (vanilla indices unchanged:
                     pathfinding.esf and startpos CAI_WORLD_REGIONS index regions.esf regions by position)
A new sea piece that touches a kept area of its own region is unioned into that area (so the vanilla Atlantic stays
one area, as in G3); vanilla area order and pass_group/nonwalk/landmass ids are kept, new ids are appended.
Theatre = proj.THEATRE_MIN/MAX; climate (1.6 px/u) and wind (0.4 px/u) maps: vanilla pasted in VT, outside from
latitude/longitude/ETOPO rules (see climate()). Groundtypes: vanilla stretched to the new box (resize rule).

  .venv/bin/python tools/regions_world.py          # build both variants + self-check -> work/world/regions/
  .venv/bin/python tools/regions_world.py check    # self-check the existing outputs only
"""
import copy, json, math, os, sys, time
from collections import Counter, defaultdict

import numpy as np
import shapely
from shapely.geometry import box, LineString, Polygon, MultiLineString
from shapely.geometry.polygon import orient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esf, proj, worldgeo, geo, regions_model as rm  # noqa: E402
from esf import Rec, Val  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VANILLA = geo.GAME + '/campaign_maps/nap_europe/regions.esf'
SEAS = os.path.join(ROOT, 'data/world1805/seas.json')
OUT = os.path.join(ROOT, 'work/world/regions')
BOX = box(*proj.BOX_MIN, *proj.BOX_MAX)
THEATRE = box(*proj.THEATRE_MIN, *proj.THEATRE_MAX)
VT = box(*proj.VT_MIN, *proj.VT_MAX)
FILLER = ('eur_map_west', 'eur_map_east')
XS = -22.7                   # west/east filler split (vanilla's split line)
AMIN = 4.0                   # drop land parts below this (u^2): they become sea
TOL = 0.5                    # land simplification (u); < 1 so water >= 1 u from land stays outside land
GRID = 2.0 ** -10            # new geometry snapped to this grid (exact in float32 over +-2048)
SLIVER = 30.0               # ocean-connected sea parts below this (u^2) mostly in VT become land (vanilla coast wins)
TINY = 1.0                   # any new part below this (u^2) joins its longest-border new neighbour
SMALL_SEA = 20.0             # sea parts below this (u^2) join the neighbouring zone they share most border with
CLIMATE_PPU, WIND_PPU = 1.6, 0.4


# ---------------------------------------------------------------- geometry helpers
def parts(g):
    return [p for p in shapely.get_parts(g) if not p.is_empty and p.area > 0] if g is not None else []


def lonlat_poly(ring):
    """lon/lat ring (lon in [SEAM, SEAM+360]) -> world polygon, edges densified so the piecewise-linear map is exact."""
    p = shapely.segmentize(Polygon(ring), 0.25)
    c = shapely.get_coordinates(p.exterior)
    return Polygon(np.column_stack(proj.to_world(c[:, 0], c[:, 1], wrap=False)))


def load_zones():
    cfg = json.load(open(SEAS))
    zones = []
    for z in cfg['zones']:
        g = shapely.union_all([lonlat_poly(r) for r in z['polys']])
        zones.append(dict(z, geom=shapely.set_precision(g, GRID)))
    return zones


def prep_land():
    g = worldgeo.land()
    out = []
    for p in parts(g):
        if p.area < AMIN:
            continue
        out.append(Polygon(p.exterior))              # lakes are filler land (see partition)
    s = shapely.simplify(np.array(out, object), TOL, preserve_topology=True)
    s = shapely.set_precision(shapely.union_all([q for q in s if not q.is_empty]), GRID)
    return shapely.MultiPolygon(parts(s))


def shared_len(a, b):
    """length of common boundary of two polygons (0 if they only touch at points or are disjoint)."""
    if not a.intersects(b):
        return 0.0
    return shapely.intersection(a.boundary, b.boundary).length


# ---------------------------------------------------------------- stage 1: partition of box - kept Europe
def vanilla_model():
    e = esf.load(VANILLA)
    rd = e.root.find('region_data')
    items = rd.find('regions').items
    names = [it[0].value for it in items]
    kinds = [it[1].value for it in items]
    polys = rm.area_polygons(rd)
    drop = {c for c, p in polys.items() if names[c >> 16] in FILLER and not p.within(VT)}
    assert len(drop) == 4, drop
    return e, rd, names, kinds, polys, drop


def partition(polys, drop, kinds, zones):
    """-> dict(sea=[(key, polygon)], land=[(region, polygon)], keep=set codes, ksea=codes) over box - union(kept)."""
    t = time.time()
    keep = {c: p for c, p in polys.items() if c not in drop}
    UK = shapely.union_all(list(keep.values()))
    R = BOX.difference(UK)
    L = prep_land()
    print(f'  land: {len(L.geoms)} parts, {shapely.get_num_coordinates(L)} vertices ({time.time() - t:.0f}s)')
    Rb = R.buffer(1.0)
    lines = [R.boundary, THEATRE.boundary,
             LineString([(XS, proj.THEATRE_MAX[1]), (XS, proj.BOX_MAX[1])]),
             LineString([(XS, proj.BOX_MIN[1]), (XS, proj.THEATRE_MIN[1])])]
    Lr = shapely.MultiPolygon([p for p in L.geoms if p.intersects(R)])
    lines.append(shapely.intersection(Lr.boundary, Rb))
    for z in zones:
        lines.append(shapely.intersection(z['geom'].boundary, Rb.intersection(THEATRE)))
    noded = shapely.union_all([g for g in lines if not g.is_empty])
    faces = list(shapely.get_parts(shapely.polygonize(shapely.get_parts(noded))))
    print(f'  {len(faces)} faces ({time.time() - t:.0f}s)')
    rep = shapely.point_on_surface(faces)
    rx, ry = shapely.get_x(rep), shapely.get_y(rep)
    shapely.prepare(UK); shapely.prepare(L)
    inK = shapely.contains_xy(UK, rx, ry)
    cls = np.where(inK, 'K', np.where(~shapely.contains_xy(THEATRE, rx, ry), 'frame',
                                      np.where(shapely.contains_xy(L, rx, ry), 'land', 'sea'))).astype(object)
    faces = [f for f, k in zip(faces, inK) if not k]
    cls, rx, ry = cls[~inK], rx[~inK], ry[~inK]
    area_new = sum(f.area for f in faces)
    assert abs(area_new - R.area) < 1e-3 * R.area, (area_new, R.area)
    ksea = {c for c in keep if kinds[c >> 16] == 'sea'}
    KS = shapely.union_all([keep[c] for c in ksea])

    def group(mask):
        idx = np.nonzero(mask)[0]
        u = parts(shapely.union_all([faces[i] for i in idx]))
        tree = shapely.STRtree(u)
        lab = np.full(len(faces), -1)
        hit = tree.query(shapely.points(rx[idx], ry[idx]), predicate='within')
        lab[idx[hit[0]]] = hit[1]
        assert (lab[idx] >= 0).all()
        return u, lab

    # small land parts -> sea (erring toward sea is allowed everywhere)
    land_u, lab = group(cls == 'land')
    small = [j for j, p in enumerate(land_u) if p.area < AMIN]
    cls[np.isin(lab, small) & (cls == 'land')] = 'sea'
    # water not connected to the ocean (directly or via a kept vanilla sea) is a lake -> filler land, as in the
    # pathfinding grid (world sea = largest water body of worldgeo; lakes, Caspian, Great Lakes are off-map)
    sea_u, lab = group(cls == 'sea')
    big = int(np.argmax([p.area for p in sea_u]))
    ocean = [j == big or shared_len(p, KS) > 0 for j, p in enumerate(sea_u)]
    tiny = [j for j in range(len(sea_u)) if not ocean[j]]
    # slivers between the vanilla and the Natural Earth coast inside VT: land, so kept vanilla seas stay unchanged
    tiny += [j for j, p in enumerate(sea_u) if ocean[j] and j != big and p.area < SLIVER
             and p.difference(VT).buffer(-(1 - TOL)).is_empty]
    cls[np.isin(lab, tiny) & (cls == 'sea')] = 'land'
    sea_u, lab = group(cls == 'sea')
    print(f'  {len(sea_u)} sea parts, {len(small)} small islands flipped to sea, '
          f'{len(tiny)} lakes / in-VT slivers flipped to land ({time.time() - t:.0f}s)')
    # zone of every sea face
    zone = np.full(len(faces), -1)
    for i in np.nonzero(cls == 'sea')[0]:
        pt = shapely.Point(rx[i], ry[i])
        zone[i] = next((k for k, z in enumerate(zones) if z['geom'].contains(pt)), -1)
        if zone[i] < 0:
            zone[i] = int(np.argmin([z['geom'].distance(pt) for z in zones]))
    zinfo = zones
    sea = defaultdict(list)
    for i in np.nonzero(cls == 'sea')[0]:
        sea[int(zone[i])].append(faces[i])
    sea_parts = [(z, p) for z, fs in sea.items() for p in parts(shapely.union_all(fs))]
    land = defaultdict(list)
    for i in np.nonzero(cls == 'frame')[0]:
        land[FILLER[int(rx[i] >= XS)]].append(faces[i])
    for p in parts(shapely.union_all([faces[i] for i in np.nonzero(cls == 'land')[0]])):
        land[FILLER[int(p.centroid.x >= XS)]].append(p)
    land_parts = [(r, p) for r, fs in land.items() for p in parts(shapely.union_all(fs))]
    print(f'  {len(sea_parts)} zone sea parts, {len(land_parts)} filler land parts ({time.time() - t:.0f}s)')
    return dict(keep=keep, ksea=ksea, sea=sea_parts, land=land_parts, zinfo=zinfo, R=R, L=L)


# ---------------------------------------------------------------- stage 2: keys per variant
def assign(P, kinds, names, variant):
    """-> (grown {kept code: polygon}, new [(key, polygon)]) for 'zones' or 'reuse'."""
    keep, zinfo = P['keep'], P['zinfo']
    reg_of = {n: i for i, n in enumerate(names)}
    ksea = sorted(P['ksea'])
    ktree = shapely.STRtree([keep[c] for c in ksea])

    def touching(p):
        """[(shared length, kept sea code)] for kept vanilla sea areas sharing a border with p."""
        out = []
        for j in ktree.query(p, predicate='intersects'):
            n = shared_len(p, keep[ksea[j]])
            if n > 0:
                out.append((n, ksea[j]))
        return sorted(out, reverse=True)

    key = lambda z: zinfo[z]['key'] if variant == 'zones' else zinfo[z]['reuse']
    pieces = []
    for z, p in P['sea']:
        k = key(z)
        if p.intersection(VT).area >= 0.5 * p.area:          # pocket between vanilla and NE coasts: join the vanilla sea
            t = touching(p)
            if t:
                k = names[t[0][1] >> 16]
        pieces.append([k, p])
    def dissolve(pcs):
        by = defaultdict(list)
        for k, p in pcs:
            by[k].append(p)
        return [[k, q] for k, ps in by.items() for q in parts(shapely.union_all(ps))]
    pieces = dissolve(pieces)
    # small sea parts join the neighbour (new piece or kept vanilla sea) they share most border with
    tree = shapely.STRtree([p for _, p in pieces])
    moved = 0
    for i, (k, p) in enumerate(pieces):
        if p.area >= SMALL_SEA:
            continue
        cand = [(shared_len(p, pieces[j][1]), pieces[j][0]) for j in tree.query(p, predicate='intersects')
                if j != i and pieces[j][0] != k]
        cand += [(n, names[c >> 16]) for n, c in touching(p) if names[c >> 16] != k]
        cand = [c for c in cand if c[0] > 0]
        if cand:
            pieces[i][0] = max(cand)[1]; moved += 1
    pieces = dissolve(pieces)
    # slivers of any kind (< TINY u^2, e.g. between a vanilla edge and a coast line) join the new part they share most
    # border with; sea <-> land is allowed both ways at this size (no point of it is >= 1 u from land)
    allp = pieces + [[r, p] for r, p in P['land']]
    tree = shapely.STRtree([p for _, p in allp])
    tiny = 0
    for i, (k, p) in enumerate(allp):
        if p.area < TINY:
            cand = [(shared_len(p, allp[j][1]), allp[j][0]) for j in tree.query(p, predicate='intersects') if j != i]
            cand = [c for c in cand if c[0] > 0 and c[1] != k]
            if cand:
                allp[i][0] = max(cand)[1]; tiny += 1
    allp = dissolve(allp)
    pieces = [x for x in allp if x[0] not in FILLER]
    land = [x for x in allp if x[0] in FILLER]
    grown, new = {}, []
    for k, p in pieces:
        if k in reg_of:
            t = [(n, c) for n, c in touching(p) if c >> 16 == reg_of[k]]
            if t:
                grown.setdefault(t[0][1], []).append(p)
                continue
        new.append((k, p))
    # union with the vanilla area can leave micro holes where grid-snapped linework meets float32 vanilla coordinates
    unfill = lambda g: Polygon(g.exterior, [h for h in g.interiors if Polygon(h).area > 1e-3])
    grown = {c: unfill(shapely.union_all([keep[c]] + ps)) for c, ps in grown.items()}
    for c, g in grown.items():
        assert g.geom_type == 'Polygon', (names[c >> 16], g.geom_type)
    new += [(r, p) for r, p in land]
    print(f'  [{variant}] {len(pieces)} sea parts ({moved} small ones re-keyed, {tiny} slivers merged), '
          f'{len(grown)} vanilla areas grown: {sorted(names[c >> 16] for c in grown)}')
    return grown, new


# ---------------------------------------------------------------- stage 3: vertex pool, rings, welding
def f32(c):
    return np.asarray(c, np.float64).astype(np.float32)


def poly_rings(p):
    """shapely polygon -> [(is_outer, float32 (n,2))] with outer CCW, holes CW, no closing / repeated points."""
    p = orient(p, 1.0)
    out = []
    for outer, r in [(True, p.exterior)] + [(False, h) for h in p.interiors]:
        c = f32(np.asarray(r.coords)[:-1])
        keep = np.any(c != np.roll(c, 1, 0), axis=1)
        c = c[keep]
        x, y = c[:, 0].astype(np.float64), c[:, 1].astype(np.float64)
        assert len(c) >= 3 and abs((x * np.roll(y, -1) - np.roll(x, -1) * y).sum()) > 1e-6, ('degenerate ring', c[:4])
        out.append((outer, c))
    return out


class Pool:
    def __init__(self):
        self.idx, self.xy = {}, []

    def get(self, p):
        k = (float(p[0]), float(p[1]))
        i = self.idx.get(k)
        if i is None:
            i = self.idx[k] = len(self.xy); self.xy.append(k)
        return i

    def ring(self, c):
        return [self.get(p) for p in c]


def weld(areas, V):
    """Insert every pool vertex lying on an edge that has no twin into that edge (removes T-junctions), until each
    directed edge off the box border has its reverse in some ring."""
    lo, hi = proj.BOX_MIN, proj.BOX_MAX
    on_border = lambda a, b: (V[a, 0] == V[b, 0] and V[a, 0] in (lo[0], hi[0])) or \
                             (V[a, 1] == V[b, 1] and V[a, 1] in (lo[1], hi[1]))
    total = 0
    for _ in range(10):
        edges = {(a, b) for ar in areas for _, r in ar['rings'] for a, b in zip(r, r[1:] + r[:1])}
        bad = [(a, b) for a, b in edges if (b, a) not in edges and not on_border(a, b)]
        if not bad:
            return total
        cand = np.array(sorted({v for e in bad for v in e}))
        tree = shapely.STRtree(shapely.points(V[cand]))
        ins = {}
        for a, b in bad:
            A, B = V[a].astype(np.float64), V[b].astype(np.float64)
            env = shapely.box(min(A[0], B[0]) - 1e-3, min(A[1], B[1]) - 1e-3, max(A[0], B[0]) + 1e-3, max(A[1], B[1]) + 1e-3)
            d = B - A; L2 = d @ d
            pts = []
            for j in tree.query(env):
                v = int(cand[j])
                if v in (a, b):
                    continue
                q = V[v].astype(np.float64) - A
                t = (q @ d) / L2
                if 1e-9 < t < 1 - 1e-9 and abs(q[0] * d[1] - q[1] * d[0]) / math.sqrt(L2) < 5e-4:
                    pts.append((t, v))
            if pts:
                ins[(a, b)] = [v for _, v in sorted(pts)]
        if not ins:
            raise AssertionError(f'{len(bad)} unmatched edges, nothing to weld, e.g. {[(V[a], V[b]) for a, b in bad[:3]]}')
        for ar in areas:
            new = []
            for o, r in ar['rings']:
                rr = []
                for a, b in zip(r, r[1:] + r[:1]):
                    rr.append(a); rr += ins.get((a, b), [])
                if len(rr) != len(r):
                    ar['changed'] = True
                new.append((o, rr))
            ar['rings'] = new
        total += sum(map(len, ins.values()))
    raise AssertionError('weld did not converge')


# ---------------------------------------------------------------- stage 4: esf
def clone(x):
    if isinstance(x, list):
        return [clone(c) for c in x]
    if isinstance(x, Rec):
        return Rec(x.name, x.version, clone(x.children), None if x.items is None else [clone(i) for i in x.items])
    return Val(x.tag, x.value)


def area_item(tmpl, a):
    ar = clone(tmpl)
    ar[0], ar[1], ar[2] = Val(0x01, a['crossing']), Val(0x01, False), Val(0x01, a['passable'])
    return ar


def set_rings(ar, rings, tmpl_outline):
    ols = rm.sub(ar, 'outlines')
    if len(ols.items) != len(rings) or any(ol[0].value != o for ol, (o, _) in zip(ols.items, rings)):
        ols.items = []
        for o, _ in rings:
            ol = clone(tmpl_outline); ol[0] = Val(0x01, o); ols.items.append(ol)
    for ol, (_, r) in zip(ols.items, rings):
        ol[3] = rm.mkarr(0x48, np.array(r, np.uint32))


def relabel(labels, old, members):
    """component labels -> ids: a component keeps the most common vanilla id of its kept members, collisions and
    vanilla-free components get freed vanilla ids first, then max+1... -> (ids, number of kept areas relabelled)."""
    comp = defaultdict(list)
    for k in members:
        comp[labels[k]].append(k)
    used, ids = set(), {}
    pending = []
    for lab, ks in sorted(comp.items(), key=lambda kv: min(kv[1])):
        votes = Counter(old[k] for k in ks if old[k] is not None and old[k] != 0xFFFF)
        choice = next((v for v, _ in sorted(votes.items(), key=lambda x: (-x[1], x[0])) if v not in used), None)
        if choice is None:
            pending.append(lab)
        else:
            used.add(choice); ids[lab] = choice
    vanilla_ids = {old[k] for k in members if old[k] is not None}
    free = sorted(vanilla_ids - used)
    vanilla_ids.discard(0xFFFF)
    nxt = max(vanilla_ids | used) + 1
    for lab in pending:
        if free:
            ids[lab] = free.pop(0)
        else:
            ids[lab] = nxt; nxt += 1
    out = {k: ids[labels[k]] for k in members}
    return out, sum(1 for k in members if old[k] is not None and old[k] != out[k])


def build(variant, P, zones_cfg):
    t = time.time()
    e, rd, names, kinds, polys, drop = vanilla_model()
    grown, new = assign(P, kinds, names, variant)
    Vv = rm.verts(rd)
    items = rd.find('regions').items
    tmpl_region = items[names.index('eur_norwegian_sea')]
    tmpl_area = rm.sub(tmpl_region, 'areas').items[0]
    tmpl_outline = rm.sub(tmpl_area, 'outlines').items[0]
    # region list: vanilla in order, then new keys in seas.json order
    order = [z['key'] for z in P['zinfo']]
    new_keys = sorted({k for k, _ in new if k not in names}, key=order.index)
    names_all = names + new_keys
    zname = {z['key']: z['name'] for z in P['zinfo']}
    # filler slots: the new filler part overlapping a dropped vanilla filler area most takes its index, item and ids,
    # so vanilla area indices stay valid (startpos CAI_REGION_HLCI records list area indices per region)
    slot = {}
    for d in sorted(drop):
        cand = [j for j, (k, _) in enumerate(new) if k == names[d >> 16] and j not in slot.values()]
        slot[d] = max(cand, key=lambda j: new[j][1].intersection(polys[d]).area)
    slot_of = {j: d for d, j in slot.items()}
    pool, areas, kept_items, vused = Pool(), [], defaultdict(list), set()
    for ri, it in enumerate(items):
        for ai, ar in enumerate(rm.sub(it, 'areas').items):
            c = ri << 16 | ai
            f = rm.area_fields(ar)
            a = dict(ri=ri, item=ar, old=(f['pass_group'], f['nonwalk_group'], f['landmass']), code=c,
                     passable=f['passable'], changed=c in grown or c in drop, blob=rm.sub(ar, 'faces').children[0].value)
            if c in drop:
                a['geom'], a['blob'] = new[slot[c]][1], None
            elif c in grown:
                a['geom'] = grown[c]
            else:
                a['vring'] = [(o, idx) for o, idx, _ in rm.rings(ar)]
                vused.update(i for _, idx in a['vring'] for i in idx.tolist())
                vused.update(np.frombuffer(a['blob'], '<u4').tolist())
            areas.append(a); kept_items[ri].append(a)
    for j, (k, p) in enumerate(new):
        if j not in slot_of:
            a = dict(ri=names_all.index(k), item=None, old=(None, None, None), passable=k not in FILLER,
                     crossing=False, changed=True, geom=p, blob=None)
            areas.append(a); kept_items[a['ri']].append(a)
    for i in sorted(vused):                       # vanilla vertex order first
        pool.get(Vv[i])
    for a in areas:
        if 'vring' in a:
            a['rings'] = [(o, [pool.get(Vv[i]) for i in idx.tolist()]) for o, idx in a['vring']]
        else:
            a['rings'] = [(o, pool.ring(c)) for o, c in poly_rings(a['geom'])]
    V = np.array(pool.xy, np.float32)
    nweld = weld(areas, V)
    # float32 rounding + welding can collapse a hair-thin inlet into a zero-width spike (.. a b a ..): cut it off
    nspike = 0
    for a in areas:
        for k, (o, r) in enumerate(a['rings']):
            i = 0
            while len(r) > 3 and i < len(r):
                if r[i - 1] == r[(i + 1) % len(r)]:
                    for j in sorted({i, (i + 1) % len(r)}, reverse=True):
                        del r[j]
                    nspike += 1; i = max(i - 2, 0)
                else:
                    i += 1
            a['rings'][k] = (o, r)
    # faces: unchanged vanilla blob groups are re-indexed, changed groups and new areas are re-triangulated
    groups = defaultdict(list)
    for a in areas:
        groups[(a['ri'], a['blob']) if a['blob'] is not None else id(a)].append(a)
    blobs, ntri = [], 0
    for g in groups.values():
        if any(a['changed'] for a in g):
            T = rm.triangulate(V, [[(o, np.array(r)) for o, r in a['rings']] for a in g]).astype(np.int64)
            ntri += 1
        else:
            T = np.array([pool.idx[(float(Vv[i][0]), float(Vv[i][1]))] for i in np.frombuffer(g[0]['blob'], '<u4')],
                         np.int64).reshape(-1, 3)
        blobs.append((g, T))
    # compact the pool: drop vertices no ring or face uses (vanilla Steiner points of re-triangulated groups)
    used = sorted({i for a in areas for _, r in a['rings'] for i in r} | {int(i) for _, T in blobs for i in T.ravel()})
    nid = np.full(len(V), -1, np.int64); nid[used] = np.arange(len(used))
    V = V[used]
    for a in areas:
        a['rings'] = [(o, nid[r].tolist()) for o, r in a['rings']]
    print(f'  [{variant}] pool {len(V)} vertices, welded {nweld} T-junction vertices, cut {nspike} spikes ({time.time() - t:.0f}s)')
    # region items
    new_items = []
    for ri, key in enumerate(names_all):
        if ri < len(items):
            it = items[ri]
        else:
            it = clone(tmpl_region); it[0] = Val(0x0e, key)
            rm.sub(it, 'areas').items = []
        al = kept_items[ri]
        assert al, f'region {key} has no areas'
        out = []
        for a in al:
            ar = a['item'] if a['item'] is not None else area_item(tmpl_area, a)
            set_rings(ar, a['rings'], tmpl_outline)
            a['ar'] = ar
            out.append(ar)
        rm.sub(it, 'areas').items = out
        new_items.append(it)
    rd.find('regions').items = new_items
    rd.find('vertices').children[0] = rm.mkarr(0x4c, V)
    for g, T in blobs:
        blob = rm.mkarr(0x48, nid[T].ravel())
        for a in g:
            rm.sub(a['ar'], 'faces').children[0] = blob
    print(f'  [{variant}] {ntri} face groups triangulated ({time.time() - t:.0f}s)')
    rm.rebuild_bounds(rd)
    rd.children[1], rd.children[2] = Val(0x0c, tuple(map(float, proj.BOX_MIN))), Val(0x0c, tuple(map(float, proj.BOX_MAX)))
    rm.rebuild_connectivity(rd)
    kinds_all = [it[1].value for it in new_items]
    groups3, iters, F = rm.derive_area_groups(rd, kinds_all)
    by_ar = {id(a['ar']): a for a in areas}
    al = [by_ar[id(ar)] for _, _, _, ar in iters]
    walk = [kinds_all[a['ri']] == 'land' and a['passable'] for a in al]
    masks = dict(pass_group=[True] * len(al), nonwalk_group=[not w for w in walk],
                 landmass=[kinds_all[a['ri']] != 'sea' for a in al])
    relab = {}
    for fi, (field, pos) in enumerate((('pass_group', 5), ('nonwalk_group', 8), ('landmass', 9))):
        lab = groups3[field]
        if field == 'pass_group':                 # impassable areas are singletons
            lab = [l if a['passable'] else -1 - k for k, (l, a) in enumerate(zip(lab, al))]
        members = [k for k in range(len(al)) if masks[field][k]]
        ids, n = relabel(lab, [a['old'][fi] for a in al], members)
        relab[field] = n
        for k, a in enumerate(al):
            a['ar'][pos] = Val(0x07, ids.get(k, 0xFFFF))
    print(f'  [{variant}] ids: kept areas whose vanilla id changed {relab}')
    # mountains: keep those inside kept Europe
    UK = shapely.union_all(list(P['keep'].values()))
    mo = e.root.find('mountain_data').find('MOUNTAIN_OUTLINES')
    ob, bb = mo.find('OUTLINE_BLOCK'), mo.find('BOUNDS_BLOCK')
    keepm = [k for k, o in enumerate(ob.items) if Polygon(rm.nparr(o[0])).buffer(-1e-3).within(UK)]
    ob.items, bb.items = [ob.items[k] for k in keepm], [bb.items[k] for k in keepm]
    # groundtypes: vanilla stretched to the new box (regions_model resize rule)
    gt = e.root.find('groundtypes')
    rm._resize_rd(gt.find('region_data'), proj.BOX_MIN, proj.BOX_MAX)
    gt.children[gt.children.index(gt.find('query_info'))] = rm.build_query_info(gt.find('region_data'), False)
    e.root.children[e.root.children.index(e.root.find('query_info'))] = rm.build_query_info(rd, True)
    print(f'  [{variant}] quadtrees built ({time.time() - t:.0f}s)')
    build_theatre(e)
    info = dict(regions=len(new_items), new_keys=[(k, zname.get(k, k)) for k in new_keys],
                areas=len(al), vertices=len(V), mountains=len(keepm),
                areas_by_kind=dict(Counter(kinds_all[a['ri']] for a in al)))
    return e, info


# ---------------------------------------------------------------- stage 5: theatre rasters
def climate(lon, lat, z):
    """Land and sea climate index (research/05 s5 values) from longitude, latitude and ETOPO elevation (m).
    Land map: vanilla Europe bands by latitude (lc_mediterranean 4 south, eu_central_humid 14, eu_north 19/12, boreal
    1, tundra 0) extended with the Asian/American keys of the same table. Sea map: by latitude, '_coast' variant
    on the shelf (elevation > -200 m), sc_mediterranean for the Levant."""
    a, am = np.abs(lat), (lon < -25) & (lon > -170)
    n = lat >= 0
    old = np.select(
        [a < 10, a < 18,
         (a < 32) & n & (lon > 95), (a < 28) & n & (lon > 68), (a < 32) & ~n & (lon > 10) & (lon < 60), a < 32,
         (a < 45) & (lon < 45), (a < 45) & (lon < 75) & n, (a < 45) & n, (a < 45) & (lon > 160), a < 45,
         (a < 55) & (lon < 50), (a < 55) & (lon < 120), a < 55, a < 66],
        [7, 5, 9, 5, 5, 6, 4, 10, 9, 14, 4, 14, 8, 12, 1], 0)
    new = np.select(
        [a < 12, (a < 23) & n & (lon < -100), a < 23,
         (a < 35) & n & (lon < -104), (a < 35) & n & (lon < -97), (a < 35) & n, (a < 35) & (lon < -68), a < 35,
         (a < 48) & n & (lon < -115), (a < 48) & n & (lon < -98), (a < 48) & n, (a < 48) & (lon < -70), a < 48,
         (a < 55) & n, a < 55, a < 66],
        [20, 21, 13, 15, 21, 16, 15, 16, 21, 18, 17, 21, 18, 32, 21, 1], 0)
    land = np.where(am, new, old)
    land = np.where(z > 3000, 0, land).astype(np.uint8)
    sea = np.select([a > 62, a > 40, a > 23], [22, 23, 24], 25)
    sea = np.where(z > -200, sea + 5, sea)                 # 22..25 -> arctic/temperate/subtropic/tropic _coast 27..30
    sea = np.where((lon > 10) & (lon < 42) & (lat > 29) & (lat < 46), 26, sea)
    return land, sea.astype(np.uint8)


def wind(lat, cal):
    """Prevailing winds as (u, v) in vanilla's convention: the vanilla mid-latitude mean `cal` is taken as the
    westerlies; trades and polar easterlies are its reverse, the southern hemisphere mirrors v. This holds whatever
    sign convention vanilla uses, as long as its axes are the map axes. Calms at the equator / 30 deg are floored."""
    a = np.abs(lat)
    s = np.where(a < 30, -np.sin(np.pi * a / 30), np.where(a < 65, np.sin(np.pi * (a - 30) / 35),
                                                            -0.6 * np.sin(np.pi * np.clip(a - 65, 0, 25) / 25)))
    s = np.where(s >= 0, np.maximum(s, 0.3), np.minimum(s, -0.3))
    hem = np.where(lat >= 0, 1.0, -1.0)
    return s * cal[0], s * cal[1] * hem


def build_theatre(e):
    r = e.root
    for th in (r.find('theatres').items[0][0], r.find('theatres_and_region_keys').items[0][0]):
        th.children[1] = Val(0x0c, tuple(map(float, proj.THEATRE_MIN)))
        th.children[2] = Val(0x0c, tuple(map(float, proj.THEATRE_MAX)))
    th = r.find('theatres').items[0][0]
    (x0, y0), (x1, y1) = proj.THEATRE_MIN, proj.THEATRE_MAX
    vw, vh = proj.VT_MAX[0] - proj.VT_MIN[0], proj.VT_MAX[1] - proj.VT_MIN[1]
    off = (proj.VT_MIN[1] - y0, proj.VT_MIN[0] - x0)                 # rows from the south, cols from the west
    # outside climate on the wind grid (2.5 u), upsampled to the climate grid
    ww, wh = int((x1 - x0) * WIND_PPU), int((y1 - y0) * WIND_PPU)
    cx, cy = np.meshgrid(x0 + (np.arange(ww) + 0.5) / WIND_PPU, y0 + (np.arange(wh) + 0.5) / WIND_PPU)
    lon, lat = proj.to_lonlat(cx, cy)
    z = geo.etopo_sample(lon.ravel(), lat.ravel()).reshape(lon.shape)
    land, sea = climate(lon, lat, z)
    for cmr, coarse in zip(th.findall('climate_map'), (land, sea)):
        w, h = cmr.children[0].value, cmr.children[1].value
        v = rm.nparr(cmr.children[2]).reshape(h, w)                   # row 0 = south
        nvw, nvh = int(round(vw * CLIMATE_PPU)), int(round(vh * CLIMATE_PPU))
        v = v[(np.arange(nvh) * h // nvh)[:, None], (np.arange(nvw) * w // nvw)[None, :]]
        nw, nh = int((x1 - x0) * CLIMATE_PPU), int((y1 - y0) * CLIMATE_PPU)
        k = CLIMATE_PPU / WIND_PPU
        new = coarse[(np.arange(nh) / k).astype(int)[:, None], (np.arange(nw) / k).astype(int)[None, :]].copy()
        o = [int(q * CLIMATE_PPU) for q in off]
        new[o[0]:o[0] + nvh, o[1]:o[1] + nvw] = v
        cmr.children[0].value, cmr.children[1].value = nw, nh
        cmr.children[2] = Val(cmr.children[2].tag, new.tobytes())
    wm = th.find('wind_map')
    w, h, scale = wm.children[0].value, wm.children[1].value, wm.children[2].value
    v = np.frombuffer(wm.children[3].value, np.int8).reshape(h, w, 2)
    assert (w, h) == (int(vw * WIND_PPU), int(vh * WIND_PPU))
    rows = np.arange(h) / WIND_PPU + proj.VT_MIN[1]
    band = (rows > -20) & (rows < 120)                                # vanilla lat ~36..57: the westerlies
    cal = v[band].reshape(-1, 2).astype(np.float64).mean(0) * scale
    cal = cal / np.hypot(*cal) * 0.8
    u, vv = wind(lat, cal)
    new = np.clip(np.round(np.stack([u, vv], -1) / scale), -127, 127).astype(np.int8)
    o = [int(q * WIND_PPU) for q in off]
    new[o[0]:o[0] + h, o[1]:o[1] + w] = v
    wm.children[0].value, wm.children[1].value = ww, wh
    wm.children[3] = Val(wm.children[3].tag, new.tobytes())


# ---------------------------------------------------------------- preview + self-check
def preview(e, path, ppu=0.5):
    from PIL import Image, ImageDraw
    import zlib
    rd = e.root.find('region_data')
    names = [it[0].value for it in rd.find('regions').items]
    kinds = [it[1].value for it in rd.find('regions').items]
    polys = rm.area_polygons(rd)
    (x0, y0), (x1, y1) = proj.BOX_MIN, proj.BOX_MAX
    img = Image.new('RGB', (int((x1 - x0) * ppu), int((y1 - y0) * ppu))); d = ImageDraw.Draw(img)
    px = lambda c: [((x - x0) * ppu, (y1 - y) * ppu) for x, y in c]
    for c, p in sorted(polys.items(), key=lambda kv: -kv[1].area):
        n, k = names[c >> 16], kinds[c >> 16]
        h = zlib.crc32(n.encode())
        r, g, b = h & 255, h >> 8 & 255, h >> 16 & 255
        col = {'sea': (r // 5, 60 + g // 3, 140 + b // 3), 'river': (0, 230, 255)}.get(
            k, (90, 80, 70) if n in FILLER else (80 + r // 2, 80 + g // 2, 40 + b // 4))
        d.polygon(px(p.exterior.coords), fill=col)
    for xy in (proj.THEATRE_MIN + proj.THEATRE_MAX, proj.VT_MIN + proj.VT_MAX):
        d.rectangle([((xy[0] - x0) * ppu, (y1 - xy[3]) * ppu), ((xy[2] - x0) * ppu, (y1 - xy[1]) * ppu)], outline=(255, 255, 255))
    img.save(path)


SPOTS = [  # name, lon, lat, expected: 'vanilla' (same region as vanilla), 'sea', 'filler'
    ('Paris', 2.35, 48.86, 'vanilla'), ('London', -0.13, 51.51, 'vanilla'), ('Madrid', -3.70, 40.42, 'vanilla'),
    ('Vienna', 16.37, 48.21, 'vanilla'), ('Rome', 12.50, 41.90, 'vanilla'), ('Bay of Biscay', -5.0, 45.5, 'vanilla'),
    ('Tyrrhenian Sea', 11.5, 40.0, 'vanilla'), ('Baltic Sea', 19.0, 56.0, 'vanilla'), ('Moscow', 37.62, 55.75, 'vanilla'),
    ('mid-Pacific', -150.0, 15.0, 'sea'), ('west Pacific', 165.0, 10.0, 'sea'), ('Indian Ocean', 75.0, -20.0, 'sea'),
    ('Caribbean', -75.0, 15.0, 'sea'), ('Hudson Bay', -85.0, 60.0, 'sea'), ('Gulf of Guinea', 2.0, 0.0, 'sea'),
    ('Tasman Sea', 160.0, -38.0, 'sea'), ('Caspian Sea (lake: filler)', 51.0, 42.0, 'filler'), ('Azores waters', -30.0, 39.0, 'sea'),
    ('inland Brazil', -50.0, -10.0, 'filler'), ('Siberia', 100.0, 62.0, 'filler'), ('Australia', 134.0, -25.0, 'filler'),
    ('Sahara', 10.0, 23.0, 'filler'), ('Anatolia', 33.0, 39.0, 'filler')]


def _contained(tree, geoms, xy, pred=shapely.contains_xy):
    """[(g, point indices)] of the points xy inside geoms[g] (pred: contains_xy / intersects_xy), the vectorised form of
    tree.query(points, 'within' / 'intersects') (pairs per geometry, not in query order)."""
    qi, gi = tree.query(shapely.points(xy))
    o = np.argsort(gi, kind='stable'); qi, gi = qi[o], gi[o]
    if not len(gi): return []
    cut = np.flatnonzero(np.diff(gi)) + 1
    return [(g, a[pred(geoms[g], xy[a, 0], xy[a, 1])]) for a, g in zip(np.split(qi, cut), gi[np.r_[0, cut]])]


def check(path, n_random=10000):
    raw = open(path, 'rb').read()
    e = esf.loads(raw)
    assert esf.dumps(e) == raw, 'esf round-trip'
    r = e.root
    rd = r.find('region_data')
    names = [it[0].value for it in rd.find('regions').items]
    kinds = [it[1].value for it in rd.find('regions').items]
    V = rm.verts(rd); Vd = V.astype(np.float64)
    out = {}
    # tiling, orientation, vertex use
    polys = rm.area_polygons(rd)
    invalid = [c for c, p in polys.items() if not p.is_valid]
    tot = sum(p.area for p in polys.values())
    assert abs(tot - BOX.area) < 1e-6 * BOX.area, (tot, BOX.area)
    assert rd.children[1].value == tuple(map(float, proj.BOX_MIN)) and rd.children[2].value == tuple(map(float, proj.BOX_MAX))
    ring_use, face_use, bad_orient = set(), set(), 0
    def sarea(idx):
        x, y = Vd[idx, 0], Vd[idx, 1]
        return 0.5 * (x * np.roll(y, -1) - np.roll(x, -1) * y).sum()
    for _, _, _, ar in rm.iter_areas(rd):
        for o, idx, _ in rm.rings(ar):
            ring_use.update(idx.tolist())
            bad_orient += (sarea(idx) > 0) != o
    own, nedges = {}, 0
    for ri, ai, _, ar in rm.iter_areas(rd):
        for _, idx, _ in rm.rings(ar):
            for a, b in zip(idx.tolist(), np.roll(idx, -1).tolist()):
                nedges += 1; own[(a, b)] = ri << 16 | ai
    assert len(own) == nedges, 'directed edge owned twice'
    lo, hi = proj.BOX_MIN, proj.BOX_MAX
    border = lambda a, b: (V[a, 0] == V[b, 0] and V[a, 0] in lo[:1] + hi[:1]) or (V[a, 1] == V[b, 1] and V[a, 1] in lo[1:] + hi[1:])
    untwinned = sum(1 for (a, b) in own if (b, a) not in own and not border(a, b))
    # faces
    blobs = {}
    for ri, ai, it, ar in rm.iter_areas(rd):
        blobs.setdefault(rm.sub(ar, 'faces').children[0].value, []).append(ri << 16 | ai)
    face_bad = 0
    for blob, codes in blobs.items():
        T = np.frombuffer(blob, '<u4').reshape(-1, 3)
        face_use.update(T.ravel().tolist())
        ta = rm.tri_signed_area(V, T)
        pa = sum(polys[c].area for c in codes)
        face_bad += not ((ta < 0).all() and abs(-ta.sum() - pa) < 1e-4 * max(pa, 1))
    unused = len(V) - len(ring_use | face_use)
    dup = len(V) - len({(float(x), float(y)) for x, y in V})
    # connectivity derivable + symmetric
    before = esf.dumps(e)
    rm.rebuild_connectivity(rd)
    conn_same = esf.dumps(e) == before
    nb = defaultdict(set)
    for ri, ai, _, ar in rm.iter_areas(rd):
        for _, _, ol in rm.rings(ar):
            for c in rm.sub(ol, 'connectivity').items:
                if c[0].value != rm.NONE:
                    nb[ri << 16 | ai].add(c[0].value)
    asym = sum(1 for a, bs in nb.items() for b in bs if a not in nb[b])
    # id partitions
    groups, items, F = rm.derive_area_groups(rd, kinds)
    walk = [kinds[it[0]] == 'land' and x['passable'] for it, x in zip(items, F)]
    ids_ok = (rm.same_partition(groups['nonwalk_group'], [x['nonwalk_group'] for x in F], [not w for w in walk])
              and rm.same_partition(groups['landmass'], [x['landmass'] for x in F], [kinds[it[0]] != 'sea' for it in items])
              and rm.same_partition(groups['pass_group'], [x['pass_group'] for x in F], [x['passable'] for x in F])
              and len({x['pass_group'] for x in F if not x['passable']}) == sum(not x['passable'] for x in F)
              and not ({x['pass_group'] for x in F if not x['passable']} & {x['pass_group'] for x in F if x['passable']}))
    # region keys / settlements
    keys = {k[0].value: k[1].value for k in r.find('theatres_and_region_keys').items[0][0].find('region_keys').items}
    reg_ok = all((rm.vals(it)[4].value == 0) == (rm.sub(it, 'settlement_and_slots') is not None) == (it[0].value in keys)
                 for it in rd.find('regions').items)
    # quadtree vs polygon containment
    qi = r.find('query_info')
    hdr = [v.value for v in rm.vals(qi.children)]
    codes = list(polys)
    tgeo = np.array([polys[c] for c in codes], object)
    tree = shapely.STRtree(tgeo)
    rng = np.random.default_rng(7)
    pts = rng.uniform(proj.BOX_MIN, proj.BOX_MAX, (n_random, 2))
    hit = tree.query(shapely.points(pts), predicate='within')
    cnt = np.bincount(hit[0], minlength=len(pts))
    where = np.full(len(pts), -1); where[hit[0]] = np.array(codes)[hit[1]]
    qmis = sum(1 for k, p in enumerate(pts) if cnt[k] == 1 and rm.query_point(qi, V, p) != where[k])
    # groundtypes
    gt = r.find('groundtypes'); grd = gt.find('region_data')
    gp = rm.area_polygons(grd)
    gtot = sum(p.area for p in gp.values())
    gcodes = list(gp); gtree = shapely.STRtree([gp[c] for c in gcodes]); gV = rm.verts(grd)
    gpts = rng.uniform(proj.BOX_MIN, proj.BOX_MAX, (2000, 2))
    gh = gtree.query(shapely.points(gpts), predicate='within')
    gmis = sum(1 for k, c in zip(gh[0], gh[1]) if rm.query_point(gt.find('query_info'), gV, gpts[k]) != gcodes[c])
    # theatre rasters
    th = r.find('theatres').items[0][0]
    cms = th.findall('climate_map'); wm = th.find('wind_map')
    W, H = proj.THEATRE_MAX[0] - proj.THEATRE_MIN[0], proj.THEATRE_MAX[1] - proj.THEATRE_MIN[1]
    rast_ok = (th.children[1].value == tuple(map(float, proj.THEATRE_MIN)) and th.children[2].value == tuple(map(float, proj.THEATRE_MAX))
               and all((c.children[0].value, c.children[1].value, len(c.children[2].value)) ==
                       (int(W * CLIMATE_PPU), int(H * CLIMATE_PPU), int(W * CLIMATE_PPU) * int(H * CLIMATE_PPU)) for c in cms)
               and (wm.children[0].value, wm.children[1].value, len(wm.children[3].value)) ==
                   (int(W * WIND_PPU), int(H * WIND_PPU), 2 * int(W * WIND_PPU) * int(H * WIND_PPU)))
    # requirement: water outside VT >= 1 u from worldgeo land is sea
    land = worldgeo.land()
    lg = np.array(land.geoms, object)
    lt = shapely.STRtree(lg)
    q = rng.uniform(proj.THEATRE_MIN, proj.THEATRE_MAX, (100000, 2))
    q = q[~shapely.contains_xy(VT, q[:, 0], q[:, 1])]
    # dist(point, land) >= 1.0: inside a polygon, or a boundary segment within 1.0 (the same segment distances GEOS takes,
    # at a hundredth of query_nearest's cost); then not inside any lake-filled polygon.
    qp = shapely.points(q)
    near = np.zeros(len(q), bool)
    for _, a in _contained(lt, lg, q): near[a] = True
    co, ix = shapely.get_coordinates(shapely.get_rings(lg), return_index=True)
    ok = np.flatnonzero(ix[1:] == ix[:-1])                              # consecutive vertices of one ring
    seg = shapely.linestrings(np.stack([co[ok], co[ok + 1]], axis=1))
    hi, gi = shapely.STRtree(seg).query(qp[~near], predicate='dwithin', distance=1.0)
    hi, gi = np.flatnonzero(~near)[hi], gi
    near[hi[shapely.distance(qp[hi], seg[gi]) < 1.0]] = True
    water = q[~near]
    filled = np.array([Polygon(p.exterior) for p in land.geoms], object)     # lakes = holes of land polygons
    lake = np.zeros(len(water), bool)
    for _, a in _contained(shapely.STRtree(filled), filled, water): lake[a] = True
    water = water[~lake]
    # kind of the region at each point; a point on a shared edge hits several, then the tree's own pair order decides
    hits = _contained(tree, tgeo, water, shapely.intersects_xy)
    nh = np.zeros(len(water), int)
    for _, a in hits: nh[a] += 1
    kind_at = np.full(len(water), '', object)
    for g, a in hits: kind_at[a[nh[a] == 1]] = kinds[codes[g] >> 16]
    many = np.flatnonzero(nh > 1)
    if len(many):
        hh = tree.query(shapely.points(water[many]), predicate='intersects')
        kind_at[many[hh[0]]] = [kinds[codes[c] >> 16] for c in hh[1]]
    not_sea = int((kind_at != 'sea').sum())
    sub_w = water[:3000]
    q_not_sea = sum(1 for p in sub_w if kinds[rm.query_point(qi, V, p) >> 16] != 'sea')
    # vanilla Europe preserved
    van = esf.load(VANILLA); vrd = van.root.find('region_data')
    vnames = [it[0].value for it in vrd.find('regions').items]
    vpolys = rm.area_polygons(vrd)
    changed, grown = [], []
    for c, vp in vpolys.items():
        ri, ai = c >> 16, c & 0xFFFF
        if vnames[ri] in FILLER and not vp.within(VT):
            continue
        assert names[ri] == vnames[ri]
        np_ = polys.get(c)
        if np_ is None or vp.difference(np_).area > 1e-3:
            changed.append(f'{vnames[ri]}#{ai}')          # vanilla geometry lost
        elif np_.difference(vp).area > 1e-3:
            grown.append(f'{vnames[ri]}#{ai}')            # vanilla area kept and extended outward (sea growth)
    vqi, vV = van.root.find('query_info'), rm.verts(vrd)
    spots = []
    for nm, lon, lat, want in SPOTS:
        x, y = proj.to_world(lon, lat)
        p = np.array([float(x), float(y)])
        got = names[rm.query_point(qi, V, p) >> 16]
        ok = {'vanilla': lambda: got == vnames[rm.query_point(vqi, vV, p) >> 16],
              'sea': lambda: kinds[names.index(got)] == 'sea',
              'filler': lambda: got in FILLER}[want]()
        spots.append((nm, round(float(x), 1), round(float(y), 1), got, 'ok' if ok else 'FAIL'))
    out = dict(regions=len(names), areas=len(polys), vertices=len(V), invalid_polygons=len(invalid),
               area_sum=round(tot, 3), box_area=BOX.area, bad_ring_orientation=bad_orient, untwinned_edges=untwinned,
               bad_face_blobs=face_bad, face_blobs=len(blobs), unused_vertices=unused, duplicate_vertices=dup,
               connectivity_rebuild_identical=conn_same, connectivity_asymmetric=asym, id_partitions_ok=ids_ok,
               region_keys_ok=reg_ok, quadtree_header=hdr, quadtree_header_formula=hdr[1] == (3 * hdr[0] + 1) // 4,
               quadtree_mismatch=f'{qmis}/{int((cnt == 1).sum())}', groundtypes_area_ok=abs(gtot - BOX.area) < 1e-6 * BOX.area,
               groundtypes_quadtree_mismatch=f'{gmis}/{len(gh[0])}', theatre_rasters_ok=rast_ok,
               water_ge1_not_sea=f'{not_sea}/{len(water)}', water_ge1_query_not_sea=f'{q_not_sea}/{len(sub_w)}',
               vanilla_areas_changed=changed, vanilla_areas_grown=grown)
    return out, spots


def report(path):
    out, spots = check(path)
    print(f'== check {os.path.relpath(path, ROOT)}')
    for k, v in out.items():
        print(f'  {k}: {v}')
    for s in spots:
        print('   ', *s)
    hard = (out['invalid_polygons'] == 0 and out['bad_ring_orientation'] == 0 and out['untwinned_edges'] == 0
            and out['bad_face_blobs'] == 0 and out['unused_vertices'] == 0 and out['duplicate_vertices'] == 0
            and out['connectivity_rebuild_identical'] and out['connectivity_asymmetric'] == 0 and out['id_partitions_ok']
            and out['region_keys_ok'] and out['quadtree_header_formula'] and out['quadtree_mismatch'].startswith('0/')
            and out['groundtypes_area_ok'] and out['groundtypes_quadtree_mismatch'].startswith('0/')
            and out['theatre_rasters_ok'] and out['water_ge1_not_sea'].startswith('0/')
            and out['water_ge1_query_not_sea'].startswith('0/') and not out['vanilla_areas_changed'] and all(s[-1] == 'ok' for s in spots))
    print('  PASS' if hard else '  FAIL')
    return hard


if __name__ == '__main__':
    files = [os.path.join(OUT, f) for f in ('regions_reuse.esf', 'regions.esf')]
    if sys.argv[1:] == ['check']:
        sys.exit(0 if all([report(f) for f in files]) else 1)
    zones = load_zones()
    e, rd, names, kinds, polys, drop = vanilla_model()
    P = partition(polys, drop, kinds, zones)
    for variant, fn in (('reuse', 'regions_reuse.esf'), ('zones', 'regions.esf')):
        e2, info = build(variant, P, zones)
        os.makedirs(OUT, exist_ok=True)
        open(os.path.join(OUT, fn), 'wb').write(esf.dumps(e2))
        print(variant, json.dumps({k: v for k, v in info.items() if k != 'new_keys'}), len(info['new_keys']), 'new keys')
        if variant == 'zones':
            json.dump(info, open(os.path.join(OUT, 'zones_info.json'), 'w'), indent=1)
            preview(e2, os.path.join(OUT, 'preview.png'))
        else:
            preview(e2, os.path.join(OUT, 'preview_reuse.png'))
    sys.exit(0 if all([report(f) for f in files]) else 1)
