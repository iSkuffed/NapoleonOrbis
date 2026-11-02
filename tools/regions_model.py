#!/usr/bin/env python3
"""Semantic model + rebuilders for NTW campaign-map regions.esf (spec: research/05-regions-esf.md).

Area code used everywhere in the file: (region_index << 16) | area_index.
Vertex pool: region_data/vertices xy[], float32. Outlines are rings of pool indices
(outer ring CCW, holes CW); faces are CW triangles of pool indices.

    python tools/regions_model.py            # self-check on all vanilla maps (read-only)
"""
import math
import os
import struct
import sys
from collections import defaultdict

import numpy as np
import shapely

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esf  # noqa: E402
from esf import Rec, Val  # noqa: E402

NONE = 0xFFFFFFFF          # connectivity code for an edge with no neighbour (world border)
MAX_LEAF_EDGES = 50        # quadtree: split while a node holds more edges than this
SHIFT_EPS2 = 1e-5          # quadtree: sample point moved if (line distance)^2 < this
CHILDREN = ("bottom_left", "top_left", "bottom_right", "top_right")
_DT = {"u8": "<u1", "i8": "<i1", "u16": "<u2", "u32": "<u4", "i32": "<i4", "f32": "<f4",
       "xy": "<f4", "xyz": "<f4"}


# ---------------------------------------------------------------- raw helpers
def nparr(v):
    """Array Val -> numpy (xy -> (n,2), xyz -> (n,3))."""
    name = esf.SCALAR[v.tag & 0x3f][0]
    a = np.frombuffer(v.value, _DT[name])
    return a.reshape(-1, 2) if name == "xy" else a.reshape(-1, 3) if name == "xyz" else a


def mkarr(tag, a):
    return Val(tag, np.ascontiguousarray(a, _DT[esf.SCALAR[tag & 0x3f][0]]).tobytes())


def vals(lst):
    return [c for c in lst if isinstance(c, Val)]


def sub(lst, name):
    return next((c for c in lst if isinstance(c, Rec) and c.name == name), None)


def f2(p):
    return tuple(float(x) for x in p)


# Area item layout (record-array entry of <areas>), by child index:
#   0 bool crossing   1 bool unknown(always False)   2 bool passable
#   3 xy bounds_min   4 xy bounds_max   5 u16 pass_group
#   6 <faces> (absent in groundtypes)   then <outlines>   then u16 nonwalk_group, u16 landmass
def area_fields(ar):
    v = vals(ar)
    return dict(crossing=v[0].value, flag_b=v[1].value, passable=v[2].value,
                bmin=v[3].value, bmax=v[4].value, pass_group=v[5].value,
                nonwalk_group=v[6].value, landmass=v[7].value)


def iter_areas(rd):
    for ri, it in enumerate(sub(rd.children, "regions").items):
        for ai, ar in enumerate(sub(it, "areas").items):
            yield ri, ai, it, ar


def verts(rd):
    return nparr(sub(rd.children, "vertices").children[0])


def rings(ar):
    """[(is_outer, idx ndarray, outline item)] of one area."""
    return [(ol[0].value, nparr(ol[3]).astype(np.int64), ol) for ol in sub(ar, "outlines").items]


