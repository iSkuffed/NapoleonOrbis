#!/usr/bin/env python3
"""Semantic readers/writers + coordinate transforms for the "misc" NTW campaign files.

  poi.esf            CAI_POI_ROOT  (flat Val stream: u32 count, then variable-length nodes)
  trade_routes.esf   root{SPLINES,PORTS,SETTLEMENTS,ROUTES,TRADE_NODE_ROUTES}
  sea_grids.esf      CAI_SEA_GRID_ROOT (cell grid + per-cell region lists + port-cell cost matrix)
  metadata.dat       'MTGI' u32 w u32 h + u8[h*w] (row 0 = north), 6 = sea
  startpos.esf       coordinate-bearing fields only (see research/08-poi-trade-seagrid-startpos.md)

Every writer is byte-exact against the vanilla files (self-check at the bottom).
transform_coords(obj, fn, scale=1.0) maps every coordinate field with fn(x, y) -> (x, y) (world
units, float) and multiplies scalar *length* fields (route lengths, POI distances, sea-grid costs and
cell size) by `scale`.  Fixed-point (i32 / 2**20) fields round back to int, so a dyadic translate and
its inverse is byte-exact for poi.esf and the startpos fixed fields; f32 fields round to float32.
fn must be axis-aligned (translate/scale) for sea_grids cells and startpos LINE_OF_SIGHT bit arrays /
grid cells to stay valid; other maps give geometry that needs regenerating, not just remapping.
"""
import os, struct, sys
from dataclasses import dataclass, field
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esf
from esf import Esf, Rec, Val

FIX = 1 << 20
T_BOOL, T_I32, T_U32, T_F32, T_XY, T_STR = 0x01, 0x04, 0x08, 0x0A, 0x0C, 0x0E
T_XYA, T_U32A = 0x4C, 0x48


def _fix(v): return v / FIX
def _unfix(w):
    v = int(round(w * FIX))
    if not -2**31 <= v < 2**31: raise OverflowError(f"fixed-point overflow: {w}")
    return v
def _f32(v): return float(np.float32(v))


# ---------------------------------------------------------------- poi.esf
@dataclass
class PoiNode:
    id: int; kind: int; flag: bool; x: int; y: int      # x,y: i32 fixed point (world = v / 2**20)
    region: str; area: int; region2: str; area2: int    # region key, area id (4 normal, 6 sea, 7 off-map, 0 border)
    dist: float                                         # f32 (0 for kinds 4,6,7,8 mostly)
    neighbors: list                                     # [(adjacent region key, f32 dist)]
    min_dist: float                                     # min(neighbor dists) or -1.0
    near: list                                          # [(region key, f32)] only kind 3 (port/coast tie)
    links: list                                         # [u32 poi ids] only kind 6 (sea node -> coast node)
    edge_idx: int                                       # u32; kind 8 border nodes: 0..n sequence, else 0
    last: bool
    @property
    def wx(self): return self.x / FIX
    @property
    def wy(self): return self.y / FIX


@dataclass
class Poi:
    nodes: list
    timestamp: int = 0
    names: list = field(default_factory=lambda: ["CAI_POI_ROOT"])


def _poi_spans(t):
    """Yield (start, n_neighbors, n_near, n_links, end) for each node in the flat Val list t."""
    p = 1
    for _ in range(t[0].value):
        n1 = t[p + 10].value; m = p + 11 + 2 * n1          # m = min_dist index
        n2 = t[m + 1].value; c3 = m + 2 + 2 * n2
        n3 = t[c3].value; end = c3 + 1 + n3 + 2
        yield p, n1, n2, n3, end
        p = end
    if p != len(t): raise ValueError(f"poi trailing tokens {len(t) - p}")


def read_poi(e: Esf) -> Poi:
    assert e.root.name == "CAI_POI_ROOT" and e.root.version == 0
    t = e.root.children; nodes = []
    for p, n1, n2, n3, end in _poi_spans(t):
        v = [x.value for x in t[p:end]]
        m = 11 + 2 * n1
        nodes.append(PoiNode(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9],
                             [(v[11 + 2 * i], v[12 + 2 * i]) for i in range(n1)], v[m],
                             [(v[m + 2 + 2 * i], v[m + 3 + 2 * i]) for i in range(n2)],
                             v[m + 3 + 2 * n2:m + 3 + 2 * n2 + n3], v[-2], v[-1]))
    return Poi(nodes, e.timestamp, list(e.names))


