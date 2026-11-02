"""Ports for a world_regions build: a PORT slot for every new region with a regions.json `port` (world_regions stage
'p' calls add_ports on its output; the CLI does the same on a copy of an existing build).

Per port (vanilla recipes, research in the New York probe, 7daede4):
  regions.esf  eur_ireland:waterford's port slot description, rotated / moved (u16 angle: footprints turn clockwise as
               it grows), appended to the region's slot_descriptions.
  pathfinding  the footprint's land half carved as kind-7 (slot) land of the region's domain, the sea half as kind-7
               sea (vanilla: every slot footprint is kind 7; 4/5 = land bridge, 6 = road); middle20 / contact masks
               re-derived round it, costs8 where land-land / sea-sea contact changed.  Domains unchanged.
  startpos     REGION_SLOT owned like the region's settlement: eur_england:portsmouth's (pNavy1_shipyard, built for the
               owner) in a generated faction's capital region, else waterford's (empty port), fresh handles.
  db / loc     campaign_map_towns_and_ports row + campaign_map_towns_and_ports_onscreen_name_<slot>.
  trade        the ports take trade indices P..P+n-1 (ports first): every settlement / trade-node index +n in
               trade_routes.esf and the startpos (indices, TRADE_ROUTES, domestic / international route hops); per port a
               spline-less route to its settlement and to each trade node (target = port index, node = P+n+S+k for
               trade_node_k).  No port-to-port sea routes.
  CAI          CAI_REGION_SLOT (waterford's, blank BDI header) with CAI_SITUATED on the building (region, its area's
               pass group) and on the dock (sea region, its pass group) + CAI_BUILDING_SLOT kind 3 + the CAI_REGION slot
               list; sea_grids.esf port list of the dock's cell.  Not added: the beliefs naming a slot (CAI_PORT_ANALYSIS
               etc.), as for every generated region.  No vanilla port has its own poi.esf node: poi.esf unchanged.
A port that cannot be placed (no footprint fit within SEARCH_R / RETRY_R u of the regions.json point, dock not
reachable by sea, > 4 passable polygons of a class in a carved cell) is deferred: build_info 'ports' 'deferred'.

  .venv/bin/python tools/port_probe.py build [--src work/world/w7_s_v] [--out DIR] [--regions k1,k2]   (then check)
  .venv/bin/python tools/port_probe.py check [--src ...] [--out DIR]
"""
import argparse, collections, copy, json, math, os, shutil, struct, sys, tempfile, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, shapely
from shapely.geometry import Point, Polygon, box
import esf, geo, proj, dbtable, packtool, loc
import campaign_misc as cm, regions_model as rm, pathfinding_model as pm, probe_g3, pf_gen, pf_check
import land_probe as lp, world_zones as wz
from esf import Rec, Val

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data/world1805')
MAPDIR = 'campaign_maps/nap_world'
VAN = geo.GAME + '/campaign_maps/nap_europe'
FIX = 1 << 20
NONE = 0xFFFFFFFF
TPL_PORT = ('eur_ireland', 'port:eur_ireland:waterford')     # regions.esf footprint template
TPL_YARD = 'port:eur_england:portsmouth'                      # startpos REGION_SLOT with pNavy1_shipyard
TPL_EMPTY = 'port:eur_ireland:waterford'                      # startpos REGION_SLOT, no building; CAI template
SEARCH_R, RETRY_R = 15.0, 40.0                                # u round regions.json's port point (0.25 / 0.5 u steps)
TOWNS_T = 'db/campaign_map_towns_and_ports_tables/campaign_map_towns_and_ports'
LAND_KINDS, SEA_COST = (0, 7), pf_gen.SEA_COST
MAX_POLYS = 4                                                 # middle20 links the first 4 polygons of a class


# ---------------------------------------------------------------- footprint
def template():
    """Waterford's port slot: building xy, dock xy, angle, footprints (land, sea, union) in world units."""
    e = esf.load(VAN + '/regions.esf')
    it = next(i for i in e.root.find('region_data').find('regions').items if i[0].value == TPL_PORT[0])
    s = next(s for s in rm.sub(it, 'settlement_and_slots').find('slot_descriptions').items if s[0].value == TPL_PORT[1])
    x, h, y = s[2].value
    return dict(item=s, bld=np.array([x, y]), h=h, dock=np.array(s[3].value), angle=s[4].value,
                fp=[rm.nparr(s[j]).reshape(-1, 2).astype(np.float64) for j in (7, 8, 9)])


def rotated(T, angle):
    """The template's dock / footprints about its own building xy, turned to angle (u16): vanilla footprints turn
    clockwise as the angle grows (Waterford -> Bristol / Portsmouth / Cadiz exact to 1e-3)."""
    d = -(angle - T['angle']) / 65536 * 2 * math.pi
    R = np.array([[math.cos(d), -math.sin(d)], [math.sin(d), math.cos(d)]])
    f = lambda p: (np.asarray(p, np.float64) - T['bld']) @ R.T
    return f(T['dock']), [f(a) for a in T['fp']]


def placed(T, bld, angle):
    """Template moved to building xy bld and angle (u16)."""
    rd, rf = rotated(T, angle)
    b = np.asarray(bld, np.float64)
    return dict(bld=b, dock=rd + b, angle=int(angle) % 65536, fp=[a + b for a in rf])