# ---------------------------------------------------------------- semantic model
def extract(e):
    """Semantic model of the whole file (plain python / numpy)."""
    r = e.root
    rd = r.find("region_data")
    V = verts(rd)
    th = r.find("theatres").items[0][0]
    cms = th.findall("climate_map")
    wm = th.find("wind_map")
    regions = []
    for it in rd.find("regions").items:
        v = vals(it)
        ss = sub(it, "settlement_and_slots")
        areas = []
        for ar in sub(it, "areas").items:
            a = area_fields(ar)
            a["rings"] = [(o, idx) for o, idx, _ in rings(ar)]
            fc = sub(ar, "faces")
            a["faces"] = nparr(fc.children[0]).reshape(-1, 3) if fc else None
            areas.append(a)
        reg = dict(name=v[0].value, kind=v[1].value, bmin=v[2].value, bmax=v[3].value,
                   theatre=v[4].value, areas=areas, settlement=None)
        if ss is not None:
            reg["settlement"] = dict(
                pos=ss.children[0].value, footprint=nparr(ss.children[1]),
                slots=[dict(key=s[0].value, type=s[1].value, pos3=s[2].value, pos=s[3].value,
                            angle=s[4].value * 2 * math.pi / 65536, is_settlement_part=s[5].value,
                            model=s[6].value, land_poly=nparr(s[7]), sea_poly=nparr(s[8]),
                            outline=nparr(s[9]))
                       for s in ss.find("slot_descriptions").items])
        regions.append(reg)

    def grid(cm):
        w, h = cm.children[0].value, cm.children[1].value
        return nparr(cm.children[2]).reshape(h, w)          # row 0 = south

    ci = r.find("climate_indices")
    wv = nparr(wm.children[3]).reshape(wm.children[1].value, wm.children[0].value, 2)
    return dict(
        world=(rd.children[1].value, rd.children[2].value), vertices=V, regions=regions,
        theatre=dict(key=th.children[0].value, bmin=th.children[1].value, bmax=th.children[2].value,
                     land_climate=grid(cms[0]), sea_climate=grid(cms[1]),
                     wind=wv.astype(np.float32) * wm.children[2].value),
        land_climates={x[0].value: x[1].value for x in ci.find("land_indices").items},
        sea_climates={x[0].value: x[1].value for x in ci.find("sea_indices").items},
        mountains=[nparr(o[0]) for o in r.find("mountain_data").find("MOUNTAIN_OUTLINES").find("OUTLINE_BLOCK").items],
        trade_nodes=[(t[0].value, t[1].value) for t in r.find("trade_nodes").find("trade_nodes").items],
        bridges=nparr(r.find("bridges").children[0]),            # (x, y, rotation radians)
        groundtypes=[t[0].value for t in r.find("groundtypes").find("groundtype_indices_list").find("groundtype_index").items],
        adjacency=adjacency(rd),
    )


def edge_owner(rd):
    """directed edge (a, b) -> area code owning it (area interior on the left)."""
    own = {}
    for ri, ai, _, ar in iter_areas(rd):
        code = ri << 16 | ai
        for ol in sub(ar, "outlines").items:
            l = nparr(ol[3]).tolist()
            own.update(dict.fromkeys(zip(l, l[1:] + l[:1]), code))
    return own


def adjacency(rd):
    """{region_index: set(neighbour region indices)} from the connectivity runs."""
    adj = defaultdict(set)
    for ri, ai, _, ar in iter_areas(rd):
        for _, _, ol in rings(ar):
            for c in sub(ol, "connectivity").items:
                if c[0].value != NONE and c[0].value >> 16 != ri:
                    adj[ri].add(c[0].value >> 16)
    return dict(adj)


def area_polygons(rd):
    V = verts(rd).astype(np.float64)
    out = {}
    for ri, ai, _, ar in iter_areas(rd):
        out[ri << 16 | ai] = _area_polygon(V, ar, ri, ai)
    return out


def _area_polygon(V, ar, ri, ai):
    rs = rings(ar)
    shell = [V[i] for o, i, _ in rs if o]
    assert len(shell) == 1, (ri, ai)
    return shapely.Polygon(shell[0], [V[i] for o, i, _ in rs if not o])


def area_polygon(rd, ri, ai):
    """area_polygons(rd)[ri << 16 | ai] without the other areas."""
    return _area_polygon(verts(rd).astype(np.float64), sub(sub(rd.children, "regions").items[ri], "areas").items[ai], ri, ai)