def write_poi(poi: Poi) -> Esf:
    u, i4, f, s, b = (lambda v: Val(T_U32, v)), (lambda v: Val(T_I32, v)), (lambda v: Val(T_F32, v)), \
                     (lambda v: Val(T_STR, v)), (lambda v: Val(T_BOOL, v))
    k = [u(len(poi.nodes))]
    for n in poi.nodes:
        k += [u(n.id), i4(n.kind), b(n.flag), i4(n.x), i4(n.y), s(n.region), u(n.area), s(n.region2),
              u(n.area2), f(n.dist), u(len(n.neighbors))]
        for r, d in n.neighbors: k += [s(r), f(d)]
        k += [f(n.min_dist), u(len(n.near))]
        for r, d in n.near: k += [s(r), f(d)]
        k += [u(len(n.links))] + [u(i) for i in n.links] + [u(n.edge_idx), b(n.last)]
    return Esf(Rec("CAI_POI_ROOT", 0, k), poi.timestamp, poi.names)


def _transform_poi(e, fn, scale):
    t = e.root.children
    for p, n1, n2, n3, end in _poi_spans(t):
        x, y = fn(t[p + 3].value / FIX, t[p + 4].value / FIX)
        t[p + 3].value, t[p + 4].value = _unfix(x), _unfix(y)
        if scale != 1.0:
            m = p + 11 + 2 * n1
            idx = [p + 9, m] + [p + 12 + 2 * i for i in range(n1)] + [m + 3 + 2 * i for i in range(n2)]
            for i in idx:
                if t[i].value != -1.0: t[i].value = _f32(t[i].value * scale)


# ---------------------------------------------------------------- trade_routes.esf
@dataclass
class TradeRoutes:
    splines: list        # [(points [(x,y)], flag)]  world float xy polylines
    ports: list          # ['port:eur_england:chatham'] -> route node indices 0..P-1
    settlements: list    # ['eur_courland'] -> node indices P..P+S-1
    routes: list         # [(node_a, node_b, [spline_ref], length)]; spline_ref = 2*spline + reversed
    node_pos: list       # [(x,y)] trade-node positions (startpos TRADE_NODES / CAI_TRADING_POST)
    node_routes: list    # [(node name, [(target idx, [spline_ref], length)])]
    timestamp: int = 0
    names: list = field(default_factory=list)


def _xy_arr(v): return v.array()
def _pack_xy(pts): return Val(T_XYA, b"".join(struct.pack("<2f", *p) for p in pts))
def _pack_u32(a): return Val(T_U32A, struct.pack(f"<{len(a)}I", *a))
def _u32_arr(v): return list(struct.unpack(f"<{len(v.value) // 4}I", v.value))


def read_trade_routes(e: Esf) -> TradeRoutes:
    r = e.root; assert r.name == "root"
    g = lambda n: r.find(n)
    for rec in r.children: assert rec.version == 0
    tn = g("TRADE_NODE_ROUTES").items
    return TradeRoutes(
        [(_xy_arr(i[0]), i[1].value) for i in g("SPLINES").items],
        [i[0].value for i in g("PORTS").items], [i[0].value for i in g("SETTLEMENTS").items],
        [(i[0].value, i[1].value, _u32_arr(i[2]), i[3].value) for i in g("ROUTES").items],
        _xy_arr(tn[0][0]),
        [(i[0].value, [(j[0].value, _u32_arr(j[1]), j[2].value) for j in i[1].items]) for i in tn[1:]],
        e.timestamp, list(e.names))


def write_trade_routes(t: TradeRoutes) -> Esf:
    arr = lambda n, items: Rec(n, 0, None, items)
    return Esf(Rec("root", 0, [
        arr("SPLINES", [[_pack_xy(p), Val(T_BOOL, fl)] for p, fl in t.splines]),
        arr("PORTS", [[Val(T_STR, n)] for n in t.ports]),
        arr("SETTLEMENTS", [[Val(T_STR, n)] for n in t.settlements]),
        arr("ROUTES", [[Val(T_U32, a), Val(T_U32, b), _pack_u32(ids), Val(T_F32, ln)] for a, b, ids, ln in t.routes]),
        arr("TRADE_NODE_ROUTES", [[_pack_xy(t.node_pos)]] + [
            [Val(T_STR, n), arr("ROUTES", [[Val(T_U32, a), _pack_u32(ids), Val(T_F32, ln)] for a, ids, ln in rs])]
            for n, rs in t.node_routes])]), t.timestamp, t.names)


def _map_xy_val(v, fn):
    pts = v.array()
    v.value = b"".join(struct.pack("<2f", *fn(x, y)) for x, y in pts)


def _transform_trade(e, fn, scale):
    r = e.root
    for it in r.find("SPLINES").items: _map_xy_val(it[0], fn)
    _map_xy_val(r.find("TRADE_NODE_ROUTES").items[0][0], fn)
    if scale != 1.0:
        for it in r.find("ROUTES").items: it[3].value = _f32(it[3].value * scale)
        for it in r.find("TRADE_NODE_ROUTES").items[1:]:
            for j in it[1].items: j[2].value = _f32(j[2].value * scale)