def place(T, area, g, P, region_poly, sea_polys, dom, sea, target, reach, R, step, strict=True, banned=()):
    """Best (building, angle) within R of target: land half on the region's land domain / off-map only, sea half on
    sea / off-map only (kind-7 = another slot counts as neither), building on the region's land and in its regions.esf
    polygon, the land half inside that polygon, dock on sea in a regions.esf sea area and in a cell reachable by sea;
    score = land half on land + sea half on sea (u^2), ties to the nearest.  strict=False (a coast with no off-map band
    between land and sea, e.g. land cut from a vanilla filler next to vanilla sea): the land half may cover sea and the
    sea half land, the building may stand in the off-map band within 1.5 u of the region's land with >= 0.25 u^2 of
    the land half on it (the carve makes them kind-7 land / sea, as vanilla's footprints define the coast locally).  banned:
    cells the footprint must not touch.  -> (placement, (score, -dist)) or None."""
    tx, ty = target
    ks = cells_in(g, (tx - R - 3, ty - R - 3, tx + R + 3, ty + R + 3))
    land, sea_, other = [], [], []
    for k in ks:
        for t, q in probe_g3.cell_polys(area, P, k):
            if t.kind in (2, 3):
                continue
            p = Polygon([(a / FIX, b / FIX) for a, b in q])
            (other if t.kind == 7 else sea_ if t.path_id == sea else land if t.path_id == dom else other).append(p)
    if not land:
        return None
    L, S, O = (shapely.union_all(x) if x else Polygon() for x in (land, sea_, other))
    LB = L.boundary
    for z in (L, S, O, LB, region_poly, sea_polys):
        shapely.prepare(z)
    best = None
    gx_, gy_ = np.arange(tx - R, tx + R + 1e-9, step), np.arange(ty - R, ty + R + 1e-9, step)
    X, Y = np.repeat(gx_, len(gy_)), np.tile(gy_, len(gx_))             # the scan order: x outer, y inner
    pts = shapely.points(X, Y)
    ok = shapely.contains(region_poly, pts) & ((shapely.contains(L, pts) & shapely.dwithin(LB, pts, 2.0)) if strict
                                                else shapely.dwithin(L, pts, 1.5))
    angles = list(range(0, 65536, 65536 // 72))
    rots = [rotated(T, a) for a in angles]
    for i in np.flatnonzero(ok):
        gx, gy = X[i], Y[i]
        bb = np.asarray((gx, gy), np.float64)
        docks = np.array([r[0] for r in rots]) + bb
        dok = shapely.contains(S, shapely.points(docks)) & shapely.contains(sea_polys, shapely.points(docks))
        for j in np.flatnonzero(dok):
            a = angles[j]
            pl = dict(bld=bb, dock=docks[j], angle=int(a) % 65536, fp=[f + bb for f in rots[j][1]])
            f7, f8 = Polygon(pl['fp'][0]), Polygon(pl['fp'][1])
            d = Point(*pl['dock'])
            if (f7.intersects(O) or f8.intersects(O)
                    or (strict and (f7.intersects(S) or f8.intersects(L))) or not region_poly.contains(f7)
                    or cells_in(g, (d.x, d.y, d.x, d.y))[0] not in reach
                    or (not strict and f7.intersection(L).area < 0.25)):
                continue
            if banned:
                xy = np.vstack(pl['fp'][:2])
                if set(cells_in(g, (*xy.min(0), *xy.max(0)))) & banned:
                    continue
            key = (round(f7.intersection(L).area + f8.intersection(S).area, 2), -math.dist((gx, gy), target))
            if best is None or key > best[0]:
                best = (key, dict(pl, bld=bb.copy(), dock=pl['dock'].copy()))
    return None if best is None else (best[1], best[0])


# ---------------------------------------------------------------- pathfinding
def cells_in(g, bbox):
    x0, y0, x1, y1 = bbox
    ox, oy, S = g.origin_fixed[0] / FIX, g.origin_fixed[1] / FIX, g.cell_size_fixed / FIX
    c0, c1 = max(0, int((x0 - ox) // S)), min(g.columns - 1, int((x1 - ox) // S))
    r0, r1 = max(0, int((y0 - oy) // S)), min(g.rows - 1, int((y1 - oy) // S))
    return [r * g.columns + c for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]


def cell_box(g, k):
    (x0, y0), _, _, (x1, y1) = g.corners(k)
    return box(x0, y0, x1, y1)


def ring(g, ks, n):
    """ks + neighbours (n = 4 or 8)."""
    C, R = g.columns, g.rows
    d = ((-1, 0), (1, 0), (0, -1), (0, 1)) + (((-1, -1), (1, -1), (-1, 1), (1, 1)) if n == 8 else ())
    return sorted(set(ks) | {(k // C + dy) * C + k % C + dx for k in ks for dx, dy in d
                             if 0 <= k % C + dx < C and 0 <= k // C + dy < R})


def sea_reach(g):
    """Cells reachable over open costs8 steps from the Bay of Biscay (pf_gen.selfcheck's fleet rule)."""
    C = g.columns
    x, y = map(float, proj.to_world(-5, 46))
    start = cells_in(g, (x, y, x, y))[0]
    seen, todo = {start}, [start]
    while todo:
        k = todo.pop()
        r, col = divmod(k, C)
        cs = g.cells[k].costs8
        for d, (dx, dy) in enumerate(lp.DIRS):
            j = (r + dy) * C + col + dx
            if cs[d] not in (0x1f, 0xff, 1) and 0 <= col + dx < C and 0 <= r + dy < g.rows and j not in seen:
                seen.add(j); todo.append(j)
    return seen


def land_sea_masks(c, dom, sea):
    """contact masks (bit d = DIRS[d]) of the region's land (kinds 0 / 7) and of the sea."""
    ts = [c.uniform] if c.uniform else [b.trait for b in c.boundaries]
    lm = sm = 0
    for t in ts:
        m = 255 if c.uniform else t.contact_mask
        if t.kind in LAND_KINDS and t.path_id == dom:
            lm |= m
        elif t.kind not in (2, 3) and t.path_id == sea:
            sm |= m
    return lm, sm


def fixed_fp(f7, f8):
    F7, F8 = (Polygon(np.round(np.asarray(f) * FIX)) for f in (f7, f8))
    assert F7.is_valid and F8.is_valid and F7.intersection(F8).area < 1e3       # vanilla: the halves share an edge
    return F7, F8


def touched(g, F7, F8):
    x0, y0, x1, y1 = F7.union(F8).bounds
    return [k for k in cells_in(g, (x0 / FIX - 2, y0 / FIX - 2, x1 / FIX + 2, y1 / FIX + 2))
            if cell_box(g, k).intersects(F7) or cell_box(g, k).intersects(F8)]


def unwelded(area, P, ks):
    """sides of cells ks whose two cells split them differently (pf_check rule: vanilla is welded; unwelded sides
    OOM-crash the AI turn)."""
    g, s = area.grid, area.grid.cell_size_fixed
    C, R = g.columns, g.rows
    bad = []
    for i in ks:
        r, col = divmod(i, C)
        x0, y0 = g.corners(i)[0]
        for dx, dy, axis, v in ((1, 0, 0, x0 + s), (-1, 0, 0, x0), (0, 1, 1, y0 + s), (0, -1, 1, y0)):
            if 0 <= col + dx < C and 0 <= r + dy < R:
                j = (r + dy) * C + col + dx
                if pf_check.side_intervals(area, P, i, axis, v) != pf_check.side_intervals(area, P, j, axis, v):
                    bad.append(i)
    return bad


def class_counts(area, P, k, sea):
    """passable polygons of cell k per class (land, sea)."""
    ts = [t for t, _ in probe_g3.cell_polys(area, P, k) if t.kind not in (2, 3)]
    return sum(t.path_id != sea for t in ts), sum(t.path_id == sea for t in ts)


def carve(area, P, F7, F8, dom, sea, key):
    """Kind-7 land (dom) = F7, kind-7 sea = F8 in every cell they touch; the cell's other polygons keep their traits
    on what is left (faces of the noded network, merged per source polygon).  New polygons go into P from offset
    key on (pf_gen.compact renumbers).  -> (cells changed, cells relinked, stats, next key)."""
    g = area.grid
    ks = touched(g, F7, F8)
    verts = list(area.vertices_fixed)
    vid = {}
    for n, p in enumerate(verts):
        if n >= 4:
            vid.setdefault(p, n)
    stats = collections.Counter()

    def ids_of(k, p):
        p = shapely.simplify(p, 0)
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

    for k in ks:
        cb = cell_box(g, k)
        src = probe_g3.cell_polys(area, P, k)
        lines = [cb.boundary] + [Polygon(q).exterior for _, q in src]
        lines += [shapely.intersection(F.exterior, cb) for F in (F7, F8)]
        net = shapely.union_all([x for x in lines if not x.is_empty], grid_size=1.0)
        faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(net)))
        assert abs(sum(f.area for f in faces) - cb.area) < 1.0, ('faces must tile the cell', k)
        groups = collections.defaultdict(list)
        for f in faces:
            q = f.representative_point()
            if F7.covers(q):
                groups[('f7',)].append(f)
            elif F8.covers(q):
                groups[('f8',)].append(f)
            else:
                j = next(j for j, (_, qq) in enumerate(src) if Polygon(qq).covers(q))
                groups[('src', j)].append(f)
        bounds = []
        for gk, fs in sorted(groups.items(), key=lambda kv: (kv[0][0] != 'src', kv[0])):
            t = (src[gk[1]][0] if gk[0] == 'src' else pm.Trait(7, 0, 0, dom if gk == ('f7',) else sea))
            u = shapely.union_all(fs, grid_size=1.0)
            ps = [p for p in shapely.get_parts(u) if p.area > 0]
            if any(p.interiors for p in ps):
                ps = fs; stats['unmerged (hole)'] += 1
            for p in sorted(ps, key=lambda p: -p.area):
                P[key] = ids_of(k, p)
                bounds.append(pm.Boundary(t, key)); key += 1
                stats['f7 polys' if gk == ('f7',) else 'f8 polys' if gk == ('f8',) else 'other polys'] += 1
        g.cells[k] = pm.Cell(g.cells[k].costs8, bounds)
    area.vertices_fixed = tuple(verts)
    for k in ks:                                         # contact masks of every passable polygon in the changed cells
        for b in g.cells[k].boundaries:
            t = b.trait
            m = 0 if t.kind in (2, 3) else pm.contact_mask(area.points(k, P[b.polygon_offset]), g.corners(k))
            b.trait = pm.Trait(t.kind, t.middle20, m, t.path_id)
    near = ring(g, ks, 4)                                # middle20 links into the neighbours' polygon indices
    for k in near:
        c = g.cells[k]
        if c.uniform is not None:
            t = c.uniform
            if t.kind not in (2, 3):
                g.cells[k] = pm.Cell(c.costs8, uniform=pm.Trait(t.kind, probe_g3.middle20(area, P, k, area.points(k, (0, 2, 3, 1)), t),
                                                                t.contact_mask, t.path_id))
            continue
        for b in c.boundaries:
            t = b.trait
            if t.kind not in (2, 3):
                b.trait = pm.Trait(t.kind, probe_g3.middle20(area, P, k, area.points(k, P[b.polygon_offset]), t), t.contact_mask, t.path_id)
    return ks, near, dict(stats), key


def recost(g, ks, before, dom, sea):
    """costs8 of the changed cells and their 8 neighbours where the land-land / sea-sea contact changed: land both
    sides -> 0x1f, else sea both sides -> SEA_COST (world_regions / pf_gen rules); other steps unchanged."""
    C, R = g.columns, g.rows
    todo = ring(g, ks, 8)
    after = {k: land_sea_masks(g.cells[k], dom, sea) for k in todo}
    changed = 0
    for k in todo:
        r, col = divmod(k, C)
        cs = bytearray(g.cells[k].costs8)
        for d, (dx, dy) in enumerate(lp.DIRS):
            j = (r + dy) * C + col + dx
            if not (0 <= col + dx < C and 0 <= r + dy < R) or j not in after:
                continue
            o = lp.OPP[d]
            both = lambda M: ((M[k][0] >> d & 1) and (M[j][0] >> o & 1), (M[k][1] >> d & 1) and (M[j][1] >> o & 1))
            if both(after) == both(before):
                continue
            ln, sn = both(after)
            v = lp.LAND_COST if ln else SEA_COST if sn else cs[d]
            if v != cs[d]:
                cs[d] = v; changed += 1
        c = g.cells[k]
        g.cells[k] = pm.Cell(bytes(cs), c.boundaries, c.uniform)
    return changed


# ---------------------------------------------------------------- regions.esf
class Regions:
    """regions.esf lookups: region polygons, the sea union, settlements, the area (+ pass group) at a point."""
    def __init__(self, e):
        rd = e.root.find('region_data')
        self.e, self.items = e, rd.find('regions').items
        self.names, self.kinds = [it[0].value for it in self.items], [it[1].value for it in self.items]
        self.polys = rm.area_polygons(rd)
        self.seas = shapely.union_all([q for c, q in self.polys.items() if self.kinds[c >> 16] == 'sea'])
        shapely.prepare(self.seas)

    def region(self, key):
        ri = self.names.index(key)
        rp = shapely.union_all([q for c, q in self.polys.items() if c >> 16 == ri])
        shapely.prepare(rp)
        return rp, rm.sub(self.items[ri], 'settlement_and_slots').children[0].value

    def area_at(self, p, sea):
        """(region index, pass group) of the one land area of no matter which region (sea=False: must be given) /
        sea area covering p."""
        hit = [(c >> 16, c & 0xFFFF) for c, q in self.polys.items()
               if (self.kinds[c >> 16] == 'sea') == sea and q.covers(Point(*p))]
        if len(hit) != 1:
            return None
        ri, ai = hit[0]
        return ri, rm.area_fields(rm.sub(self.items[ri], 'areas').items[ai])['pass_group']

    def add_slot(self, key, slot, pl, T):
        """Waterford's slot description moved to pl, appended to the region's slot_descriptions."""
        it = self.items[self.names.index(key)]
        sd = rm.sub(it, 'settlement_and_slots').find('slot_descriptions')
        s = copy.deepcopy(T['item'])
        s[0] = Val(0x0e, slot)
        s[2] = Val(0x0d, (lp.f32(pl['bld'][0]), T['h'], lp.f32(pl['bld'][1])))
        s[3] = Val(0x0c, tuple(lp.f32(v) for v in pl['dock']))
        s[4] = Val(s[4].tag, pl['angle'])
        for j, a in zip((7, 8, 9), pl['fp']):
            s[j] = rm.mkarr(s[j].tag, a.astype(np.float32))
        sd.items.append(s)


# ---------------------------------------------------------------- startpos
def slot_key(rs):
    return next(v.value for v in rs.children if isinstance(v, Val) and v.tag == 0x0e)


def region_slots(sp, key):
    ra = cm.first_rec(sp.root, 'REGIONS_ARRAY')
    reg = next(it[0] for it in ra.items if it[0].children[0].value == key)
    return reg, reg.find('REGION_SLOT_MANAGER').find('REGION_SLOT_ARRAY')


def startpos_slot(sp, tpls, used, key, slot, pl, yard):
    """The port REGION_SLOT (Portsmouth's with its shipyard if yard, else Waterford's), owner = the region's settlement
    slot owner, the shipyard built for that faction / government, fresh slot handle + recruitment manager id."""
    reg, arr = region_slots(sp, key)
    mine = next(it[0] for it in arr.items if slot_key(it[0]).endswith(':settlement_1_slot:1'))
    owner = mine.find('SIEGEABLE_GARRISON_RESIDENCE').find('GARRISON_RESIDENCE').children[0].value
    b = mine.find('BUILDING_MANAGER').find('BUILDING')
    fac_, gov = (b.children[2].value, b.children[3].value) if b is not None else (None, None)
    rs = copy.deepcopy(tpls[TPL_YARD if yard else TPL_EMPTY])
    h, rrm = lp.handles(used, 2)
    used.update((h, rrm))
    sg = rs.find('SIEGEABLE_GARRISON_RESIDENCE')
    sg.find('GARRISON_RESIDENCE').children[0] = Val(0x08, owner)
    assert sg.children[1].value == rs.children[2].value and not sg.find('LINE_OF_SIGHT').children[0].value
    sg.children[1] = Val(0x08, h)
    rs.children[2] = Val(0x08, h)
    rs.children[3] = Val(0x0e, slot)
    rs.children[6], rs.children[7] = Val(0x04, round(pl['bld'][0] * FIX)), Val(0x04, round(pl['bld'][1] * FIX))
    bb = rs.find('BUILDING_MANAGER').find('BUILDING')
    assert (bb is not None) == yard
    if yard:
        assert bb.children[1].value == 'pNavy1_shipyard' and fac_
        bb.children[2], bb.children[3] = Val(0x0e, fac_), Val(0x0e, gov)
    rr = rs.find('REGION_RECRUITMENT_MANAGER')
    assert rr.children[2].tag == 0x04
    rr.children[2] = Val(0x04, rrm)
    arr.items.append([rs])
    return dict(handle=h, recruitment_manager=rrm, owner_handle=owner, startpos_building=['pNavy1_shipyard', fac_, gov] if yard else None)


# ---------------------------------------------------------------- db / loc
def db_rows(ov, rows):
    with tempfile.TemporaryDirectory() as t:
        assert packtool.extract(geo.GAME + '/data.pack', t, TOWNS_T) == 1
        tb = dbtable.load(os.path.join(t, TOWNS_T))
    assert not {r[0] for r in rows} & {r[0] for r in tb['rows']}
    tb['rows'] += rows
    os.makedirs(os.path.dirname(os.path.join(ov, TOWNS_T)), exist_ok=True)
    open(os.path.join(ov, TOWNS_T), 'wb').write(dbtable.build(tb))


def loc_add(out, rows):
    p = os.path.join(out, 'loc_rows.tsv')
    old = loc.from_tsv(open(p, encoding='utf-8').read())
    open(p, 'w', encoding='utf-8', newline='').write(loc.to_tsv(old + rows))


# ---------------------------------------------------------------- trade
def f32(v):
    return struct.unpack('<f', struct.pack('<f', v))[0]


def bump_hops(kids, n_at, P, n):
    """trade route hops (i32 handle, xy, u32 a, u32 b, bool) after the u32 hop count at kids[n_at]: index >= P -> +n."""
    cnt = 0
    for h in range(kids[n_at].value):
        at = n_at + 1 + 5 * h
        assert kids[at].tag == 0x04 and kids[at + 4].tag == 0x01
        for j in (at + 2, at + 3):
            v = kids[j]
            assert v.tag == 0x08
            if P <= v.value != NONE:
                kids[j] = Val(0x08, v.value + n); cnt += 1
    return cnt


def trade(ov, sp, ports):
    """ports [(slot, region key, dock xy, settlement xy)] -> trade indices P..P+n-1 (one renumbering pass)."""
    tp = os.path.join(ov, MAPDIR, 'trade_routes.esf')
    tr = cm.read_trade_routes(esf.load(tp))
    P, S, N, n = len(tr.ports), len(tr.settlements), len(tr.node_routes), len(ports)
    up = lambda v: v + n if P <= v != NONE else v
    tr.routes = [(up(a), up(b), ids, ln) for a, b, ids, ln in tr.routes]
    new = []                                             # startpos TRADE_ROUTES (a, b, length)
    for j, (slot, key, dock, spos) in enumerate(ports):
        r = (P + j, P + n + tr.settlements.index(key), [], f32(math.dist(dock, spos)))
        tr.routes.append(r); tr.ports.append(slot); new.append((r[0], r[1], r[3]))
    for name, rs in tr.node_routes:
        k = int(name.rsplit('_', 1)[1])
        for j, (_, _, dock, _) in enumerate(ports):
            ln = f32(math.dist(dock, tr.node_pos[k]))
            rs.append((P + j, [], ln)); new.append((P + j, P + n + S + k, ln))
    open(tp, 'wb').write(esf.dumps(cm.write_trade_routes(tr)))
    tm = cm.first_rec(sp.root, 'CAMPAIGN_TRADE_MANAGER')
    pi = tm.find('PORT_INDICES')
    assert sorted(x[1].value for x in pi.items) == list(range(P))
    pi.items += [[Val(0x0e, slot), Val(0x08, P + j)] for j, (slot, *_) in enumerate(ports)]
    for name, lo, hi in (('SETTLEMENT_INDICES', P, P + S), ('TRADE_NODES', P + S, P + S + N)):
        x = tm.find(name).items
        assert sorted(i[1].value for i in x) == list(range(lo, hi)), name
        for i in x:
            i[1] = Val(0x08, i[1].value + n)
    items = tm.find('TRADE_ROUTES').items
    for x in items:
        x[0], x[1] = Val(0x08, up(x[0].value)), Val(0x08, up(x[1].value))
    tpl = items[0]
    for a, b, ln in new:
        x = copy.deepcopy(tpl)
        x[0], x[1], x[2], x[3] = Val(0x08, a), Val(0x08, b), wz.u32a([]), Val(0x0a, ln)
        items.append(x)
    cnt = collections.Counter()
    for name, at in (('DOMESTIC_TRADE_ROUTES', 3), ('INTERNATIONAL_TRADE_ROUTES', 0)):
        for fac in tm.find(name).items:
            for r in fac[1].items:
                cnt[name + ' hop indices'] += bump_hops(r[0].children, at, P, n)
    return dict(first_port_index=P, ports=n, settlements=S, nodes=N, routes_added=len(new), hop_indices_shifted=dict(cnt))


# ---------------------------------------------------------------- CAI
class Cai:
    def __init__(self, sp, rg):
        w = cm.first_rec(sp.root, 'CAI_WORLD')
        self.central = cm.first_rec(sp.root, 'CAI_CENTRAL_BDI_POOL')
        self.R, H, self.RS, self.BS = (w.find(n) for n in ('CAI_WORLD_REGIONS', 'CAI_WORLD_REGION_HLCIS',
                                                            'CAI_WORLD_REGION_SLOTS', 'CAI_WORLD_BUILDING_SLOTS'))
        self.blank = copy.deepcopy(H.items[0][:-1])
        assert [it[-1].children[10].value for it in self.R.items] == rg.names
        self.rid = [it[2].value for it in self.R.items]
        wt = next(r for r in cm._iter_recs(sp.root, 'REGION_SLOT') if slot_key(r) == TPL_EMPTY).children[2].value
        self.btpl = next(it for it in self.BS.items if it[-1].children[0].value == wt)
        self.rtpl = next(it for it in self.RS.items if it[3].value == self.btpl[-1].children[2].value)
        self.gi = next(j for j, c in enumerate(self.rtpl) if isinstance(c, Rec) and c.name == 'CAI_GARRISONABLE')
        assert (self.rtpl[-1].name == 'CAI_REGION_SLOT' and self.rtpl[-1].children[5].value and self.btpl[-1].children[1].value == 3
                and self.gi == 2 + len(self.blank) and self.rtpl[2].name == self.blank[0].name and len(self.rtpl) == self.gi + 3)

    def top(self, i):
        t = copy.deepcopy(self.blank); t[1] = Val(0x08, i); return t

    def add(self, h, pl, land, sea):
        """CAI_REGION_SLOT + CAI_BUILDING_SLOT kind 3 + the CAI_REGION slot list; land / sea = (region index, pass group)."""
        nxt = self.central.children[0].value
        rsid, bsid = nxt, nxt + 1
        rt, gi = self.rtpl, self.gi
        rsl = copy.deepcopy(rt[:2]) + self.top(rsid) + copy.deepcopy(rt[gi:])
        rsl[0].children[0] = Val(0x08, self.rid[land[0]])
        for sit, p, (ri, pg) in ((rsl[1], pl['bld'], land), (rsl[-1].children[6], pl['dock'], sea)):
            c = sit.children
            assert sit.name == 'CAI_SITUATED' and c[4].tag == 0x08
            c[0], c[1] = Val(0x04, round(p[0] * FIX)), Val(0x04, round(p[1] * FIX))
            c[2], c[3], c[4] = Val(0x08, self.rid[ri]), wz.u32a(self.R.items[ri][-1].children[0].array()), Val(0x08, pg)
        rsl[-1].children[1] = Val(0x08, bsid)
        g = rsl[gi].children
        assert rsl[gi].name == 'CAI_GARRISONABLE' and g[0].value == 0 and not g[2].array() and not g[3].array()
        self.RS.items.append(rsl)
        bsl = self.top(bsid) + [copy.deepcopy(self.btpl[-1])]
        bsl[-1].children[0], bsl[-1].children[2] = Val(0x08, h), Val(0x08, rsid)
        self.BS.items.append(bsl)
        rc = self.R.items[land[0]][-1].children
        rc[3] = wz.u32a(rc[3].array() + [rsid])
        self.central.children[0] = Val(0x08, nxt + 2)
        return dict(cai_region_slot=rsid, cai_building_slot=bsid, land_pass_group=land[1], sea_pass_group=sea[1])


def sea_grid(ov, ports):
    p = os.path.join(ov, MAPDIR, 'sea_grids.esf')
    raw = open(p, 'rb').read()
    sg = cm.read_sea_grids(esf.loads(raw))
    assert esf.dumps(cm.write_sea_grids(sg)) == raw, 'sea_grids round-trip'
    out = {}
    for slot, (x, y) in ports:
        k = [i for i, (cx, cy, (x0, y0), (x1, y1)) in enumerate(sg.cells) if x0 <= x < x1 and y0 <= y < y1]
        assert len(k) == 1, (slot, k)
        sg.info[k[0]][2].append(slot)
        out[slot] = k[0]
    open(p, 'wb').write(esf.dumps(cm.write_sea_grids(sg)))
    return out


# ---------------------------------------------------------------- driver
def add_ports(out, only=None):
    """Ports for the build in out (in place): every new region with a regions.json port (only: these keys)."""
    import world_regions
    t0 = __import__('time').time()
    ov = os.path.join(out, 'overlay')
    bi_p = os.path.join(out, 'build_info.json')
    B = json.load(open(bi_p))
    RJ = {r['key']: r for r in json.load(open(os.path.join(DATA, 'regions.json')))}
    moved = {k for k, v in (B.get('split') or {}).items() if any(sl.startswith('port:') for sl, _ in v['slots'])}
    keys = [k for k in B['regions'] if RJ[k].get('port') and k not in moved and (only is None or k in only)]   # split: vanilla's port moved
    yards = {v['regions'][0] for v in (B.get('faction') or {}).values()}       # generated factions' capitals
    rp_ = os.path.join(ov, MAPDIR, 'regions.esf')
    rg = Regions(esf.load(rp_))
    pf_p = os.path.join(ov, MAPDIR, 'pathfinding.esf')
    m = pm.PathfindingModel.load(pf_p)
    area = m.areas[0]; g = area.grid
    P = area.polygons()
    words0, ndom, table0 = len(area.polygon_words), len(g.path_domains()), g.path_table
    sea = B['pathfinding']['sea']
    assert g.path_domains()[sea] == ()
    reach = sea_reach(g)
    T = template()
    key = max(P) + 1
    placed_, deferred, todo_all, pstats = {}, {}, set(), collections.Counter()
    for k in keys:
        port = RJ[k]['port']
        dom = B['pathfinding']['domains'][k]
        assert g.path_domains()[dom] == (rg.names.index(k),)
        rpoly, settle = rg.region(k)
        target = tuple(map(float, proj.to_world(port['lon'], port['lat'])))
        banned, why, done = set(), None, None
        for strict, R, step in ((True, SEARCH_R, 0.25), (True, RETRY_R, 0.5), (False, SEARCH_R, 0.25), (False, RETRY_R, 0.5)):
            for _ in range(4):                          # a carve that fails bans its cells and places again
                hit = place(T, area, g, P, rpoly, rg.seas, dom, sea, target, reach, R, step, strict, banned)
                if hit is None:
                    break
                pl, score = hit
                r32 = lambda a: np.asarray(a, np.float32).astype(np.float64)       # what regions.esf stores
                pl = dict(pl, bld=r32(pl['bld']), dock=r32(pl['dock']), fp=[r32(a) for a in pl['fp']])
                F7, F8 = fixed_fp(*pl['fp'][:2])
                ks0 = touched(g, F7, F8)
                land, seaa = rg.area_at(pl['bld'], False), rg.area_at(pl['dock'], True)
                if land is None or rg.names[land[0]] != k or seaa is None:
                    why = f'building / dock not in exactly one regions.esf area of the region / of a sea ({land}, {seaa})'
                    banned |= set(ks0)
                    continue
                snap = {c: copy.deepcopy(g.cells[c]) for c in ring(g, ks0, 4)}
                before = {c: land_sea_masks(g.cells[c], dom, sea) for c in ring(g, ks0, 8)}
                ks, near, st, key = carve(area, P, F7, F8, dom, sea, key)
                over = [c for c in ks if max(class_counts(area, P, c, sea)) > MAX_POLYS]
                weld = [] if over else unwelded(area, P, ks)
                if over or weld:
                    for c, v in snap.items():
                        g.cells[c] = v
                    why = (f'> {MAX_POLYS} passable polygons of a class in carved cells' if over else
                           'carved cell sides not welded to their neighbours') + ' (every placement tried)'
                    banned |= set(over or weld)
                    pstats['placements retried (cells: ' + ('> 4 polygons' if over else 'unwelded') + ')'] += 1
                    continue
                done = strict
                break
            if done is not None:
                break
        if done is None:
            deferred[k] = why or (f'no footprint fit within {RETRY_R:g} u of the port point: no sea reachable from the open '
                                  'sea there (a lake / the Caspian) or no coast of the region')
            continue
        nc = recost(g, ks, before, dom, sea)
        todo_all |= set(ring(g, ks, 8))
        pstats.update(st); pstats['cells carved'] += len(ks); pstats['costs8 changed'] += nc
        slot = f"port:{k}:{world_regions.slug(port['name'])}"
        rg.add_slot(k, slot, pl, T)
        placed_[k] = dict(slot=slot, name=port['name'], building=[float(v) for v in pl['bld']],
                          dock=[float(v) for v in pl['dock']], angle=pl['angle'], score_u2=score[0],
                          target_dist=round(-score[1], 2), shipyard=k in yards, settlement=list(settle),
                          building_lonlat=[round(float(v), 3) for v in proj.to_lonlat(*pl['bld'])],
                          dock_lonlat=[round(float(v), 3) for v in proj.to_lonlat(*pl['dock'])],
                          coast='banded' if done else 'unbanded (footprint redraws the coast)',
                          land_area=list(land), sea_area=[rg.names[seaa[0]], seaa[1]], _seaa=seaa)
        print(f"port {k}: {slot} score {score[0]} dist {-score[1]:.1f} u{' shipyard' if k in yards else ''}"
              f"{'' if done else ' unbanded coast'}", flush=True)
    pf_gen.compact(area, P)
    assert g.path_table == table0 and len(g.path_domains()) == ndom
    assert len(area.polygon_words) < pm.STATIC_LIMIT
    open(pf_p, 'wb').write(m.encode())
    open(rp_, 'wb').write(esf.dumps(rg.e))
    sp_p = os.path.join(out, 'startpos.esf')
    sp = esf.load(sp_p)
    tpls = {t: next(r for r in cm._iter_recs(sp.root, 'REGION_SLOT') if slot_key(r) == t) for t in (TPL_YARD, TPL_EMPTY)}
    used = lp.all_ints(sp.root)
    cai = Cai(sp, rg)
    for k, d in placed_.items():
        pl = dict(bld=d['building'], dock=d['dock'])
        d.update(startpos_slot(sp, tpls, used, k, d['slot'], pl, d['shipyard']))
        d.update(cai.add(d['handle'], pl, tuple(d['land_area']), d.pop('_seaa')))
    tinfo = trade(ov, sp, [(d['slot'], k, d['dock'], d['settlement']) for k, d in placed_.items()])
    cells = sea_grid(ov, [(d['slot'], d['dock']) for d in placed_.values()])
    for d in placed_.values():
        d['sea_grid_cell'] = cells[d['slot']]
    open(sp_p, 'wb').write(esf.dumps(sp))
    cm._FIRST.clear()                                    # first_rec holds the sp tree
    db_rows(ov, [[d['slot'], 'port', d['name']] for d in placed_.values()])
    loc_add(out, [(f"campaign_map_towns_and_ports_onscreen_name_{d['slot']}", d['name'], 0) for d in placed_.values()])
    info = dict(asked=len(keys), placed=placed_, deferred=deferred, shipyards=sorted(k for k in placed_ if placed_[k]['shipyard']),
                pathfinding=dict(pstats, words_before=words0, words_after=len(area.polygon_words),
                                 words_added=len(area.polygon_words) - words0, domains=ndom, limit=pm.STATIC_LIMIT,
                                 path_table_crc=zlib.crc32(struct.pack(f'<{len(g.path_table)}H', *g.path_table)),
                                 checked_cells=sorted(todo_all)),
                trade=tinfo, seconds=round(__import__('time').time() - t0))
    B['ports'] = info
    B['ports_deferred'] = deferred
    json.dump(B, open(bi_p, 'w'), indent=1, default=str)
    print(json.dumps({k: v for k, v in info.items() if k not in ('placed',)}, default=str)[:3000])
    print(f'ports placed {len(placed_)} / {len(keys)}, deferred {len(deferred)}; words {words0} -> {len(area.polygon_words)}')
    return info


# ---------------------------------------------------------------- check
def check(out):
    ov = os.path.join(out, 'overlay')
    cm._FIRST.clear()                                    # memoised records of an earlier startpos tree
    B = json.load(open(os.path.join(out, 'build_info.json')))
    I = B['ports']
    pls = I['placed']
    res = []

    def rep(what, ok, detail=''):
        res.append(bool(ok))
        print(('  ok   ' if ok else '  FAIL ') + what + (f': {str(detail)[:700]}' if detail != '' else ''))
    print(f"== ports: {len(pls)} placed of {I['asked']}, {len(I['deferred'])} deferred {I['deferred']}")
    # ---- regions.esf
    rg = Regions(esf.load(os.path.join(ov, MAPDIR, 'regions.esf')))
    bad, fr, fp = [], [], {}
    for k, d in pls.items():
        rpoly, _ = rg.region(k)
        it = rg.items[rg.names.index(k)]
        s = [x for x in rm.sub(it, 'settlement_and_slots').find('slot_descriptions').items if x[1].value == 'port']
        f7, f8 = (Polygon(rm.nparr(s[0][j]).reshape(-1, 2)) for j in (7, 8)) if len(s) == 1 else (Polygon(), Polygon())
        fp[k] = (f7, f8)
        if not (len(s) == 1 and s[0][0].value == d['slot'] and rpoly.contains(Point(*d['building'])) and rpoly.contains(f7)
                and rg.seas.contains(Point(*d['dock']))):
            bad.append(k)
        fr.append(f8.intersection(rg.seas).area / max(f8.area, 1e-9))
    rep('regions.esf: one port slot per port region, building + land half in the region, dock in a sea region', not bad,
        f"{bad}; sea half on regions.esf sea min {min(fr, default=1):.0%} median {sorted(fr)[len(fr) // 2] if fr else 1:.0%}")
    # ---- pathfinding
    area = pm.PathfindingModel.load(os.path.join(ov, MAPDIR, 'pathfinding.esf')).areas[0]
    g = area.grid
    P = area.polygons()
    sea = B['pathfinding']['sea']
    ipf = I['pathfinding']
    rep('pathfinding: path-domain table unchanged by the ports',
        len(g.path_domains()) == ipf['domains'] and zlib.crc32(struct.pack(f'<{len(g.path_table)}H', *g.path_table)) == ipf['path_table_crc'],
        f"{len(g.path_domains())} domains")
    rep('pathfinding: polygon words', ipf['words_after'] == len(area.polygon_words) < pm.STATIC_LIMIT,
        f"{ipf['words_before']} -> {ipf['words_after']} (+{ipf['words_added']}), limit {pm.STATIC_LIMIT}")
    abad, pbad, over = {}, {}, set()

    def at(p):
        c = cells_in(g, (p.x, p.y, p.x, p.y))[0]
        return c, [t for t, q in probe_g3.cell_polys(area, P, c) if Polygon([(a / FIX, b / FIX) for a, b in q]).covers(p)]
    reach = sea_reach(g)
    unreach = []
    for k, d in pls.items():
        dom = B['pathfinding']['domains'][k]
        F7, F8 = fixed_fp(fp[k][0].exterior.coords[:-1], fp[k][1].exterior.coords[:-1])
        ks = touched(g, F7, F8)
        a7 = collections.Counter()
        for c in ks:
            for t, q in probe_g3.cell_polys(area, P, c):
                if t.kind == 7:
                    Q = Polygon(q)
                    a7['land'] += Q.intersection(F7).area / FIX ** 2 if t.path_id == dom else 0
                    a7['sea'] += Q.intersection(F8).area / FIX ** 2 if t.path_id == sea else 0
            if max(class_counts(area, P, c, sea)) > MAX_POLYS:
                over.add(c)
        if abs(a7['land'] - F7.area / FIX ** 2) > 1e-3 or abs(a7['sea'] - F8.area / FIX ** 2) > 1e-3:
            abad[k] = dict(a7)
        cb, tb = at(Point(*d['building']))
        cd, td = at(Point(*d['dock']))
        if not (tb and all(t.kind == 7 and t.path_id == dom for t in tb) and td and all(t.kind not in (2, 3) and t.path_id == sea for t in td)):
            pbad[k] = ([(t.kind, t.path_id) for t in tb], [(t.kind, t.path_id) for t in td])
        if cd not in reach:
            unreach.append(k)
    rep('pathfinding: kind-7 land of the region covers each land half, kind-7 sea each sea half', not abad, abad)
    rep('pathfinding: every building on kind-7 land of its region, every dock on sea', not pbad, pbad)
    rep(f'pathfinding: <= {MAX_POLYS} passable polygons per class in the carved cells', not over, sorted(over)[:5])
    rep('pathfinding: every dock cell reachable by sea from the Bay of Biscay', not unreach, f'{unreach}; {len(reach)} sea cells')
    bad, ex = pf_check.check(area, ipf['checked_cells'])
    rep('pathfinding: welded (shared sides split alike) round every footprint', not bad, (dict(bad), ex[:2]))
    try:
        pm.rebuild_spatial_grid(area); ok, err = True, ''
    except AssertionError as x:
        ok, err = False, repr(x)
    rep('pathfinding: rebuild_spatial_grid (CCW, in-cell, tile area, contact masks) over the whole grid', ok, err)
    del area, P
    # ---- startpos slots
    sp = esf.load(os.path.join(out, 'startpos.esf'))
    sbad = []
    own = lambda r: r.find('SIEGEABLE_GARRISON_RESIDENCE').find('GARRISON_RESIDENCE').children[0].value
    for k, d in pls.items():
        _, arr = region_slots(sp, k)
        mine = [x[0] for x in arr.items if slot_key(x[0]) == d['slot']]
        st_ = next(x[0] for x in arr.items if slot_key(x[0]).endswith(':settlement_1_slot:1'))
        b = mine[0].find('BUILDING_MANAGER').find('BUILDING') if mine else None
        if not (len(mine) == 1 and own(mine[0]) == own(st_) and mine[0].children[2].value == d['handle']
                and (mine[0].children[6].value, mine[0].children[7].value) == (round(d['building'][0] * FIX), round(d['building'][1] * FIX))
                and (b is not None) == d['shipyard']
                and (b is None or (b.children[1].value == 'pNavy1_shipyard'
                                   and b.children[2].value == st_.find('BUILDING_MANAGER').find('BUILDING').children[2].value))):
            sbad.append(k)
    rep(f"startpos: a port REGION_SLOT per port, owned like its settlement, at the building; shipyard (for the owner) in "
        f"the {len(I['shipyards'])} generated factions' coastal capitals only", not sbad, sbad)
    # ---- db / loc
    tb_ = {r[0]: r for r in dbtable.load(os.path.join(ov, TOWNS_T))['rows']}
    lr = set(loc.from_tsv(open(os.path.join(out, 'loc_rows.tsv'), encoding='utf-8').read()))
    dbad = [k for k, d in pls.items() if tb_.get(d['slot']) != [d['slot'], 'port', d['name']]
            or (f"campaign_map_towns_and_ports_onscreen_name_{d['slot']}", d['name'], 0) not in lr]
    rep('db campaign_map_towns_and_ports row + loc onscreen name per port', not dbad, f'{dbad}; {len(tb_)} rows')
    # ---- trade
    tm = cm.first_rec(sp.root, 'CAMPAIGN_TRADE_MANAGER')
    tr = cm.read_trade_routes(esf.load(os.path.join(ov, MAPDIR, 'trade_routes.esf')))
    Pn, Sn, Nn = len(tr.ports), len(tr.settlements), len(tr.node_routes)
    pix = {x[0].value: x[1].value for x in tm.find('PORT_INDICES').items}
    six = {x[0].value: x[1].value for x in tm.find('SETTLEMENT_INDICES').items}
    tnodes = sorted(x[1].value for x in tm.find('TRADE_NODES').items)
    routes = [(x[0].value, x[1].value, tuple(x[2].array()), x[3].value) for x in tm.find('TRADE_ROUTES').items]
    esr = {(a, b, tuple(ids), ln) for a, b, ids, ln in tr.routes}
    nr = {(a, Pn + Sn + int(n.rsplit('_', 1)[1]), tuple(ids), ln) for n, rs in tr.node_routes for a, ids, ln in rs}
    hops = []
    for name, at_ in (('DOMESTIC_TRADE_ROUTES', 3), ('INTERNATIONAL_TRADE_ROUTES', 0)):
        for fac in tm.find(name).items:
            for r in fac[1].items:
                c = r[0].children
                hops += [(c[at_ + 3 + 5 * j].value, c[at_ + 4 + 5 * j].value) for j in range(c[at_].value)]
    cl = lambda v: 'n' if v == NONE else 'p' if v < Pn else 's' if v < Pn + Sn else 'k' if v < Pn + Sn + Nn else '?'
    hc = collections.Counter((cl(a), cl(b)) for a, b in hops)
    rep('trade indices consistent (trade_routes.esf <-> startpos: ports, settlements, nodes, routes, route hops)',
        pix == {p_: i for i, p_ in enumerate(tr.ports)} and six == {s2: Pn + i for i, s2 in enumerate(tr.settlements)}
        and tnodes == list(range(Pn + Sn, Pn + Sn + Nn)) and set(routes) == esr | nr and len(routes) == len(esr) + len(nr)
        and set(hc) <= {('s', 's'), ('n', 'n'), ('p', 'p'), ('k', 'p')}, f'P={Pn} S={Sn} N={Nn} routes {len(routes)} hops {dict(hc)}')
    P0 = I['trade']['first_port_index']
    per = collections.Counter(a for a, b, *_ in routes if a >= P0 and a < Pn)
    tbad = [k for k, d in pls.items() if pix.get(d['slot'], -1) < P0 or per[pix[d['slot']]] != 1 + Nn
            or not any(a == pix[d['slot']] and b == six[k] for a, b, *_ in routes)]
    rep('trade: every port registered (index >= the vanilla ports), one route to its settlement + one per trade node; '
        'every node lists every port', not tbad and Pn == P0 + len(pls) and all(len(rs) == Pn for _, rs in tr.node_routes), tbad)
    # ---- CAI
    w = cm.first_rec(sp.root, 'CAI_WORLD')
    BS, RS, Rg = (w.find(n) for n in ('CAI_WORLD_BUILDING_SLOTS', 'CAI_WORLD_REGION_SLOTS', 'CAI_WORLD_REGIONS'))
    bsh = collections.defaultdict(list)
    for x in BS.items:
        bsh[x[-1].children[0].value].append(x)
    rsi = {x[3].value: x for x in RS.items}
    ids = collections.Counter([x[1].value for x in BS.items] + [x[3].value for x in RS.items])
    nxt = cm.first_rec(sp.root, 'CAI_CENTRAL_BDI_POOL').children[0].value
    cbad = []
    for k, d in pls.items():
        rr = Rg.items[rg.names.index(k)]
        bs = bsh.get(d['handle'], [])
        rs = rsi.get(bs[0][-1].children[2].value) if len(bs) == 1 else None
        if not (rs is not None and bs[0][-1].children[1].value == 3 and rs[-1].children[1].value == bs[0][1].value
                and rs[3].value in rr[-1].children[3].array() and rs[0].children[0].value == rr[2].value
                and rs[1].children[4].value == d['land_area'][1] and rs[-1].children[6].children[4].value == d['sea_area'][1]
                and ids[d['cai_region_slot']] == 1 and ids[d['cai_building_slot']] == 1
                and nxt > max(d['cai_region_slot'], d['cai_building_slot'])):
            cbad.append(k)
    rep('CAI: per port building slot (kind 3) -> region slot (situated on its land / sea area pass groups) -> the '
        'region\'s slot list; ids unique, below the pool counter', not cbad, cbad)
    sg = cm.read_sea_grids(esf.load(os.path.join(ov, MAPDIR, 'sea_grids.esf')))
    where = collections.defaultdict(list)
    for c, inf in enumerate(sg.info):
        for s in inf[2]:
            where[s].append(c)
    gbad = [k for k, d in pls.items() if where[d['slot']] != [d['sea_grid_cell']] or not sg.info[d['sea_grid_cell']][1]]
    rep('sea_grids: every port in its dock\'s cell (a cell listing sea regions)', not gbad, gbad)
    print('  ports PASS' if all(res) else f'  ports: {res.count(False)} FAIL')
    return all(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=('build', 'check'))
    ap.add_argument('--src', default=os.path.join(ROOT, 'work/world/w7_s_v'))
    ap.add_argument('--out', help='default <src>_ports')
    ap.add_argument('--regions', help='comma-separated region keys (default: every new region with a port)')
    a = ap.parse_args()
    src = os.path.abspath(a.src)
    out = os.path.abspath(a.out or src + '_ports')
    if a.cmd == 'build':
        if os.path.exists(out):
            shutil.rmtree(out)
        shutil.copytree(src, out)
        add_ports(out, a.regions.split(',') if a.regions else None)
    sys.exit(0 if check(out) else 1)


if __name__ == '__main__':
    main()