# ---------------------------------------------------------------- derived: bounds + connectivity
def rebuild_bounds(rd):
    """Recompute outline/area/region/world bounds from the vertex pool (exact in vanilla)."""
    V = verts(rd)
    for it in sub(rd.children, "regions").items:
        rp = []
        for ar in sub(it, "areas").items:
            ap = []
            for _, idx, ol in rings(ar):
                p = V[idx]; ap.append(p)
                ol[1], ol[2] = Val(0x0c, f2(p.min(0))), Val(0x0c, f2(p.max(0)))
            p = np.concatenate(ap); rp.append(p)
            ar[3], ar[4] = Val(0x0c, f2(p.min(0))), Val(0x0c, f2(p.max(0)))
        p = np.concatenate(rp)
        it[2], it[3] = Val(0x0c, f2(p.min(0))), Val(0x0c, f2(p.max(0)))
    rd.children[1], rd.children[2] = Val(0x0c, f2(V.min(0))), Val(0x0c, f2(V.max(0)))


def rebuild_connectivity(rd):
    """Connectivity = runs of outline edges with the same neighbour (owner of the twin edge)."""
    own = edge_owner(rd)
    for _, _, _, ar in iter_areas(rd):
        for _, idx, ol in rings(ar):
            runs = []
            for k, (a, b) in enumerate(zip(idx.tolist(), np.roll(idx, -1).tolist())):
                c = own.get((b, a), NONE)
                if runs and runs[-1][0] == c:
                    runs[-1][2] = k
                else:
                    runs.append([c, k, k])
            sub(ol, "connectivity").items = [[Val(0x08, c), Val(0x08, s), Val(0x08, t)] for c, s, t in runs]


# ---------------------------------------------------------------- derived: area ids
def _components(n, pairs):
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for i, j in pairs:
        parent[find(i)] = find(j)
    return [find(i) for i in range(n)]


def derive_area_groups(rd, kinds):
    """Partitions behind the 3 area ids, from topology + flags only.
    Returns per-area component labels (lists aligned with iter_areas order):
      pass_group     passable areas joined across shared edges (same kind) and across
                     'crossing' sea areas (all passable land touching one crossing is merged)
      nonwalk_group  everything that is not passable land, joined across shared edges
      landmass       land+river areas joined across shared edges (sea excluded)
      face_group     areas of the same region joined across shared edges; every vanilla <faces>
                     blob lies inside one such component, but some components hold >1 blob"""
    items = list(iter_areas(rd))
    index = {ri << 16 | ai: k for k, (ri, ai, _, _) in enumerate(items)}
    F = [area_fields(ar) for _, _, _, ar in items]
    K = [kinds[ri] for ri, _, _, _ in items]
    nb = [set() for _ in items]
    for k, (_, _, _, ar) in enumerate(items):
        for _, _, ol in rings(ar):
            for c in sub(ol, "connectivity").items:
                if c[0].value in index:
                    nb[k].add(index[c[0].value])
    walk = [K[k] == "land" and F[k]["passable"] for k in range(len(items))]
    e_pass = [(i, j) for i in range(len(items)) for j in nb[i]
              if F[i]["passable"] and F[j]["passable"] and K[i] == K[j]]
    for i in range(len(items)):
        if F[i]["crossing"]:
            land = [j for j in nb[i] if walk[j]]
            e_pass += list(zip(land, land[1:]))
    return dict(
        pass_group=_components(len(items), e_pass),
        nonwalk_group=_components(len(items), [(i, j) for i in range(len(items)) for j in nb[i]
                                               if not walk[i] and not walk[j]]),
        landmass=_components(len(items), [(i, j) for i in range(len(items)) for j in nb[i]
                                          if K[i] != "sea" and K[j] != "sea"]),
        face_group=_components(len(items), [(i, j) for i in range(len(items)) for j in nb[i]
                                            if items[i][0] == items[j][0]]),
    ), items, F


def same_partition(labels, ids, mask):
    a, b = defaultdict(set), defaultdict(set)
    for lab, i, m in zip(labels, ids, mask):
        if m:
            a[lab].add(i); b[i].add(lab)
    return all(len(s) == 1 for s in a.values()) and all(len(s) == 1 for s in b.values())