# ---------------------------------------------------------------- sea_grids.esf
@dataclass
class SeaGrid:
    version: int; grid_id: str          # grid_id: decimal-string id also echoed in startpos DOMESTIC_TRADE_ROUTE
    bmin: tuple; bmax: tuple            # theatre box (xy floats)
    cell: float; cols: int; rows: int   # cols = floor(w/cell)+1, rows = floor(h/cell)+1 (grid overhangs bmax)
    cells: list                         # [(cx, cy, (x0,y0), (x1,y1))] row-major, cell k = cy*cols+cx
    info: list                          # per cell: [land region keys, sea region keys, port keys, poi node ids]
    edges: list                         # [(cell_a, cell_b, cost)] all pairs of sea cells; cost 0.0/-1.0 = none
    timestamp: int = 0
    names: list = field(default_factory=lambda: ["CAI_SEA_GRID_ROOT"])


def read_sea_grids(e: Esf) -> SeaGrid:
    assert e.root.name == "CAI_SEA_GRID_ROOT" and e.root.version == 0
    c = [x.value for x in e.root.children]
    cols, rows = c[5], c[6]; p = 7; cells = []
    for _ in range(cols * rows):
        cells.append((c[p], c[p + 1], c[p + 2], c[p + 3])); p += 4
    info = []
    for k in range(cols * rows):
        assert c[p] == k; p += 1; lists = []
        for _ in range(3):
            n = c[p]; lists.append(c[p + 1:p + 1 + n]); p += 1 + n
        n = c[p]; lists.append(c[p + 1:p + 1 + n]); p += 1 + n
        info.append(lists)
    n = c[p]; p += 1
    edges = [tuple(c[p + 3 * i:p + 3 * i + 3]) for i in range(n)]
    assert p + 3 * n == len(c)
    return SeaGrid(c[0], c[1], c[2], c[3], c[4], cols, rows, cells, info, edges, e.timestamp, list(e.names))


def write_sea_grids(g: SeaGrid) -> Esf:
    u, s = (lambda v: Val(T_U32, v)), (lambda v: Val(T_STR, v))
    k = [u(g.version), s(g.grid_id), Val(T_XY, g.bmin), Val(T_XY, g.bmax), Val(T_F32, g.cell), u(g.cols), u(g.rows)]
    for cx, cy, a, b in g.cells: k += [u(cx), u(cy), Val(T_XY, a), Val(T_XY, b)]
    for i, lists in enumerate(g.info):
        k.append(u(i))
        for j, l in enumerate(lists):
            k.append(u(len(l))); k += [(s if j < 3 else u)(v) for v in l]
    k.append(u(len(g.edges)))
    for a, b, cst in g.edges: k += [u(a), u(b), Val(T_F32, cst)]
    return Esf(Rec("CAI_SEA_GRID_ROOT", 0, k), g.timestamp, g.names)


