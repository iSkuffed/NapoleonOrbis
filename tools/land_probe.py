"""First new land region (research/10 section 5): Newfoundland becomes region `nam_probe` (settlement Probetown,
owned by Britain, vanilla CAI, no CAI shadow).

  .venv/bin/python tools/land_probe.py [--variant notrade]          build -> work/world/probe5[_notrade]/
  .venv/bin/python tools/land_probe.py check [--variant notrade]    self-checks on the written files

Output: overlay/ (copy over work/mods/world_m1 before packing: campaign_maps/nap_world/{regions,pathfinding,poi,
trade_routes,sea_grids}.esf, db/regions_tables/regions, db/campaign_map_settlements_tables/campaign_map_settlements),
loc_rows.tsv (merge with world_build.localisation), startpos.esf, build_info.json.
Variant notrade = spec step 10: the settlement is not registered in trade_routes.esf / SETTLEMENT_INDICES.
"""
import argparse, collections, json, math, os, shutil, struct, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import shapely
from shapely.geometry import Point, Polygon, box

import esf, geo, proj, loc, dbtable, packtool, campaign_misc as cm, regions_model as rm
import pathfinding_model as pm, pf_check, pf_gen, probe_g3
from esf import Rec, Val
from regions_world import clone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W = os.path.join(ROOT, 'work/world')
M1 = os.path.join(ROOT, 'work/mods/world_m1/campaign_maps/nap_world')
SRC = geo.GAME + '/campaign_maps/nap_europe'
MAPDIR = 'campaign_maps/nap_world'

KEY, TOWN, NAME, TOWN_NAME = 'nam_probe', 'probetown', 'Newfoundland', 'Probetown'
TPL, TPL_TOWN = 'eur_ireland', 'dublin'               # template region (Britain-owned island)
TEST_LONLAT = (-56.0, 48.5)                           # inside Newfoundland
OWNER, GOV = 'britain', 739282900                     # Britain's GOVERNORSHIP handle (= Ireland REGION[22])
LOC_SUFFIX = 1805000001                               # settlement CAMPAIGN_LOCALISATION suffix
RGB = (201, 77, 13)                                   # regions_tables colour (not in the table or the lookup palette)
REBEL_KEY, REBEL_NAME = 'british_rebels', 'Newfoundland Rebels'
KEEP_SLOTS = ('settlement_road', 'settlement_1_slot', 'settlement_fortification')
FIX, S = pf_gen.FIX, pf_gen.S
LAND_BAND = 1.0                                       # u of off-map between pathfinding land and sea (vanilla median)
OFF = probe_g3.OFF
DIRS, OPP = probe_g3.DIRS, pf_gen.OPP
LAND_COST, BLOCKED = 0x1f, 0xff                       # vanilla: land<->land 0x1f, coast directions without land 0xff
PASS_GROUP_APPEND = False                             # False: island keeps its pass_group (dense ids); True: max+1


def out_dir(variant):
    return os.path.join(W, 'probe5' if variant == 'trade' else 'probe5_notrade')


# ---------------------------------------------------------------- inputs
def inputs():
    e = esf.load(M1 + '/regions.esf')
    n = len(e.root.find('region_data').find('regions').items)
    if n == 101:
        return dict(regions=M1 + '/regions.esf', poi=M1 + '/poi.esf', why='work/mods/world_m1 is the plain 101-region build')
    assert n == 139, n
    return dict(regions=W + '/regions/regions_reuse.esf', poi=SRC + '/poi.esf',
                why='work/mods/world_m1 regions.esf has 139 regions (zones build): using regions_reuse.esf + vanilla poi.esf')


# ---------------------------------------------------------------- regions.esf, part 1: carve the island
def find_island(rd):
    """-> (area index in eur_map_west, polygon, neighbour region index): the impassable filler area at TEST_LONLAT whose
    only neighbour is one sea region."""
    items = rd.find('regions').items
    names, kinds = [it[0].value for it in items], [it[1].value for it in items]
    wi = names.index('eur_map_west')
    p = Point(*map(float, proj.to_world(*TEST_LONLAT)))
    polys = rm.area_polygons(rd)
    ai = next(c & 0xFFFF for c, q in polys.items() if c >> 16 == wi and q.contains(p))
    ar = rm.sub(items[wi], 'areas').items[ai]
    f = rm.area_fields(ar)
    assert not f['passable'] and len(rm.rings(ar)) == 1, f
    nb = {c[0].value >> 16 for _, _, ol in rm.rings(ar) for c in rm.sub(ol, 'connectivity').items}
    assert len(nb) == 1 and kinds[next(iter(nb))] == 'sea', nb
    return wi, ai, polys[wi << 16 | ai], next(iter(nb))


def regions_finish(e, wi, ai, pos, D, pass_group):
    """Move area ai of eur_map_west into a new land region KEY (index = current count) cloned from TPL, with the
    TPL settlement + KEEP_SLOTS translated by D; rebuild bounds/connectivity/quadtree."""
    rd = e.root.find('region_data')
    items = rd.find('regions').items
    names = [it[0].value for it in items]
    tpl = items[names.index(TPL)]
    t_ar = rm.sub(tpl, 'areas').items[0]
    assert rm.area_fields(t_ar)['passable'] and rm.area_fields(t_ar)['nonwalk_group'] == 0xFFFF
    w_areas = rm.sub(items[wi], 'areas').items
    ar = w_areas.pop(ai)
    ar[2] = Val(0x01, True)                              # passable
    ar[5] = Val(0x07, pass_group)
    ar[8] = Val(0x07, 0xFFFF)                            # walkable land has no nonwalk group (= Ireland)
    it = clone(tpl)
    it[0] = Val(0x0e, KEY)
    rm.sub(it, 'areas').items = [ar]
    ss = rm.sub(it, 'settlement_and_slots')
    ss.children[0] = Val(0x0c, pos)
    shift = lambda v: rm.mkarr(0x4c, rm.nparr(v) + np.array(D, np.float32)) if v.value else v
    ss.children[1] = shift(ss.children[1])
    sd = ss.find('slot_descriptions')
    keep = [s for s in sd.items if s[1].value in KEEP_SLOTS]
    assert len(keep) == 3
    for k, s in enumerate(keep):
        typ, suf = s[1].value, int(s[0].value.rsplit(':', 1)[1])
        assert suf == k, s[0].value                      # suffix = index in slot_descriptions (research/10)
        s[0] = Val(0x0e, f'settlement:{KEY}:{TOWN}:{typ}:{k}')
        x, h, y = s[2].value
        s[2] = Val(0x0d, (f32(x + D[0]), h, f32(y + D[1])))
        s[3] = Val(0x0c, (f32(s[3].value[0] + D[0]), f32(s[3].value[1] + D[1])))
        for j in (7, 8, 9):
            s[j] = shift(s[j])
    sd.items = keep
    items.append(it)
    th = e.root.find('theatres_and_region_keys').items[0][0].find('region_keys')
    th.items.append([Val(0x0e, KEY), Val(0x0c, pos)])
    rm.rebuild_bounds(rd)
    rd.children[1], rd.children[2] = Val(0x0c, tuple(map(float, proj.BOX_MIN))), Val(0x0c, tuple(map(float, proj.BOX_MAX)))
    rm.rebuild_connectivity(rd)
    e.root.children[e.root.children.index(e.root.find('query_info'))] = rm.build_query_info(rd, True)
    return len(items) - 1