# ---------------------------------------------------------------- derived: faces
def triangulate(V, area_rings):
    """CW triangles (pool indices) covering the union of a face group, given per area its rings
    [(is_outer, idx)], via shapely constrained Delaunay (no Steiner points)."""
    Vd = V.astype(np.float64)
    look = {tuple(Vd[i]): i for rl in area_rings for _, idx in rl for i in idx.tolist()}
    geom = shapely.union_all([shapely.Polygon(Vd[next(i for o, i in rl if o)], [Vd[i] for o, i in rl if not o])
                              for rl in area_rings])
    tris = []
    for t in shapely.get_parts(shapely.constrained_delaunay_triangles(geom)):
        c = shapely.get_coordinates(t)[:3]
        tri = [look[tuple(p)] for p in c]
        x = Vd[tri]
        if (x[1, 0] - x[0, 0]) * (x[2, 1] - x[0, 1]) - (x[2, 0] - x[0, 0]) * (x[1, 1] - x[0, 1]) > 0:
            tri = tri[::-1]                                   # vanilla faces are clockwise
        tris.append(tri)
    return np.array(tris, np.uint32)


def tri_signed_area(V, T):
    a, b, c = (V[T[:, k]].astype(np.float64) for k in range(3))
    return 0.5 * ((b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (b[:, 1] - a[:, 1]))


# ---------------------------------------------------------------- derived: quadtree
def _edges(rd):
    own = edge_owner(rd)
    und, seen = [], set()
    for (a, b) in own:
        k = (min(a, b), max(a, b))
        if k not in seen:
            seen.add(k); und.append(k)
    return np.array(und, np.int64), own


def build_query_info(rd, left_codes=True, max_edges=MAX_LEAF_EDGES):
    """Rebuild <query_info> (point -> area quadtree) from region_data.

    Node = bounds + 4 children (BL, TL, BR, TR) or one <cell>. Split while the node holds more
    than 50 edges; an edge belongs to a node if it meets the box interior (touching only the box
    border does not count). Cell = sample point (min corner, or left-edge midpoint if the corner
    is within sqrt(1e-5) of an edge line), area code at that point, and u32 4-tuples
    (v0, v1, right_area, left_area) oriented so the sample point is LEFT of v0->v1.
    The groundtypes copy stores NONE instead of left_area (left_codes=False).
    Header = (node count, leaf count). Edge order inside a cell is ours (vanilla's is not
    reproducible, see spec)."""
    V = verts(rd).astype(np.float64)
    und, own = _edges(rd)
    P0, P1 = V[und[:, 0]], V[und[:, 1]]
    segs = shapely.linestrings(np.stack([P0, P1], 1))
    polys = area_polygons(rd)
    codes = list(polys)
    tree = shapely.STRtree([polys[c] for c in codes])
    counts = [0, 0]

    def area_at(p):
        hit = tree.query(shapely.Point(p), predicate="intersects")
        if len(hit) > 1:
            inside = tree.query(shapely.Point(p), predicate="within")
            hit = inside if len(inside) else hit
        return codes[int(min(hit))]

    def cross(S, e):
        d = P1[e] - P0[e]
        return d[:, 0] * (S[1] - P0[e, 1]) - d[:, 1] * (S[0] - P0[e, 0]), d

    def node(lo, hi, cand):
        counts[0] += 1
        box = shapely.box(lo[0], lo[1], hi[0], hi[1])
        s = segs[cand]
        sel = cand[shapely.intersects(s, box) & ~shapely.touches(s, box)]
        kids = [Val(0x0c, f2(lo)), Val(0x0c, f2(hi))]
        if len(sel) > max_edges:
            mx, my = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
            for name, (a, b) in zip(CHILDREN, (((lo[0], lo[1]), (mx, my)), ((lo[0], my), (mx, hi[1])),
                                              ((mx, lo[1]), (hi[0], my)), ((mx, my), (hi[0], hi[1])))):
                kids.append(Rec(name, 0, node(a, b, sel)))
            return kids
        counts[1] += 1
        S = np.array(lo, np.float64)
        for cand_pt in (lo, (lo[0], (lo[1] + hi[1]) / 2), ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)):
            S = np.array(cand_pt, np.float64)
            if not len(sel):
                break
            c, d = cross(S, sel)
            if (c * c / (d * d).sum(1)).min() >= SHIFT_EPS2:
                break
        c, _ = cross(S, sel)
        q = np.empty((len(sel), 4), np.uint32)
        for k, (e, cr) in enumerate(zip(sel.tolist(), c.tolist())):
            a, b = int(und[e, 0]), int(und[e, 1])
            if cr < 0:
                a, b = b, a
            q[k] = (a, b, own.get((b, a), NONE), own.get((a, b), NONE) if left_codes else NONE)
        kids.append(Rec("cell", 0, [Val(0x0c, f2(S)), Val(0x08, area_at(S)), mkarr(0x48, q.ravel())]))
        return kids

    lo, hi = rd.children[1].value, rd.children[2].value
    root = Rec("node", 0, node(lo, hi, np.arange(len(und))))
    return Rec("query_info", 0, [Val(0x08, counts[0]), Val(0x08, counts[1]), root])