def sea_grid_dims(bmin, bmax, cell=75.0):
    return int((bmax[0] - bmin[0]) // cell) + 1, int((bmax[1] - bmin[1]) // cell) + 1


def make_sea_grid_cells(bmin, bmax, cell=75.0):
    """Cell geometry for a theatre box (everything else in sea_grids is region/POI/port derived)."""
    cols, rows = sea_grid_dims(bmin, bmax, cell)
    return cols, rows, [(cx, cy, (bmin[0] + cx * cell, bmin[1] + cy * cell),
                         (bmin[0] + (cx + 1) * cell, bmin[1] + (cy + 1) * cell))
                        for cy in range(rows) for cx in range(cols)]


def _transform_sea_grid(e, fn, scale):
    k = e.root.children; cols, rows = k[5].value, k[6].value
    xys = [k[2], k[3]] + [k[7 + 4 * i + j] for i in range(cols * rows) for j in (2, 3)]
    for v in xys: v.value = tuple(_f32(c) for c in fn(*v.value))
    k[4].value = _f32(k[4].value * scale)
    p = 7 + 4 * cols * rows                      # skip per-cell lists to reach the edge count
    for _ in range(cols * rows):
        p += 1
        for _ in range(4): p += 1 + k[p].value
    ne = k[p].value
    if scale != 1.0:
        for i in range(ne):
            v = k[p + 1 + 3 * i + 2]
            if v.value > 0: v.value = _f32(v.value * scale)


# ---------------------------------------------------------------- metadata.dat
META_MAGIC = b"MTGI"
# nap_europe metadata.dat (2048x1024) world<->pixel affine, fitted (99.6% agreement of POI land/sea nodes,
# independent check: 0.0004% of heightmap>20 pixels land on sea): col = wx*S + OX, row = OY - wy*S.
# Covers world x ~[-456.3, 439.7], y ~[-217.9, 230.1] (896 x 448 units, ~2.2857 px/unit), +-1 px.
META_EUROPE = dict(S=16 / 7, OX=1043.0, OY=526.0)


@dataclass
class Meta:
    data: np.ndarray    # uint8 (h, w), row 0 = north

    @property
    def w(self): return self.data.shape[1]
    @property
    def h(self): return self.data.shape[0]


def read_metadata(b) -> Meta:
    if isinstance(b, str):
        with open(b, "rb") as f: b = f.read()
    assert b[:4] == META_MAGIC, b[:4]
    w, h = struct.unpack_from("<2I", b, 4)
    assert len(b) == 12 + w * h
    return Meta(np.frombuffer(b, np.uint8, w * h, 12).reshape(h, w).copy())


def write_metadata(m: Meta) -> bytes:
    return META_MAGIC + struct.pack("<2I", m.w, m.h) + m.data.tobytes()


def meta_px(wx, wy, a=META_EUROPE): return wx * a["S"] + a["OX"], a["OY"] - wy * a["S"]


def resample_metadata(m: Meta, fn_inv, w, h):
    """Nearest-neighbour rebuild: dst pixel (col,row) -> src pixel via fn_inv(col,row)->(col,row); outside = 0."""
    cc, rr = np.meshgrid(np.arange(w), np.arange(h))
    sc, sr = fn_inv(cc + 0.0, rr + 0.0)
    sc, sr = np.round(sc).astype(int), np.round(sr).astype(int)
    ok = (sc >= 0) & (sc < m.w) & (sr >= 0) & (sr < m.h)
    out = np.zeros((h, w), np.uint8); out[ok] = m.data[sr[ok], sc[ok]]
    return Meta(out)


# ---------------------------------------------------------------- startpos.esf
# (record-path suffix, kind, leaf indices).  Path = names from CAMPAIGN_MODEL down, matched as suffix.
#   fix  : i32 fixed-point (x,y) leaf pair          f32 : f32 (x,y) leaf pair
# Pairs that are exactly (0,0) are "not on map" sentinels and left alone.  Generic: every xy (0x0c) leaf.
START_RULES = [
    (("REGION_SLOT_ARRAY", "REGION_SLOT"), "fix", (6, 7)),
    (("ROAD_SLOT", "REGION_SLOT"), "fix", (6, 7)),
    (("FORTIFICATION_SLOT", "REGION_SLOT"), "fix", (6, 7)),
    (("REGION", "SETTLEMENT", "SIEGEABLE_GARRISON_RESIDENCE"), "fix", (10, 11)),
    (("CHARACTER", "LOCOMOTABLE"), "fix", (0, 1)), (("CHARACTER", "LOCOMOTABLE"), "fix", (2, 3)),
    (("CAI_WORLD_REGION_SLOTS", "CAI_REGION_SLOT", "CAI_SITUATED"), "fix", (0, 1)),
    (("CAI_WORLD_REGION_SLOTS", "CAI_SITUATED"), "fix", (0, 1)),
    (("CAI_WORLD_RESOURCE_MOBILES", "CAI_SITUATED"), "fix", (0, 1)),
    (("CAI_WORLD_SETTLEMENTS", "CAI_SITUATED"), "fix", (0, 1)),
    (("CAI_WORLD_TRADING_POSTS", "CAI_TRADING_POST"), "fix", (1, 2)),
    (("CAI_WORLD_REGION_HLCIS", "CAI_REGION_HLCI"), "fix", (3, 4)),
    (("CAI_WORLD_REGIONS", "CAI_REGION"), "f32", (4, 5)),
    (("CAI_BDIM_MOVE_TO_POSITION",), "fix", (1, 2)),
    (("CAI_BDIM_WAIT_HERE",), "fix", (0, 1)),
    (("CAI_HLPP_INFO",), "fix", (1, 2)),
    (("CAI_BORDER_PATROL_ANALYSIS_AREA_SPECIFIC",), "fix", (3, 4)),
    (("CAI_BORDER_PATROL_POINT",), "fix", (0, 1)),
]
_RULES_BY_NAME = {}
for _p, _k, _i in START_RULES: _RULES_BY_NAME.setdefault(_p[-1], []).append((_p, _k, _i))


def _poly_stream(v, fn):
    """PATHFINDING_GRID leaf 1: u32 stream of [n][n x (i32 x, i32 y)][u32 kind] obstacle polygons."""
    u = np.frombuffer(v.value, "<u4").copy(); p = 0
    while p < len(u):
        n = int(u[p]); xy = u[p + 1:p + 1 + 2 * n].view("<i4").reshape(-1, 2)
        for j in range(n):
            x, y = fn(xy[j, 0] / FIX, xy[j, 1] / FIX); xy[j] = (_unfix(x), _unfix(y))
        u[p + 1:p + 1 + 2 * n] = xy.reshape(-1).view("<u4"); p += 2 + 2 * n
    assert p == len(u)
    v.value = u.tobytes()


def _transform_startpos(e, fn, scale, pathfinder, los):
    cnt = {}
    def bump(k): cnt[k] = cnt.get(k, 0) + 1
    def walk(rec, stack, kids):
        # direct xy leaves (LINE_OF_SIGHT bounds, trade polylines/nodes, region-group analysis ...)
        for v in kids:
            if isinstance(v, Val):
                if v.tag == T_XY and v.value != (0.0, 0.0):
                    v.value = tuple(_f32(c) for c in fn(*v.value)); bump("xy:" + rec.name)
                elif v.tag == T_XYA: _map_xy_val(v, fn); bump("xya:" + rec.name)
        for pat, kind, (ix, iy) in _RULES_BY_NAME.get(rec.name, ()):
            if tuple(stack[-len(pat):]) != pat: continue
            a, b = kids[ix], kids[iy]
            if kind == "fix":
                assert a.tag == b.tag == T_I32, (pat, a.tag, b.tag)
                if (a.value, b.value) == (0, 0): continue
                x, y = fn(a.value / FIX, b.value / FIX); a.value, b.value = _unfix(x), _unfix(y)
            else:
                assert a.tag == b.tag == T_F32, (pat, a.tag, b.tag)
                if (a.value, b.value) == (0.0, 0.0): continue
                x, y = fn(a.value, b.value); a.value, b.value = _f32(x), _f32(y)
            bump(".".join(pat))
        if rec.name == "EPISODIC_RESTRICTIONS":  # f32 world rect at leaves 9..12 (-640,-320,640,320)
            r = kids[9:13]; assert all(v.tag == T_F32 for v in r)
            (x0, y0), (x1, y1) = fn(r[0].value, r[1].value), fn(r[2].value, r[3].value)
            r[0].value, r[1].value, r[2].value, r[3].value = (_f32(min(x0, x1)), _f32(min(y0, y1)),
                                                               _f32(max(x0, x1)), _f32(max(y0, y1)))
            bump("EPISODIC_RESTRICTIONS.bounds")
        elif rec.name == "TRADE_ROUTES" and scale != 1.0:   # u32 a, u32 b, u32[] segs, f32 length
            kids[3].value = _f32(kids[3].value * scale); bump("TRADE_ROUTES.len")
        elif rec.name == "PATHFINDING_GRID" and pathfinder:
            _poly_stream(kids[1], fn); bump("PATHFINDING_GRID.polys")
        elif rec.name == "LINE_OF_SIGHT" and los == "strip" and kids and kids[0].value is True:
            kids[:] = [Val(T_BOOL, False)]; bump("LINE_OF_SIGHT.stripped")
            return
        for c in kids:
            if isinstance(c, Rec):
                stack.append(c.name)
                if c.items is None: walk(c, stack, c.children)
                else:
                    for it in c.items: walk(c, stack, it)
                stack.pop()
    root = e.root
    walk(root, [root.name], root.children)
    return cnt


# ---------------------------------------------------------------- startpos visibility grids (QUAD_TREE_BIT_ARRAY)
# LINE_OF_SIGHT and CAMPAIGN_SHROUD bit arrays: u32 W, u32 H, u32 root, NODE.  Cells are 1.25 world units, counted from
# the regions.esf world-box min (x east, y NORTH-UP); vanilla Europe is 1024x512 over 1280x640.  The engine sizes its grid
# from the box, so an enlarged box needs W, H = box / 1.25 or every faction is fully shrouded and characters vanish.
# NODE = 4 child NODEs or a u32 pair.  Child k covers (x half k & 1, y half 1 - (k >> 1)), so the unused half of a 2:1 grid
# (high y) is children 0, 1.  An 8x8 leaf holds bit r*8+c = cell (c, r) of the block (lo = bits 0..31); a bigger leaf
# is uniform, (0, 0) or all ones.
QT_CELL = 1.25
_FULL = 0xFFFFFFFF


def _iter_recs(r, name):
    for kids in ([r.children] if r.items is None else r.items):
        for c in kids:
            if isinstance(c, Rec):
                if c.name == name: yield c
                else: yield from _iter_recs(c, name)


_FIRST = {}


def first_rec(root, name, key=None, pred=None):
    """next(r for r in _iter_recs(root, name) if pred(r)), remembered per (root, name, key): the records a startpos
    edit looks up for every region it adds (REGIONS_ARRAY, PATHFINDING_GRID, a governorship ...) are found once.  The
    answer is stale if the record is replaced in the tree (edits so far only change what is inside it); NTW_CHECK_FIRST=1
    re-scans every call and asserts the same record."""
    ck = (id(root), name, key)
    hit = _FIRST.get(ck)
    if hit is None or hit[0] is not root:
        hit = _FIRST[ck] = (root, next(r for r in _iter_recs(root, name) if pred is None or pred(r)))
    if os.environ.get('NTW_CHECK_FIRST'):
        assert hit[1] is next(r for r in _iter_recs(root, name) if pred is None or pred(r)), (name, key)
    return hit[1]


def all_recs(root, name):
    """list(_iter_recs(root, name)), remembered per (root, name) like first_rec (same staleness rule: the records of that
    name are not added or removed once the tree is being edited; NTW_CHECK_FIRST=1 re-scans every call and asserts)."""
    ck = (id(root), name, '*')
    hit = _FIRST.get(ck)
    if hit is None or hit[0] is not root:
        hit = _FIRST[ck] = (root, list(_iter_recs(root, name)))
    if os.environ.get('NTW_CHECK_FIRST'):
        fresh = list(_iter_recs(root, name))
        assert len(fresh) == len(hit[1]) and all(a is b for a, b in zip(fresh, hit[1])), name
    return hit[1]


def qtba_decode(q):
    """QUAD_TREE_BIT_ARRAY Rec -> (W, H, {(bx, by): (lo, hi)}) for every non-empty 8x8 block (by north-up)."""
    W, H, root = (c.value for c in q.children[:3])
    blocks = {}
    def walk(n, x, y, s):
        v = [c for c in n.children if isinstance(c, Val)]
        if v:
            lo, hi = v[0].value, v[1].value
            if lo or hi:
                for bx in range(x // 8, (x + s) // 8):
                    for by in range(y // 8, (y + s) // 8): blocks[(bx, by)] = (lo, hi)
            return
        h = s // 2
        for k, c in enumerate(n.children): walk(c, x + (k & 1) * h, y + (1 - (k >> 1)) * h, h)
    walk(q.children[3], 0, 0, root)
    return W, H, blocks


def qtba_encode(W, H, blocks, ver=0):
    """Inverse of qtba_decode (root = next power of two >= max(W, H)); collapses uniform squares like vanilla."""
    root = 8
    while root < max(W, H): root *= 2
    def node(x, y, s, ks):
        if s == 8:
            lo, hi = blocks.get((x // 8, y // 8), (0, 0))
            return Rec("QUAD_TREE_BIT_ARRAY_NODE", ver, [Val(T_U32, lo), Val(T_U32, hi)])
        if not ks:                                        # no set block in the square: it collapses to an empty leaf
            return Rec("QUAD_TREE_BIT_ARRAY_NODE", ver, [Val(T_U32, 0), Val(T_U32, 0)])
        h = s // 2
        kids = []
        for k in range(4):
            cx, cy = x + (k & 1) * h, y + (1 - (k >> 1)) * h
            kids.append(node(cx, cy, h, [b for b in ks if cx <= b[0] * 8 < cx + h and cy <= b[1] * 8 < cy + h]))
        leaf = [tuple(c.value for c in k.children) for k in kids if isinstance(k.children[0], Val)]
        if len(leaf) == 4 and len(set(leaf)) == 1 and leaf[0] in ((0, 0), (_FULL, _FULL)):
            return kids[0]
        return Rec("QUAD_TREE_BIT_ARRAY_NODE", ver, kids)
    return Rec(None, 0, [Val(T_U32, W), Val(T_U32, H), Val(T_U32, root), node(0, 0, root, [b for b, v in blocks.items() if v != (0, 0)])])


def regrid_visibility(e, old_min, new_min, new_max):
    """Re-anchor every startpos QUAD_TREE_BIT_ARRAY from a world box with min old_min to [new_min, new_max], in place.
    The old cells move by (old_min - new_min) / 1.25, which must be a multiple of 8 cells (10 units)."""
    dx, dy = ((o - n) / QT_CELL for o, n in zip(old_min, new_min))
    assert dx % 8 == 0 and dy % 8 == 0, (dx, dy)
    W, H = (int(round((b - a) / QT_CELL)) for a, b in zip(new_min, new_max))
    bx0, by0 = int(dx) // 8, int(dy) // 8
    n = 0
    def walk(r):
        nonlocal n
        for kids in ([r.children] if r.items is None else r.items):
            for c in kids:
                if not isinstance(c, Rec): continue
                if c.name == "QUAD_TREE_BIT_ARRAY":
                    _, _, b = qtba_decode(c)
                    new = qtba_encode(W, H, {(x + bx0, y + by0): v for (x, y), v in b.items()}, c.children[3].version)
                    c.children[:] = new.children; n += 1
                else: walk(c)
    walk(e.root)
    return n


# ---------------------------------------------------------------- dispatch / string helpers
def transform_coords(obj, fn, scale=1.0, pathfinder=False, los="keep"):
    """In-place coordinate remap of a loaded Esf (poi / trade_routes / sea_grids / startpos).
    fn(x, y) -> (x, y) in world units; scale multiplies length fields (see module doc).
    startpos only: pathfinder=True also remaps PATHFINDING_GRID obstacle polygons (grid-cell indices
    stay untouched, regenerate them); los='strip' replaces LINE_OF_SIGHT bit arrays by b=False.
    Returns obj (startpos: also sets obj.counts, the per-rule application counts)."""
    n = obj.root.name
    if n == "CAI_POI_ROOT": _transform_poi(obj, fn, scale)
    elif n == "root": _transform_trade(obj, fn, scale)
    elif n == "CAI_SEA_GRID_ROOT": _transform_sea_grid(obj, fn, scale)
    elif n == "CAMPAIGN_STARTPOS": obj.counts = _transform_startpos(obj, fn, scale, pathfinder, los)
    else: raise ValueError(f"unknown ESF root {n}")
    return obj


def translate(dx, dy): return lambda x, y: (x + dx, y + dy)
def scale_about(sx, sy, cx=0.0, cy=0.0): return lambda x, y: (cx + (x - cx) * sx, cy + (y - cy) * sy)


def replace_strings(e, mapping):
    """Exact-match replace of string leaves anywhere in the tree (map keys such as 'nap_europe',
    'campaign_maps/nap_europe', region/slot keys).  Returns number replaced."""
    n = 0
    def walk(kids):
        nonlocal n
        for c in kids:
            if isinstance(c, Val):
                if c.tag in (0x0e, 0x0f) and c.value in mapping: c.value = mapping[c.value]; n += 1
            elif c.items is None: walk(c.children)
            else:
                for it in c.items: walk(it)
    walk(e.root.children)
    return n


def collect_coords(obj, **kw):
    """Identity transform that records every (x, y) it is handed (for diffing / tests)."""
    got = []
    transform_coords(obj, lambda x, y: (got.append((x, y)) or (x, y)), **kw)
    return got


# ---------------------------------------------------------------- self-check
def _selfcheck(quick=False):
    import time
    root = os.path.expanduser("~/.local/share/Steam/steamapps/common/Napoleon Total War/data/")
    maps = ["nap_europe", "nap_egypt", "nap_italy", "nap_spain", "nap_tut"]
    T = translate(37.5, -12.25); Ti = translate(-37.5, 12.25)
    def raw(p):
        with open(p, "rb") as f: return f.read()
    def near(a, b, tol=2e-3):
        assert len(a) == len(b) and (not a or np.abs(np.array(a) - np.array(b)).max() <= tol)
    for m in maps:
        d = root + "campaign_maps/" + m + "/"
        # poi
        b = raw(d + "poi.esf"); e = esf.loads(b); p = read_poi(e)
        assert esf.dumps(write_poi(p)) == b, (m, "poi roundtrip")
        e = esf.loads(b); transform_coords(e, lambda x, y: (x, y)); assert esf.dumps(e) == b, (m, "poi identity")
        e = esf.loads(b); transform_coords(e, T); assert esf.dumps(e) != b
        n0 = read_poi(e).nodes[3]; assert abs(n0.wx - (p.nodes[3].wx + 37.5)) < 1e-9
        transform_coords(e, Ti); assert esf.dumps(e) == b, (m, "poi translate-inverse")
        e = esf.loads(b); transform_coords(e, scale_about(2, 2), scale=2.0); transform_coords(e, scale_about(.5, .5), scale=.5)
        assert esf.dumps(e) == b, (m, "poi scale-inverse")   # power-of-two scale: exact
        # trade routes
        b = raw(d + "trade_routes.esf"); e = esf.loads(b); t = read_trade_routes(e)
        assert esf.dumps(write_trade_routes(t)) == b, (m, "trade roundtrip")
        e = esf.loads(b); transform_coords(e, lambda x, y: (x, y)); assert esf.dumps(e) == b
        c0 = collect_coords(esf.loads(b)); e = esf.loads(b); transform_coords(e, T)
        near([(x - 37.5, y + 12.25) for x, y in collect_coords(e)], c0)
        transform_coords(e, Ti); near(collect_coords(e), c0)
        # sea grids
        b = raw(d + "sea_grids.esf"); e = esf.loads(b); g = read_sea_grids(e)
        assert esf.dumps(write_sea_grids(g)) == b, (m, "sea roundtrip")
        assert (g.cols, g.rows) == sea_grid_dims(g.bmin, g.bmax, g.cell), m
        assert g.cells == make_sea_grid_cells(g.bmin, g.bmax, g.cell)[2], m
        e = esf.loads(b); transform_coords(e, lambda x, y: (x, y)); assert esf.dumps(e) == b
        transform_coords(e, T); transform_coords(e, Ti); assert esf.dumps(e) == b, (m, "sea translate-inverse")
        e = esf.loads(b); transform_coords(e, scale_about(2, 2), scale=2.0)
        g2 = read_sea_grids(e); assert g2.cell == 2 * g.cell and g2.bmax == (g.bmax[0] * 2, g.bmax[1] * 2)
        # metadata
        mp = d + "metadata.dat"
        if os.path.exists(mp):
            b = raw(mp); mt = read_metadata(b); assert write_metadata(mt) == b, (m, "meta roundtrip")
    # europe metadata affine sanity: all kind-6 POI nodes mostly on sea, land nodes mostly not
    mt = read_metadata(root + "campaign_maps/nap_europe/metadata.dat")
    pn = read_poi(esf.load(root + "campaign_maps/nap_europe/poi.esf")).nodes
    def on_sea(n):
        c, r = meta_px(n.wx, n.wy); c, r = int(round(c)), int(round(r))
        return 0 <= c < mt.w and 0 <= r < mt.h and mt.data[r, c] == 6
    sea = [on_sea(n) for n in pn if n.kind == 6]; land = [on_sea(n) for n in pn if 1 <= n.kind <= 5]
    agree = (np.mean(sea) + 1 - np.mean(land)) / 2
    assert agree > 0.99, agree
    print(f"campaign_maps x5: poi/trade_routes/sea_grids/metadata round-trip, identity, translate-inverse OK; "
          f"europe metadata affine agreement {agree:.4f}")
    if quick: return
    for camp in ["mp_eur_napoleon", "tut_napoleon", "egy_napoleon"]:
        t0 = time.time(); b = raw(root + f"campaigns/{camp}/startpos.esf"); e = esf.loads(b)
        assert esf.dumps(e) == b, (camp, "startpos roundtrip")
        c0 = collect_coords(e, pathfinder=True)
        assert esf.dumps(e) == b, (camp, "startpos identity")
        transform_coords(e, T, pathfinder=True); cnt = e.counts
        near([(x - 37.5, y + 12.25) for x, y in collect_coords(e, pathfinder=True)], c0)
        transform_coords(e, Ti, pathfinder=True); c1 = collect_coords(e, pathfinder=True)
        near(c1, c0)   # f32 xy fields drift <= 1 ulp when a translate changes binade; fixed-point fields are exact
        drift = max(abs(a - c) for p, q in zip(c0, c1) for a, c in zip(p, q))
        print(f"{camp}: startpos round-trip + identity byte-exact, translate-inverse max drift {drift:.2e}; {len(c0)} coordinate pairs; "
              f"{sum(cnt.values())} field applications in {len(cnt)} rules ({time.time() - t0:.0f}s)")
        if camp == "mp_eur_napoleon":
            print({k.replace("CAI_", "")[-36:]: v for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])[:14]})
            assert cnt["REGION.SETTLEMENT.SIEGEABLE_GARRISON_RESIDENCE"] == 72
            assert cnt["PATHFINDING_GRID.polys"] == 1
            e2 = esf.loads(b); n = replace_strings(e2, {"europe_main": "world_main", "nap_europe": "nap_world", "campaign_maps/nap_europe": "campaign_maps/nap_world"})
            assert n >= 2, n   # 'europe_main' x2 always; nap_europe x3 only in files not already retargeted
            e2 = esf.loads(b); transform_coords(e2, T, los="strip"); assert len(esf.dumps(e2)) < len(b)
            # visibility quadtrees: decode/encode byte-exact; regrid into a 2x box and back is the identity
            e2 = esf.loads(b); assert regrid_visibility(e2, (-640, -320), (-640, -320), (640, 320)) == 923
            assert esf.dumps(e2) == b, "qtba roundtrip"
            regrid_visibility(e2, (-640, -320), (-1280, -640), (1280, 640)); assert esf.dumps(e2) != b
            regrid_visibility(e2, (-1280, -640), (-640, -320), (640, 320)); assert esf.dumps(e2) == b, "qtba regrid inverse"
            # the bits sit inside each LINE_OF_SIGHT's stored bounds (cells north-up from the box min)
            for r in [r for r in _iter_recs(e2.root, "LINE_OF_SIGHT") if r.children[0].value is True][:200]:
                (x0, y0), (x1, y1) = r.children[1].value, r.children[2].value
                _, _, bl = qtba_decode(r.children[3]); cells = []
                for (bx, by), (lo, hi) in bl.items():
                    bits = lo | hi << 32
                    cells += [(bx * 8 + i % 8, by * 8 + i // 8) for i in range(64) if bits >> i & 1]
                if cells:
                    c = np.array(cells)
                    assert c[:, 0].min() >= (x0 + 640) / QT_CELL - 1 and c[:, 0].max() < (x1 + 640) / QT_CELL + 1
                    assert c[:, 1].min() >= (y0 + 320) / QT_CELL - 1 and c[:, 1].max() < (y1 + 320) / QT_CELL + 1
    print("campaign_misc self-check OK")


if __name__ == "__main__":
    _selfcheck(quick="--quick" in sys.argv)