def f32(v):
    return float(np.float32(v))


# ---------------------------------------------------------------- pathfinding.esf
_SEA = {}


def sea_id(g):
    c = _SEA.get(id(g))
    if c is None or c[0] is not g:                         # the entry keeps g alive, so its id cannot be reused
        c = _SEA[id(g)] = (g, g.path_domains().index(()))
    return c[1]


def side_intervals(area, P, i, axis, v):
    """pf_check.side_intervals with the grid's sea domain instead of the hard-coded 72."""
    c, sea = area.grid.cells[i], sea_id(area.grid)
    polys = ([(c.uniform, area.points(i, (0, 2, 3, 1)))] if c.uniform else
             [(b.trait, area.points(i, P[b.polygon_offset])) for b in c.boundaries])
    out = []
    for t, pts in polys:
        cls = 'x' if t.kind in (2, 3) else 's' if t.path_id == sea else 'l'
        for p, q in zip(pts, pts[1:] + pts[:1]):
            if p[axis] == q[axis] == v and p[1 - axis] != q[1 - axis]:
                out.append((min(p[1 - axis], q[1 - axis]), max(p[1 - axis], q[1 - axis]), cls))
    return sorted(out)


pf_check.side_intervals = side_intervals     # pf_check.check calls the module global; see report for the real fix
pf_check.sea_of = lambda area: sea_id(area.grid)     # and its uniform-pair shortcut


def cell_of(g, x, y):
    return (int(y * FIX) - g.origin_fixed[1]) // S * g.columns + (int(x * FIX) - g.origin_fixed[0]) // S


def segs(pts, axis, v):
    return [tuple(sorted((p[1 - axis], q[1 - axis]))) for p, q in zip(pts, pts[1:] + pts[:1])
            if p[axis] == q[axis] == v and p[1 - axis] != q[1 - axis]]


def offmap_component(area, P, start):
    """{cell: [polygon index]} of the off-map (kind 2/3) polygons joined to `start` across shared edge segments."""
    g, C, R = area.grid, area.grid.columns, area.grid.rows
    polys = lambda i: probe_g3.cell_polys(area, P, i)
    seen, todo = {start}, [start]
    while todo:
        i, k = todo.pop()
        r, col = divmod(i, C)
        x0, y0 = g.corners(i)[0]
        pts = polys(i)[k][1]
        E = {frozenset(e) for e in zip(pts, pts[1:] + pts[:1])}
        for k2, (t2, q) in enumerate(polys(i)):
            if k2 != k and t2.kind in (2, 3) and (i, k2) not in seen and E & {frozenset(e) for e in zip(q, q[1:] + q[:1])}:
                seen.add((i, k2)); todo.append((i, k2))
        for dx, dy, axis, v in ((1, 0, 0, x0 + S), (-1, 0, 0, x0), (0, 1, 1, y0 + S), (0, -1, 1, y0)):
            mine = segs(pts, axis, v)
            if not mine:
                continue
            assert 0 <= col + dx < C and 0 <= r + dy < R, 'component reaches the grid edge'
            j = (r + dy) * C + col + dx
            for k2, (t2, q) in enumerate(polys(j)):
                if t2.kind in (2, 3) and (j, k2) not in seen and any(
                        min(a1, b1) > max(a0, b0) for a0, a1 in mine for b0, b1 in segs(q, axis, v)):
                    seen.add((j, k2)); todo.append((j, k2))
    comp = collections.defaultdict(list)
    for i, k in seen:
        comp[i].append(k)
    return comp