def leaves(qi):
    out = []

    def walk(n):
        k = [c for c in n.children if isinstance(c, Rec)]
        if k[0].name == "cell":
            c = k[0]
            out.append((n.children[0].value, n.children[1].value, c.children[0].value, c.children[1].value,
                        nparr(c.children[2]).reshape(-1, 4)))
        else:
            assert [x.name for x in k] == list(CHILDREN)
            for x in k:
                walk(x)
    walk(qi.find("node"))
    return out


def compare_query_info(a, b):
    """Semantic diff of two <query_info> records."""
    la, lb = leaves(a), leaves(b)
    r = dict(header=[v.value for v in vals(a.children)] == [v.value for v in vals(b.children)],
             leaves=(len(la), len(lb)), bounds=0, sample=0, code=0, edge_set=0, edge_order=0)
    if len(la) != len(lb):
        return r
    for x, y in zip(la, lb):
        r["bounds"] += x[:2] == y[:2]
        r["sample"] += x[2] == y[2]
        r["code"] += x[3] == y[3]
        r["edge_set"] += sorted(map(tuple, x[4].tolist())) == sorted(map(tuple, y[4].tolist()))
        r["edge_order"] += np.array_equal(x[4], y[4])
    return r


def query_point(qi, V, p):
    """Engine-style lookup: area code at p using only the quadtree (our reading of it):
    leaf code if S->p crosses no edge, else right_area of the crossed edge nearest p."""
    n = qi.find("node")
    while True:
        k = [c for c in n.children if isinstance(c, Rec)]
        if k[0].name == "cell":
            break
        lo, hi = n.children[0].value, n.children[1].value
        mx, my = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        n = k[(2 if p[0] >= mx else 0) + (1 if p[1] >= my else 0)]
    c = k[0]
    S, code = np.array(c.children[0].value), c.children[1].value
    q = nparr(c.children[2]).reshape(-1, 4)
    best = None
    for a, b, right, left in q.tolist():
        A, B = V[a].astype(np.float64), V[b].astype(np.float64)
        d, e = B - A, p - S
        den = e[0] * d[1] - e[1] * d[0]
        if den == 0:
            continue
        t = ((A[0] - S[0]) * d[1] - (A[1] - S[1]) * d[0]) / den   # along S->p
        u = ((A[0] - S[0]) * e[1] - (A[1] - S[1]) * e[0]) / den   # along A->B
        if 0 <= t <= 1 and 0 <= u <= 1 and (best is None or t > best[0]):
            best = (t, right)   # S is left of every edge line, so p is right of the last edge crossed
    return code if best is None else best[1]


# ---------------------------------------------------------------- resize
def _resize_rd(rd, new_min, new_max):
    lo, hi = rd.children[1].value, rd.children[2].value
    V = verts(rd).copy()
    moved = np.zeros(len(V), bool)
    for ax, old, new in ((0, lo[0], new_min[0]), (0, hi[0], new_max[0]), (1, lo[1], new_min[1]), (1, hi[1], new_max[1])):
        m = V[:, ax] == np.float32(old)
        V[m, ax] = new; moved |= m
    sub(rd.children, "vertices").children[0] = mkarr(0x4c, V)
    touched = set(np.nonzero(moved)[0].tolist())
    for it in sub(rd.children, "regions").items:
        done = {}
        for ar in sub(it, "areas").items:
            fc = sub(ar, "faces")
            if fc is None:
                continue
            raw = fc.children[0].value
            if raw in done:
                fc.children[0] = done[raw]; continue
            T = np.frombuffer(raw, "<u4").reshape(-1, 3)
            if touched.isdisjoint(T.ravel().tolist()) or (tri_signed_area(V, T) < 0).all():
                done[raw] = fc.children[0]; continue
            group = [a for a in sub(it, "areas").items if sub(a, "faces").children[0].value == raw]
            rl = [[(o, i) for o, i, _ in rings(a)] for a in group]
            done[raw] = fc.children[0] = mkarr(0x48, triangulate(V, rl).ravel())
    rebuild_bounds(rd)
    rd.children[1], rd.children[2] = Val(0x0c, f2(new_min)), Val(0x0c, f2(new_max))
    return int(moved.sum())


def move_vertices(rd, moves):
    """Move pool vertices {index: (x, y)} in place (every ring sharing them follows), re-triangulate each face
    group that uses a moved vertex, rebuild bounds. Caller keeps rings simple and rebuilds query_info."""
    V = verts(rd).copy()
    for i, p in moves.items():
        V[i] = p
    sub(rd.children, "vertices").children[0] = mkarr(0x4c, V)
    touched = set(moves)
    for it in sub(rd.children, "regions").items:
        done = {}
        for ar in sub(it, "areas").items:
            fc = sub(ar, "faces")
            if fc is None:
                continue
            raw = fc.children[0].value
            if raw in done:
                fc.children[0] = done[raw]; continue
            if touched.isdisjoint(np.frombuffer(raw, "<u4").tolist()):
                done[raw] = fc.children[0]; continue
            group = [a for a in sub(it, "areas").items if sub(a, "faces").children[0].value == raw]
            done[raw] = fc.children[0] = mkarr(0x48, triangulate(V, [[(o, i) for o, i, _ in rings(a)] for a in group]).ravel())
    rebuild_bounds(rd)


def resize_world(e, new_min, new_max):
    """Embed the map in a larger world box, in place: every vertex lying on the old world border
    (only the outer filler areas own them) is pushed onto the new border, bounds recomputed,
    face groups re-triangulated if any triangle would flip, both quadtrees rebuilt.
    Theatre, climate/wind maps and everything inside the theatre stay untouched."""
    r = e.root
    lo, hi = r.find("region_data").children[1].value, r.find("region_data").children[2].value
    assert new_min[0] <= lo[0] and new_min[1] <= lo[1] and new_max[0] >= hi[0] and new_max[1] >= hi[1]
    moved = 0
    for owner in (r, r.find("groundtypes")):
        rd = owner.find("region_data")
        moved += _resize_rd(rd, new_min, new_max)
        owner.children[owner.children.index(owner.find("query_info"))] = build_query_info(rd, owner is r)
    return moved