def snap_ring(coords):
    """Integer ring with no vertex on a grid line and a vertex at every grid-line crossing, so each edge lies in one
    closed cell and neighbouring cells clip it at identical points."""
    pts = []
    for x, y in coords[:-1]:
        x, y = int(round(x)), int(round(y))
        pts.append((x + (x % S == 0), y + (y % S == 0)))
    out = []
    for p, q in zip(pts, pts[1:] + pts[:1]):
        out.append(p)
        cr = []
        for a in (0, 1):
            if p[a] == q[a]:
                continue
            lo, hi = sorted((p[a], q[a]))
            for k in range(lo // S + 1, hi // S + 1):
                v = k * S
                t = (v - p[a]) / (q[a] - p[a])
                o = int(round(p[1 - a] + t * (q[1 - a] - p[1 - a])))
                cr.append((t, (v, o) if a == 0 else (o, v)))
        for _, c in sorted(cr):
            if c != out[-1]:
                out.append(c)
    while out[-1] == out[0]:
        out.pop()
    return out


def edge_in_cell(p, q):
    return all((max(p[a], q[a]) <= (min(p[a], q[a]) // S + 1) * S) for a in (0, 1))


def renumber_domains(g, region_index):
    """Insert a singleton path domain for region_index before the sea separator: domain = old singleton count,
    sea and every composite +1 (1023 untouched)."""
    n = len(g.region_indices)
    assert g.passable_region_count == g.listed_region_count == n
    sep = g.path_table.index(0)
    assert sep == n
    g.region_indices = g.region_indices + (region_index,)
    g.path_table = g.path_table[:sep] + (n + 1,) + g.path_table[sep:]
    g.passable_region_count = g.listed_region_count = n + 1
    up = lambda t: t if t.path_id < n or t.path_id == 1023 else pm.Trait(t.kind, t.middle20, t.contact_mask, t.path_id + 1)
    for c in g.cells:
        if c.uniform is not None:
            c.uniform = up(c.uniform)
        for b in c.boundaries:
            b.trait = up(b.trait)
    _SEA.clear(); probe_g3._SEA.clear()
    return n                                          # the new domain id


def land_mask(c, dom):
    if c.uniform is not None:
        return 255 if c.uniform.kind == 0 and c.uniform.path_id == dom else 0
    m = 0
    for b in c.boundaries:
        if b.trait.kind == 0 and b.trait.path_id == dom:
            m |= b.trait.contact_mask
    return m


def pathfinding(region_poly, region_index):
    """-> (model, land polygon L in world units, stats). Off-map polygons of the island's component become land
    L = (component ∩ region polygon) shrunk by LAND_BAND, clipped per cell; sea polygons untouched."""
    m = pm.PathfindingModel.load(W + '/pf/pathfinding.esf')
    area = m.areas[0]
    g, P = area.grid, area.polygons()
    C, R = g.columns, g.rows
    assert (C, R) == (pf_gen.C, pf_gen.R)
    dom = renumber_domains(g, region_index)
    sea = sea_id(g)
    x, y = map(float, proj.to_world(*TEST_LONLAT))
    i0 = cell_of(g, x, y)
    pt = Point(x * FIX, y * FIX)
    k0 = next(k for k, (t, q) in enumerate(probe_g3.cell_polys(area, P, i0)) if t.kind == 2 and Polygon(q).covers(pt))
    comp = offmap_component(area, P, (i0, k0))
    for i, ks in comp.items():
        assert all(probe_g3.cell_polys(area, P, i)[k][0] == OFF for k in ks), i
    O = shapely.union_all([Polygon(probe_g3.cell_polys(area, P, i)[k][1]) for i, ks in comp.items() for k in ks])
    Rf = shapely.transform(region_poly, lambda c: c * FIX)
    L = O.intersection(Rf).buffer(-LAND_BAND * FIX)
    L = max(getattr(L, 'geoms', [L]), key=lambda p: p.area)
    L = shapely.simplify(L, 0.05 * FIX)
    L = max(getattr(L, 'geoms', [L]), key=lambda p: p.area)
    assert not L.interiors
    ring = snap_ring(list(L.exterior.coords))
    Ls = Polygon(ring)
    assert Ls.is_valid and all(edge_in_cell(p, q) for p, q in zip(ring, ring[1:] + ring[:1]))
    assert Ls.within(O) and O.boundary.distance(Ls) > 0.5 * LAND_BAND * FIX
    # per cell: land = cell ∩ Ls, new off-map = component off-map - land
    verts = list(area.vertices_fixed)
    vid = {}
    for n, p in enumerate(verts):
        if n >= 4:
            vid.setdefault(p, n)
    key = max(P) + 1000
    kept = bytearray(b'\x01' * (C * R))
    stats = collections.Counter()

    def ids_of(k, poly):
        p = shapely.simplify(poly, 0)
        pts = [(int(a), int(b)) for a, b in p.exterior.coords[:-1]]
        assert all(float(a) == q[0] and float(b) == q[1] for (a, b), q in zip(p.exterior.coords[:-1], pts))
        if not p.exterior.is_ccw:
            pts.reverse()
        corners = g.corners(k)
        out = []
        for q in pts:
            if q in corners:
                out.append(corners.index(q))
            else:
                if q not in vid:
                    vid[q] = len(verts); verts.append(q)
                out.append(vid[q])
        return tuple(out)

    land_trait = pm.Trait(0, 0, 255, dom)
    for k in sorted(comp):
        c = g.cells[k]
        cps = probe_g3.cell_polys(area, P, k)
        cellbox = box(*g.corners(k)[0], *g.corners(k)[3])
        land = shapely.intersection(cellbox, Ls, grid_size=1.0)
        lp = sorted((p for p in getattr(land, 'geoms', [land]) if p.geom_type == 'Polygon' and p.area > 0), key=lambda p: -p.area)
        if not lp:
            continue
        kept[k] = 0
        if sum(p.area for p in lp) == S * S:
            g.cells[k] = pm.Cell(c.costs8, uniform=land_trait); stats['uniform land'] += 1
            continue
        off = shapely.union_all([Polygon(cps[j][1]) for j in comp[k]], grid_size=1.0)
        lu = shapely.union_all(lp, grid_size=1.0)
        assert lu.difference(off, grid_size=1.0).area == 0, k
        rest = off.difference(lu, grid_size=1.0)
        op = sorted((p for p in getattr(rest, 'geoms', [rest]) if p.geom_type == 'Polygon' and p.area > 0), key=lambda p: -p.area)
        assert not any(p.interiors for p in lp + op), ('hole', k)
        bounds = [b for j, b in enumerate(c.boundaries) if j not in comp[k]]
        for trait, ps in ((land_trait, lp), (OFF, op)):
            for p in ps:
                P[key] = ids_of(k, p)
                bounds.append(pm.Boundary(trait, key)); key += 1
        g.cells[k] = pm.Cell(c.costs8, bounds)
        stats['mixed'] += 1
        stats['max land polys/cell'] = max(stats['max land polys/cell'], len(lp))
        stats['cells >4 land polys'] += len(lp) > 4
    area.vertices_fixed = tuple(verts)
    pf_gen.weld(area, P, kept)
    mod = [k for k in range(C * R) if not kept[k]]
    # land traits: contact mask, then middle20 (research/06 rule, probe_g3.middle20)
    for k in mod:
        c = g.cells[k]
        for b in c.boundaries:
            if b.trait.kind == 0 and b.trait.path_id == dom:
                b.trait = pm.Trait(0, 0, pm.contact_mask(area.points(k, P[b.polygon_offset]), g.corners(k)), dom)
    for k in mod:
        c = g.cells[k]
        if c.uniform is not None:
            g.cells[k] = pm.Cell(c.costs8, uniform=pm.Trait(0, probe_g3.middle20(area, P, k, area.points(k, (0, 2, 3, 1)), c.uniform),
                                                            255, dom))
            continue
        for b in c.boundaries:
            if b.trait.kind == 0 and b.trait.path_id == dom:
                t = b.trait
                b.trait = pm.Trait(0, probe_g3.middle20(area, P, k, area.points(k, P[b.polygon_offset]), t), t.contact_mask, dom)
    # costs: land<->land 0x1f, sea-open directions kept, everything else of a land cell blocked (vanilla coast cells)
    for k in mod:
        r, col = divmod(k, C)
        cs = bytearray(g.cells[k].costs8)
        mk = land_mask(g.cells[k], dom)
        for d, (dx, dy) in enumerate(DIRS):
            j = (r + dy) * C + col + dx
            if mk >> d & 1 and land_mask(g.cells[j], dom) >> OPP[d] & 1:
                cs[d] = LAND_COST
            elif cs[d] in (0x1f, 0xff, 1):
                cs[d] = BLOCKED
        c = g.cells[k]
        g.cells[k] = pm.Cell(bytes(cs), c.boundaries, c.uniform)
    pf_gen.compact(area, P)
    stats['component cells'] = len(comp)
    stats['modified cells'] = len(mod)
    Lw = shapely.transform(Ls, lambda c: c / FIX)
    return m, Lw, dict(stats), dom, sea


# ---------------------------------------------------------------- poi.esf
def poi(path, pos, L, R, pass_group, sea_key):
    raw = open(path, 'rb').read()
    p = cm.read_poi(esf.loads(raw))
    assert esf.dumps(cm.write_poi(p)) == raw, 'poi round-trip'
    nid = max(n.id for n in p.nodes) + 1
    coast = lambda q: f32(R.exterior.distance(Point(q)))
    node = lambda i, kind, q, dist: cm.PoiNode(i, kind, True, int(round(q[0] * FIX)), int(round(q[1] * FIX)), KEY, pass_group,
                                              KEY, pass_group, f32(dist), [(sea_key, coast(q))], coast(q), [], [], 0, False)
    new = [node(nid, 4, pos, 0.0)]
    x0, y0, x1, y1 = L.bounds
    grid = [(x, y) for x in np.arange(math.ceil(x0 / 8) * 8, x1, 8.0) for y in np.arange(math.ceil(y0 / 8) * 8, y1, 8.0)
            if L.contains(Point(x, y)) and L.exterior.distance(Point(x, y)) > 2.0 and Point(x, y).distance(Point(pos)) > 5.0]
    grid.sort(key=lambda q: Point(q).distance(Point(pos)))
    for q in grid[:10]:
        new.append(node(nid + len(new), 2, q, Point(q).distance(Point(pos))))
    p.nodes += new
    return esf.dumps(cm.write_poi(p)), new


# ---------------------------------------------------------------- startpos
def all_ints(root):
    out = set()
    def walk(r):
        for kids in (r.items if r.items is not None else [r.children]):
            for v in kids:
                if isinstance(v, Rec):
                    walk(v)
                elif v.tag in (0x04, 0x08):
                    out.add(v.value & 0xFFFFFFFF)
                elif v.tag in (0x44, 0x48) and v.value:
                    out.update(struct.unpack(f'<{len(v.value) // 4}I', v.value))
    walk(root)
    return out


def handles(used, n, start=900000000):
    out, h = [], start
    while len(out) < n:
        if h not in used:
            out.append(h)
        h += 4
    return out


def walk_vals(r, fn):
    """fn(kids, index, val) for every Val under r (kids is the list holding it)."""
    for kids in (r.items if r.items is not None else [r.children]):
        for j, v in enumerate(kids):
            if isinstance(v, Rec):
                walk_vals(v, fn)
            else:
                fn(kids, j, v)


def recs(r, name):
    for kids in (r.items if r.items is not None else [r.children]):
        for v in kids:
            if isinstance(v, Rec):
                if v.name == name:
                    yield v
                yield from recs(v, name)


def shift_los(los, D):
    """LINE_OF_SIGHT (bool True, xy min, xy max, QUAD_TREE_BIT_ARRAY) moved by D (multiples of 10 u = 8 cells)."""
    los.children[1] = Val(0x0c, (los.children[1].value[0] + D[0], los.children[1].value[1] + D[1]))
    los.children[2] = Val(0x0c, (los.children[2].value[0] + D[0], los.children[2].value[1] + D[1]))
    q = los.find('QUAD_TREE_BIT_ARRAY')
    Wd, H, b = cm.qtba_decode(q)
    bx, by = int(D[0]) // 10, int(D[1]) // 10
    new = cm.qtba_encode(Wd, H, {(x + bx, y + by): v for (x, y), v in b.items()}, q.children[3].version)
    q.children[:] = new.children


def startpos(sp, D, pos, variant, P_S):
    """Clone the TPL REGION -> KEY. -> info dict."""
    used = P_S['used'] if 'used' in P_S else all_ints(sp.root)     # P_S['used']: the caller's running set (startpos_regions)
    ra = cm.first_rec(sp.root, 'REGIONS_ARRAY')
    tpl = next(it[0] for it in ra.items if it[0].children[0].value == TPL)
    rebels = {it[0].children[24].value for it in ra.items}
    assert REBEL_KEY in rebels, sorted(rebels)
    reg = clone(tpl)
    # slots: keep KEEP_SLOTS only (settlement_1_slot in REGION_SLOT_ARRAY, road + fortification are own records)
    sm = reg.find('REGION_SLOT_MANAGER')
    arr = sm.find('REGION_SLOT_ARRAY')
    slot_key = lambda rs: next(v.value for v in rs.children if isinstance(v, Val) and v.tag == 0x0e)
    arr.items = [it for it in arr.items if slot_key(it[0]).endswith(':settlement_1_slot:1')]
    assert len(arr.items) == 1
    slots = [arr.items[0][0], sm.find('ROAD_SLOT').find('REGION_SLOT'), sm.find('FORTIFICATION_SLOT').find('REGION_SLOT')]
    old = dict(region=reg.children[4].value, settlement=reg.find('SETTLEMENT').children[0].children[1].value,
               rrm=reg.find('REGION_RECRUITMENT_MANAGER').children[2].value,
               army=reg.find('SETTLEMENT').children[0].children[12].value)
    for s in slots:
        old[slot_key(s).split(':')[3]] = s.children[2].value
    new = dict(zip(('region', 'settlement', 'rrm', 'settlement_1_slot', 'settlement_road', 'settlement_fortification'),
                   handles(used, 6)))
    if 'used' in P_S and os.environ.get('NTW_CHECK_FIRST'):
        assert handles(all_ints(sp.root), 6) == list(new.values()), 'running used set drifted'
    hmap = {old[k]: new[k] for k in new}
    hmap[old['army']] = 0                                 # no garrison army (as eur_finland)
    suffix = reg.find('SETTLEMENT').find('CAMPAIGN_LOCALISATION').children[0].value.rsplit(TPL_TOWN, 1)[1]
    cnt = collections.Counter()

    def fix(kids, j, v):
        if v.tag in (0x04, 0x08) and v.value in hmap:
            kids[j] = Val(v.tag, hmap[v.value]); cnt['handles'] += 1
        elif v.tag == 0x0e:
            s = v.value.replace(f'{TPL}:{TPL_TOWN}', f'{KEY}:{TOWN}')
            if s.startswith('start_pos_settlements_onscreen_name_'):
                s = s[:-len(suffix)] + str(LOC_SUFFIX)
            s = KEY if s == TPL else s.replace('regions_onscreen_' + TPL, 'regions_onscreen_' + KEY)
            if s != v.value:
                kids[j] = Val(0x0e, s); cnt['strings'] += 1
    walk_vals(reg, fix)
    reg.children[24], reg.children[25] = Val(0x0e, REBEL_KEY), Val(0x0e, REBEL_NAME)
    # positions: i32 fixed pairs near the template settlement (3 slots + SETTLEMENT residence)
    t = reg.find('SETTLEMENT').children[0]
    px, py = t.children[10].value / FIX, t.children[11].value / FIX
    dfx, dfy = int(D[0]) * FIX, int(D[1]) * FIX
    npos = 0
    for s in slots + [t]:
        k = next(j for j in range(len(s.children) - 1) if all(isinstance(s.children[j + d], Val) and s.children[j + d].tag == 0x04
                                                             for d in (0, 1))
                 and abs(s.children[j].value / FIX - px) < 30 and abs(s.children[j + 1].value / FIX - py) < 30)
        s.children[k] = Val(0x04, s.children[k].value + dfx)
        s.children[k + 1] = Val(0x04, s.children[k + 1].value + dfy)
        npos += 1
    assert abs(t.children[10].value / FIX - pos[0]) < 1e-4 and abs(t.children[11].value / FIX - pos[1]) < 1e-4
    nlos = 0
    for los in recs(reg, 'LINE_OF_SIGHT'):
        if los.children[0].value:
            shift_los(los, D); nlos += 1
    assert nlos == 2 and npos == 4, (nlos, npos)
    leftover = []
    walk_vals(reg, lambda kids, j, v: leftover.append(v.value) if v.tag == 0x0e and ('ireland' in v.value or 'dublin' in v.value) else None)
    assert not leftover, leftover
    assert reg.children[20].value == tpl.children[20].value and reg.children[22].value == GOV
    ra.items.append([reg])
    # ownership, governorship
    own = cm.first_rec(sp.root, 'REGION_OWNERSHIPS_BY_THEATRE').items[0][1]
    own.items.append([Val(0x0e, KEY), Val(0x0e, OWNER)])
    gov = cm.first_rec(sp.root, 'GOVERNORSHIP', GOV, lambda g: g.children[1].value == GOV)
    assert gov.children[2].tag == 0x48 and gov.children[3].value == reg.children[20].value
    gov.children[2] = Val(0x48, gov.children[2].value + struct.pack('<I', new['region']))
    # per-path-domain arrays: insert at the new domain id (= old singleton count)
    pg = cm.first_rec(sp.root, 'PATHFINDING_GRID').items[0]
    dom = P_S['dom']
    b8 = pg[8].value
    assert pg[8].tag == 0x41 and pg[11].tag == 0x4a and len(b8) == len(pg[11].value) // 4 == P_S['domains_before']
    f11 = list(struct.unpack(f'<{len(b8)}f', pg[11].value))
    major = collections.Counter(f11).most_common(1)[0][0]
    pg[8] = Val(0x41, b8[:dom] + b'\x01' + b8[dom:])
    pg[11] = Val(0x4a, struct.pack(f'<{len(f11) + 1}f', *(f11[:dom] + [major] + f11[dom:])))
    if 'used' in P_S:
        used.update(new.values())
    info = dict(handles=new, template_handles={k: v for k, v in old.items()}, handle_fixes=cnt['handles'],
                string_fixes=cnt['strings'], domain_array_value=major, rebel=REBEL_KEY)
    if variant == 'trade':
        info['trade'] = trade_startpos(sp, P_S['P'], P_S['S'])
    return info


def trade_startpos(sp, P, S_):
    """Register KEY as settlement index P+S_; every trade-node index (>= P+S_) +1."""
    tm = cm.first_rec(sp.root, 'CAMPAIGN_TRADE_MANAGER')
    si = tm.find('SETTLEMENT_INDICES')
    assert len(si.items) == S_ and sorted(it[1].value for it in si.items) == list(range(P, P + S_))
    si.items.append([Val(0x0e, KEY), Val(0x08, P + S_)])
    n0 = P + S_
    cnt = collections.Counter()

    def bump(v, what):
        if n0 <= v.value != 0xFFFFFFFF:
            cnt[what] += 1
            return Val(0x08, v.value + 1)
        return v
    for it in tm.find('TRADE_NODES').items:
        it[1] = bump(it[1], 'TRADE_NODES')
    for it in tm.find('TRADE_ROUTES').items:
        it[0], it[1] = bump(it[0], 'TRADE_ROUTES'), bump(it[1], 'TRADE_ROUTES')
    for fac in tm.find('DOMESTIC_TRADE_ROUTES').items:
        for r in fac[1].items:
            c = r[0].children
            for j in (6, 7):
                assert c[j].tag == 0x08
                c[j] = bump(c[j], 'DOMESTIC_TRADE_ROUTE')
    return dict(cnt)


def trade_esf():
    e = esf.load(SRC + '/trade_routes.esf')
    e.root.find('SETTLEMENTS').items.append([Val(0x0e, KEY)])
    return esf.dumps(e)


# ---------------------------------------------------------------- db + loc
def db_tables():
    with tempfile.TemporaryDirectory() as t:
        for pat in ('db/regions_tables/regions', 'db/campaign_map_settlements_tables/campaign_map_settlements'):
            assert packtool.extract(geo.GAME + '/data.pack', t, pat) == 1, pat
        reg = dbtable.load(t + '/db/regions_tables/regions')
        st = dbtable.load(t + '/db/campaign_map_settlements_tables/campaign_map_settlements')
    from PIL import Image
    pal = Image.open(M1 + '/europe_lookup.tga').getpalette()
    assert RGB not in {tuple(r[2:5]) for r in reg['rows']} and RGB not in set(zip(pal[0::3], pal[1::3], pal[2::3]))
    assert KEY not in {r[0] for r in reg['rows']}
    reg['rows'].append([KEY, 'cont_europe', *RGB, NAME])
    st['rows'].append([f'settlement:{KEY}:{TOWN}', KEY, TOWN_NAME, 1, 'settlement'])
    return {'db/regions_tables/regions': dbtable.build(reg),
            'db/campaign_map_settlements_tables/campaign_map_settlements': dbtable.build(st)}


def loc_rows():
    return [('regions_onscreen_' + KEY, NAME, 0), ('regions_battle_name_' + KEY, NAME, 0),
            (f'start_pos_settlements_onscreen_name_settlement:{KEY}:{TOWN}{LOC_SUFFIX}', TOWN_NAME, 0),
            (f'start_pos_regions_rebel_faction_name_{KEY}mp_eur_napoleon', REBEL_NAME, 0)]


# ---------------------------------------------------------------- build
def build(variant):
    out = out_dir(variant)
    if os.path.exists(out):
        shutil.rmtree(out)
    ov = os.path.join(out, 'overlay')
    os.makedirs(os.path.join(ov, MAPDIR))
    src = inputs()
    print('inputs:', src['why'])
    e = esf.load(src['regions'])
    rd = e.root.find('region_data')
    items = rd.find('regions').items
    names = [it[0].value for it in items]
    assert KEY not in names
    wi, ai, R, sea_ri = find_island(rd)
    sea_key = names[sea_ri]
    f = rm.area_fields(rm.sub(items[wi], 'areas').items[ai])
    # pass_group: the island keeps its own id (regions_world.relabel rule: a component keeps its old id), so ids stay
    # dense 0..max; spec 10 says append max+1 -> PASS_GROUP_APPEND. Which one the game prefers is open question 7.
    allpg = [rm.area_fields(ar)['pass_group'] for _, _, _, ar in rm.iter_areas(rd)]
    pass_group = max(allpg) + 1 if PASS_GROUP_APPEND else f['pass_group']
    new_index = len(items)
    # pathfinding first: the settlement must sit on its land
    m, L, pstats, dom, sea = pathfinding(R, new_index)
    tpl = items[names.index(TPL)]
    tpos = rm.sub(tpl, 'settlement_and_slots').children[0].value
    # template offset D: multiples of 10 u (LOS bit-array blocks move whole); the most interior such position on land
    x0, y0, x1, y1 = L.bounds
    cands = [(dx, dy) for dx in range(math.floor((x0 - tpos[0]) / 10) * 10, math.ceil((x1 - tpos[0]) / 10) * 10 + 1, 10)
             for dy in range(math.floor((y0 - tpos[1]) / 10) * 10, math.ceil((y1 - tpos[1]) / 10) * 10 + 1, 10)]
    D = max(cands, key=lambda d: L.boundary.distance(Point(tpos[0] + d[0], tpos[1] + d[1]))
            if L.contains(Point(tpos[0] + d[0], tpos[1] + d[1])) else -1)
    D = tuple(map(float, D))
    pos = (f32(tpos[0] + D[0]), f32(tpos[1] + D[1]))
    assert L.contains(Point(pos)) and L.exterior.distance(Point(pos)) > 3.0, pos
    ri = regions_finish(e, wi, ai, pos, D, pass_group)
    assert ri == new_index
    open(os.path.join(ov, MAPDIR, 'regions.esf'), 'wb').write(esf.dumps(e))
    open(os.path.join(ov, MAPDIR, 'pathfinding.esf'), 'wb').write(m.encode())
    pb, nodes = poi(src['poi'], pos, L, R, pass_group, sea_key)
    open(os.path.join(ov, MAPDIR, 'poi.esf'), 'wb').write(pb)
    import world_build
    open(os.path.join(ov, MAPDIR, 'sea_grids.esf'), 'wb').write(world_build.sea_grid())
    tr = cm.read_trade_routes(esf.load(SRC + '/trade_routes.esf'))
    if variant == 'trade':
        open(os.path.join(ov, MAPDIR, 'trade_routes.esf'), 'wb').write(trade_esf())
    else:
        shutil.copy(SRC + '/trade_routes.esf', os.path.join(ov, MAPDIR, 'trade_routes.esf'))
    for rel, data in db_tables().items():
        os.makedirs(os.path.dirname(os.path.join(ov, rel)), exist_ok=True)
        open(os.path.join(ov, rel), 'wb').write(data)
    open(os.path.join(out, 'loc_rows.tsv'), 'w', encoding='utf-8', newline='').write(loc.to_tsv(loc_rows()))
    sp = esf.load(W + '/startpos_plain.esf')
    sinfo = startpos(sp, D, pos, variant, dict(dom=dom, domains_before=len(m.areas[0].grid.path_domains()) - 1,
                                                 P=len(tr.ports), S=len(tr.settlements)))
    open(os.path.join(out, 'startpos.esf'), 'wb').write(esf.dumps(sp))
    lon, lat = proj.to_lonlat(*np.array(R.exterior.coords).T)
    slon, slat = proj.to_lonlat(*pos)
    info = dict(variant=variant, inputs=src, region=KEY, region_index=new_index, carved_from=f'eur_map_west area #{ai}',
                carved_area_fields={k: v for k, v in f.items() if k not in ('bmin', 'bmax')}, pass_group=pass_group,
                sea_neighbour=sea_key, world_bounds=[round(v, 3) for v in R.bounds],
                lonlat_bounds=[round(float(lon.min()), 3), round(float(lat.min()), 3), round(float(lon.max()), 3), round(float(lat.max()), 3)],
                area_u2=round(R.area, 1), pf_land_area_u2=round(L.area, 1), settlement=pos,
                settlement_lonlat=(round(float(slon), 3), round(float(slat), 3)), template_offset=D,
                path_domain=dom, sea_domain=sea, pathfinding=pstats, poi_nodes=[(n.id, n.kind, n.wx, n.wy) for n in nodes],
                startpos=sinfo, loc_suffix=LOC_SUFFIX, rgb=RGB)
    json.dump(info, open(os.path.join(out, 'build_info.json'), 'w'), indent=1)
    print(json.dumps(info, indent=1))



# ---------------------------------------------------------------- check
def check(variant):
    out = out_dir(variant)
    ov = os.path.join(out, 'overlay', MAPDIR)
    info = json.load(open(os.path.join(out, 'build_info.json')))
    ok = True

    def rep(name, cond, detail=''):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f': {detail}' if detail != '' else ''))

    print(f'== check {os.path.relpath(out, ROOT)}')
    # pathfinding
    area = pm.PathfindingModel.load(ov + '/pathfinding.esf').areas[0]
    g = area.grid
    pm.rebuild_spatial_grid(area)
    rep('pathfinding rebuild_spatial_grid (CCW, in-cell, tile area, contact masks)', True)
    bad, ex = pf_check.check(area)
    rep('pf_check unwelded sides (sea = path_domains().index(()))', not bad, f'{sum(bad.values())} {dict(bad)} {ex[:2]}')
    doms = g.path_domains()
    ri = info['region_index']
    rep('path domains', doms[info['path_domain']] == (ri,) and doms.index(()) == info['sea_domain'] == info['path_domain'] + 1,
        f'{len(doms)} domains, domain {info["path_domain"]} = {doms[info["path_domain"]]}, sea = {doms.index(())}')
    rep('region counts', g.passable_region_count == g.listed_region_count == len(g.region_indices) == 73,
        (g.passable_region_count, g.listed_region_count, len(g.region_indices)))
    P = area.polygons()
    x, y = info['settlement']
    k = cell_of(g, x, y)
    hit = [t for t, q in probe_g3.cell_polys(area, P, k) if Polygon(q).covers(Point(x * FIX, y * FIX))]
    rep('settlement on passable land in pathfinding', hit and all(t.kind == 0 and t.path_id == info['path_domain'] for t in hit), hit)
    dom = info['path_domain']
    lc = [i for i, c in enumerate(g.cells) if land_mask(c, dom) or (c.uniform is None and any(b.trait.path_id == dom for b in c.boundaries))]
    C = g.columns
    asym = sum(1 for i in lc for d, (dx, dy) in enumerate(DIRS)
               if (g.cells[i].costs8[d] == LAND_COST) != (g.cells[(i // C + dy) * C + i % C + dx].costs8[OPP[d]] == LAND_COST)
               and (land_mask(g.cells[i], dom) >> d & 1))
    rep('land cost symmetry', asym == 0, f'{len(lc)} cells carry domain {dom}, {asym} asymmetric land steps')
    # regions.esf
    import regions_world
    out_r, spots = regions_world.check(ov + '/regions.esf')
    hard = [k2 for k2 in ('invalid_polygons', 'bad_ring_orientation', 'untwinned_edges', 'bad_face_blobs', 'unused_vertices',
                          'duplicate_vertices', 'connectivity_asymmetric') if out_r[k2]]
    hard += [k2 for k2 in ('connectivity_rebuild_identical', 'id_partitions_ok', 'region_keys_ok', 'quadtree_header_formula',
                           'groundtypes_area_ok', 'theatre_rasters_ok') if not out_r[k2]]
    hard += [k2 for k2 in ('quadtree_mismatch', 'groundtypes_quadtree_mismatch', 'water_ge1_not_sea', 'water_ge1_query_not_sea')
             if not out_r[k2].startswith('0/')]
    hard += ['vanilla_areas_changed'] * bool(out_r['vanilla_areas_changed']) + [s[0] for s in spots if s[-1] != 'ok']
    rep('regions_world.check', not hard, f"failed {hard}; regions {out_r['regions']} areas {out_r['areas']} quadtree {out_r['quadtree_mismatch']}")
    e = esf.load(ov + '/regions.esf')
    rd = e.root.find('region_data')
    items = rd.find('regions').items
    names = [it[0].value for it in items]
    rep('region index', names.index(KEY) == ri == len(items) - 1 and len(items) == 102, (names.index(KEY), len(items)))
    it = items[ri]
    ars = rm.sub(it, 'areas').items
    fl = rm.area_fields(ars[0])
    pgs = [rm.area_fields(ar)['pass_group'] for _, _, _, ar in rm.iter_areas(rd)]
    rep('new area: 1 passable land area, own pass_group', it[1].value == 'land' and len(ars) == 1 and fl['passable']
        and pgs.count(fl['pass_group']) == 1 and fl['pass_group'] == info['pass_group'], (fl['pass_group'], fl['nonwalk_group'], fl['landmass']))
    Rp = rm.area_polygons(rd)[ri << 16]
    ss = rm.sub(it, 'settlement_and_slots')
    inside = [Rp.contains(Point(ss.children[0].value))]
    inside += [Rp.contains(Polygon(rm.nparr(ss.children[1]))) if ss.children[1].value else True]
    for s in ss.find('slot_descriptions').items:
        inside.append(Rp.contains(Point(s[3].value)))
        inside += [Rp.contains(shapely.MultiPoint(rm.nparr(s[j]))) for j in (7, 9) if s[j].value]
    rep('settlement, footprint and slot geometry inside the region polygon', all(inside), f'{sum(inside)}/{len(inside)}')
    th = {k2[0].value for k2 in e.root.find('theatres_and_region_keys').items[0][0].find('region_keys').items}
    settled = {it2[0].value for it2 in items if rm.sub(it2, 'settlement_and_slots') is not None}
    # startpos
    sp = esf.load(os.path.join(out, 'startpos.esf'))
    ra = next(cm._iter_recs(sp.root, 'REGIONS_ARRAY'))
    spk = [x[0].children[0].value for x in ra.items]
    own = [x[0].value for x in next(cm._iter_recs(sp.root, 'REGION_OWNERSHIPS_BY_THEATRE')).items[0][1].items]
    pfk = {names[i] for i in g.region_indices}
    rep('region lists agree (regions.esf settlements = theatre keys = pathfinding region_indices = startpos REGIONS_ARRAY = '
        'REGION_OWNERSHIPS)', settled == th == pfk == set(spk) == set(own) and len(spk) == len(own) == 73 and KEY in th,
        f'{len(settled)} {len(th)} {len(pfk)} {len(spk)} {len(own)}')
    pg = next(cm._iter_recs(sp.root, 'PATHFINDING_GRID')).items[0]
    b8, f11 = pg[8].value, struct.unpack(f'<{len(pg[11].value) // 4}f', pg[11].value)
    rep('PATHFINDING_GRID leaves 8/11 sized to the domain count, new entry at the new domain', len(b8) == len(f11) == len(doms)
        and b8[dom] == 1, (len(b8), len(f11), len(doms), b8[dom], f11[dom]))
    reg = ra.items[spk.index(KEY)][0]
    gov = next(x for x in cm._iter_recs(sp.root, 'GOVERNORSHIP') if x.children[1].value == GOV)
    h = info['startpos']['handles']
    owner = {x[0].value: x[1].value for x in next(cm._iter_recs(sp.root, 'REGION_OWNERSHIPS_BY_THEATRE')).items[0][1].items}
    rep('owner + governorship', reg.children[22].value == GOV and reg.children[20].value == gov.children[3].value
        and h['region'] in gov.children[2].array() and owner[KEY] == OWNER, (owner[KEY], reg.children[20].value, gov.children[2].array()))
    counts = collections.Counter()
    walk_vals(sp.root, lambda kids, j, v: counts.update([v.value]) if v.tag in (0x04, 0x08) and v.value in h.values() else
              counts.update(x for x in struct.unpack(f'<{len(v.value) // 4}I', v.value) if x in h.values()) if v.tag in (0x44, 0x48) and v.value else None)
    base = all_ints(esf.load(W + '/startpos_plain.esf').root)
    want = dict(region=2, settlement=2, rrm=1, settlement_1_slot=2, settlement_road=2, settlement_fortification=2)
    rep('new handles unique (absent from the base startpos, each used only by the new records)',
        len(set(h.values())) == len(h) and not set(h.values()) & base and all(counts[h[k2]] == n for k2, n in want.items()),
        {k2: counts[v] for k2, v in h.items()})
    sx, sy = reg.find('SETTLEMENT').children[0].children[10].value / FIX, reg.find('SETTLEMENT').children[0].children[11].value / FIX
    rep('startpos settlement position = regions.esf settlement', abs(sx - x) < 1e-4 and abs(sy - y) < 1e-4 and Rp.contains(Point(sx, sy)),
        (sx, sy))
    # trade
    tr = cm.read_trade_routes(esf.load(ov + '/trade_routes.esf'))
    tm = next(cm._iter_recs(sp.root, 'CAMPAIGN_TRADE_MANAGER'))
    Pn, Sn = len(tr.ports), len(tr.settlements)
    pi = {x[0].value: x[1].value for x in tm.find('PORT_INDICES').items}
    si = {x[0].value: x[1].value for x in tm.find('SETTLEMENT_INDICES').items}
    nodes = sorted(x[1].value for x in tm.find('TRADE_NODES').items)
    routes = [(x[0].value, x[1].value, tuple(x[2].array()), x[3].value) for x in tm.find('TRADE_ROUTES').items]
    esr = {(a, b, tuple(ids), ln) for a, b, ids, ln in tr.routes}
    node_of = {int(n.rsplit('_', 1)[1]): rs for n, rs in tr.node_routes}
    nr = {(a, Pn + Sn + k2, tuple(ids), ln) for k2, rs in node_of.items() for a, ids, ln in rs}
    dom_nodes = [r[0].children[6].value for fac in tm.find('DOMESTIC_TRADE_ROUTES').items for r in fac[1].items]
    rep('trade indices consistent (trade_routes.esf <-> startpos)',
        pi == {p: i for i, p in enumerate(tr.ports)} and si == {s: Pn + i for i, s in enumerate(tr.settlements)}
        and nodes == list(range(Pn + Sn, Pn + Sn + len(tr.node_routes))) and set(routes) == esr | nr and len(routes) == len(esr) + len(nr)
        and all(Pn + Sn <= v < Pn + Sn + len(nodes) for v in dom_nodes),
        f'P={Pn} S={Sn} nodes {nodes[0]}..{nodes[-1]} routes {len(routes)}; {KEY} settlement index {si.get(KEY)}')
    rep(f'variant {variant}: {KEY} ' + ('registered' if variant == 'trade' else 'absent') + ' in trade data',
        (KEY in tr.settlements and KEY in si) if variant == 'trade' else (KEY not in tr.settlements and KEY not in si))
    # poi
    p = cm.read_poi(esf.load(ov + '/poi.esf'))
    ids = [n.id for n in p.nodes]
    mine = [n for n in p.nodes if n.region == KEY]
    rep('poi: ids unique, kind-4 at the settlement, nodes inside the region on pathfinding land',
        len(set(ids)) == len(ids) and sum(n.kind == 4 for n in mine) == 1
        and next(n for n in mine if n.kind == 4).x == int(round(x * FIX)) and all(Rp.contains(Point(n.wx, n.wy)) for n in mine)
        and all(n.area == info['pass_group'] == n.area2 for n in mine)
        and all(any(t.kind == 0 and t.path_id == dom and Polygon(q).covers(Point(n.x, n.y))
                    for t, q in probe_g3.cell_polys(area, P, cell_of(g, n.wx, n.wy))) for n in mine),
        f'{len(mine)} nodes ({collections.Counter(n.kind for n in mine)})')
    # db + loc
    reg_t = dbtable.load(os.path.join(out, 'overlay/db/regions_tables/regions'))
    st_t = dbtable.load(os.path.join(out, 'overlay/db/campaign_map_settlements_tables/campaign_map_settlements'))
    rgbs = [tuple(r[2:5]) for r in reg_t['rows']]
    rows = loc.from_tsv(open(os.path.join(out, 'loc_rows.tsv'), encoding='utf-8').read())
    sloc = reg.find('SETTLEMENT').find('CAMPAIGN_LOCALISATION').children[0].value
    rep('db rows + loc keys', [r for r in reg_t['rows'] if r[0] == KEY] == [[KEY, 'cont_europe', *RGB, NAME]] and len(set(rgbs)) == len(rgbs)
        and [r for r in st_t['rows'] if r[1] == KEY] == [[f'settlement:{KEY}:{TOWN}', KEY, TOWN_NAME, 1, 'settlement']]
        and sloc in {r[0] for r in rows} and reg.children[41].children[0].value in {r[0] for r in rows},
        f'{len(reg_t["rows"])} regions rows, {len(st_t["rows"])} settlement rows, loc {len(rows)} rows')
    print('  PASS' if ok else '  FAIL')
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('cmd', nargs='?', default='build', choices=('build', 'check'))
    ap.add_argument('--variant', default='trade', choices=('trade', 'notrade'))
    a = ap.parse_args()
    if a.cmd == 'build':
        build(a.variant)
    else:
        sys.exit(0 if check(a.variant) else 1)


if __name__ == '__main__':
    main()