# ---------------------------------------------------------------- self-check
def _check_map(path, name):
    raw = open(path, "rb").read()
    e = esf.loads(raw)
    assert esf.dumps(e) == raw
    r = e.root
    print(f"== {name}")
    for label, owner in (("regions", r), ("groundtypes", r.find("groundtypes"))):
        rd = owner.find("region_data")
        V = verts(rd)
        kinds = [it[1].value for it in rd.find("regions").items]
        # bounds + connectivity are exactly derivable
        before = esf.dumps(e)
        rebuild_bounds(rd); rebuild_connectivity(rd)
        assert esf.dumps(e) == before, "bounds/connectivity rebuild changed bytes"
        # areas tile the world box
        polys = area_polygons(rd)
        lo, hi = rd.children[1].value, rd.children[2].value
        tot = sum(p.area for p in polys.values())
        assert all(p.is_valid for p in polys.values())
        assert abs(tot - (hi[0] - lo[0]) * (hi[1] - lo[1])) < 1e-3 * tot
        # face groups: CW triangles covering exactly the areas that share the blob
        groups, items, F = derive_area_groups(rd, kinds)
        nf = 0
        if label == "regions":
            blobs = [sub(ar, "faces").children[0].value for _, _, _, ar in items]
            # each <faces> blob lies inside one same-region connected component (the exact split
            # is authored: vanilla sometimes splits a component into several blobs)
            comp_of = defaultdict(set)
            for lab, bl in zip(groups["face_group"], blobs):
                comp_of[bl].add(lab)
            assert all(len(v) == 1 for v in comp_of.values())
            seen = set()
            for k, (ri, ai, it, ar) in enumerate(items):
                if blobs[k] in seen:
                    continue
                seen.add(blobs[k]); nf += 1
                T = np.frombuffer(blobs[k], "<u4").reshape(-1, 3)
                ta = tri_signed_area(V, T)
                pa = sum(polys[ri << 16 | j].area for j, b in enumerate(sub(it, "areas").items)
                         if sub(b, "faces").children[0].value == blobs[k])
                assert (ta < 0).all() and abs(-ta.sum() - pa) < 1e-3 * max(pa, 1)
            # area ids are labelled partitions
            ids = {f: [x[f] for x in F] for f in ("pass_group", "nonwalk_group", "landmass")}
            walk = [kinds[it[0]] == "land" and x["passable"] for it, x in zip(items, F)]
            assert same_partition(groups["nonwalk_group"], ids["nonwalk_group"], [not w for w in walk])
            assert all(x["nonwalk_group"] == 0xFFFF for x, w in zip(F, walk) if w)
            assert same_partition(groups["landmass"], ids["landmass"], [kinds[it[0]] != "sea" for it in items])
            assert same_partition(groups["pass_group"], ids["pass_group"], [x["passable"] for x in F])
            npass = len({x["pass_group"] for x in F if x["passable"]})
            imp = [x["pass_group"] for x in F if not x["passable"]]
            assert imp == list(range(npass, npass + len(imp))), "impassable ids are sequential in file order"
            assert not any(x["flag_b"] for x in F)
            # trivial region-level facts
            keys = {k[0].value: k[1].value for k in r.find("theatres_and_region_keys").items[0][0].find("region_keys").items}
            for it in rd.find("regions").items:
                ss = sub(it, "settlement_and_slots")
                assert (vals(it)[4].value == 0) == (ss is not None) == (it[0].value in keys)
                if ss is not None:
                    assert keys[it[0].value] == ss.children[0].value
        else:
            assert all(x["pass_group"] == x["nonwalk_group"] == x["landmass"] == 0xFFFF for x in F)
            names = [t[0].value for t in owner.find("groundtype_indices_list").find("groundtype_index").items]
            assert names == [it[0].value for it in rd.find("regions").items]
        # quadtree
        qi = owner.find("query_info")
        hdr = [v.value for v in vals(qi.children)]
        assert hdr[1] == (3 * hdr[0] + 1) // 4
        mine = build_query_info(rd, label == "regions")
        cmp = compare_query_info(qi, mine)
        n = cmp["leaves"][0]
        assert cmp["header"] and cmp["leaves"][0] == cmp["leaves"][1]
        assert cmp["bounds"] == cmp["sample"] == cmp["code"] == cmp["edge_set"] == n, cmp
        size_same = len(esf.dumps(esf.Esf(qi))) == len(esf.dumps(esf.Esf(mine)))
        assert size_same
        # engine-style point lookups agree with polygon containment (vanilla + rebuilt tree)
        rng = np.random.default_rng(1)
        pts = rng.uniform(lo, hi, (300, 2))
        codes = list(polys)
        tree = shapely.STRtree([polys[c] for c in codes])
        for p in pts:
            hit = [codes[i] for i in tree.query(shapely.Point(p), predicate="within")]
            if len(hit) == 1:
                assert query_point(qi, V, p) == hit[0] == query_point(mine, V, p)
        print(f"  {label:11s} regions={len(kinds):3d} areas={len(items):4d} face_groups={nf:4d} "
              f"bounds+connectivity rebuild byte-exact; quadtree header={hdr} "
              f"leaves={n} structure/sample/code/edge-set equal={cmp['edge_set']}/{n} "
              f"edge-order equal={cmp['edge_order']}/{n} same byte size={size_same}")
    # crossings that merge passable groups
    rd = r.find("region_data")
    names = [it[0].value for it in rd.find("regions").items]
    cr = [f"{names[ri]}#{ai}" for ri, ai, _, ar in iter_areas(rd) if area_fields(ar)["crossing"]]
    print(f"  crossing sea areas: {cr}")
    return e


def _check_resize(path, name):
    e = esf.load(path)
    lo, hi = e.root.find("region_data").children[1].value, e.root.find("region_data").children[2].value
    new_min, new_max = (lo[0] * 2, lo[1] * 2), (hi[0] * 2, hi[1] * 2)
    moved = resize_world(e, new_min, new_max)
    raw = esf.dumps(e)
    e2 = esf.loads(raw)
    assert esf.dumps(e2) == raw
    for owner in (e2.root, e2.root.find("groundtypes")):
        rd = owner.find("region_data")
        polys = area_polygons(rd)
        assert all(p.is_valid for p in polys.values())
        tot = sum(p.area for p in polys.values())
        want = (new_max[0] - new_min[0]) * (new_max[1] - new_min[1])
        assert abs(tot - want) < 1e-3 * want and rd.children[1].value == new_min
        V = verts(rd)
        for it in rd.find("regions").items:
            for ar in sub(it, "areas").items:
                fc = sub(ar, "faces")
                if fc is not None:
                    assert (tri_signed_area(V, nparr(fc.children[0]).reshape(-1, 3)) < 0).all()
        qi = owner.find("query_info")
        codes = list(polys)
        tree = shapely.STRtree([polys[c] for c in codes])
        for p in np.random.default_rng(2).uniform(new_min, new_max, (300, 2)):
            hit = [codes[i] for i in tree.query(shapely.Point(p), predicate="within")]
            if len(hit) == 1:
                assert query_point(qi, V, p) == hit[0]
    out = os.path.join(os.path.dirname(__file__), "..", "work", "scratch_regions", f"{name}_resized_regions.esf")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "wb").write(raw)
    print(f"  resize {lo}..{hi} -> {new_min}..{new_max}: moved {moved} border vertices, "
          f"{len(raw)} bytes, valid; wrote {os.path.normpath(out)}")


if __name__ == "__main__":
    G = os.path.expanduser("~/.local/share/Steam/steamapps/common/Napoleon Total War/data/campaign_maps")
    maps = sys.argv[1:] or ["nap_europe", "nap_egypt", "nap_italy", "nap_spain", "nap_tut"]
    for m in maps:
        p = f"{G}/{m}/regions.esf"
        _check_map(p, m)
        if m in ("nap_europe", "nap_egypt"):
            _check_resize(p, m)
    model = extract(esf.load(f"{G}/{maps[0]}/regions.esf"))
    print(f"extract({maps[0]}): {len(model['regions'])} regions, {len(model['vertices'])} vertices, "
          f"{sum(len(v) for v in model['adjacency'].values()) // 2} region adjacencies, "
          f"{len(model['bridges'])} bridges, {len(model['trade_nodes'])} trade nodes")
    print("OK")
