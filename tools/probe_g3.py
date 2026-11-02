"""Gate G3 probe: one theatre over almost the whole world box, vanilla Europe embedded, plus a test sea corridor.

  python tools/probe_g2.py 1920 960 && python tools/probe_g3.py
      -> work/mods/world_g3/campaign_maps/nap_world, work/startpos_g3.esf (from work/startpos_c3_vis.esf)

Theatre (-1910,-940)..(1910,950): pathfinding grid 1910x945 cells (vanilla 375x193 pasted at 750,375), climate maps at
1.6 px/u (Spain's density), wind map 0.4 px/u, sea grid 51x26. Everything outside vanilla is off-map (kind 2) except
CORRIDOR, open sea west of the vanilla Atlantic. Startpos pathfinder obstacle state is emptied (research/00: plays).
"""
import os, shutil, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esf, pathfinding_model as pm, campaign_misc as cm, regions_model as rm, pf_check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
G2 = os.path.join(ROOT, 'work/mods/world_g2/campaign_maps/nap_world')
OUT = os.path.join(ROOT, 'work/mods/world_g3/campaign_maps/nap_world')
TH_MIN, TH_MAX = (-1910, -940), (1910, 950)
VT_MIN = (-410, -190)
CORRIDOR = (-1000, -190, -388, 195)          # x0, y0, x1, y1: full vanilla height (edges meet only new cells); x1 past the
                                             # vanilla map-edge strip whose sea polygons are closed to the W
CLIMATE_PPU, WIND_PPU = 1.6, 0.4

OFF = pm.Trait(2, 0, 0, 1023)
SEA = pm.Trait(1, 69649, 255, 72)
# costs8 byte order E, NW, N, NE, SW, S, SE, W; 0x01 = no neighbour (grid edge)
DIRS = ((1, 0), (-1, 1), (0, 1), (1, 1), (-1, -1), (0, -1), (1, -1), (-1, 0))
INTERIOR = bytes.fromhex('1fff1fffff1fff1f')


def edge_costs(base, col, row, C, R):
    return bytes(1 if not (0 <= col + dx < C and 0 <= row + dy < R) else (INTERIOR[i] if b == 1 else b)
                 for i, ((dx, dy), b) in enumerate(zip(DIRS, base)))


def cell_polys(area, P, i):
    """[(trait, points)] for cell i; a uniform cell is one full quad."""
    c = area.grid.cells[i]
    if c.uniform:
        return [(c.uniform, area.points(i, (0, 2, 3, 1)))]
    return [(b.trait, area.points(i, P[b.polygon_offset])) for b in c.boundaries]


def _on_line(pts, axis, v):
    return [tuple(sorted((p[1 - axis], q[1 - axis]))) for p, q in zip(pts, pts[1:] + pts[:1])
            if p[axis] == q[axis] == v and p[1 - axis] != q[1 - axis]]


_SEA = {}


def middle20(area, P, i, pts, trait):
    """research/06: five 4-bit masks S, W, same-cell, E, N; bit j = the j-th polygon of that neighbour (or of this
    cell) in the same passable class (kind not 2/3; sea = the grid's sea domain, else land) sharing an edge segment
    with pts. Exact for 92.6% of Europe's passable polygons (sea 96.8%, land 93.7%)."""
    g, s = area.grid, area.grid.cell_size_fixed
    r, col = divmod(i, g.columns)
    x0, y0 = g.corners(i)[0]
    sea = _SEA.get(id(g)) or _SEA.setdefault(id(g), g.path_domains().index(()))
    ok = lambda t: t.kind not in (2, 3) and (t.path_id == sea) == (trait.path_id == sea)
    out = 0
    for nib, (dx, dy, axis, v) in ((0, (0, -1, 1, y0)), (1, (-1, 0, 0, x0)), (3, (1, 0, 0, x0 + s)), (4, (0, 1, 1, y0 + s))):
        if not (0 <= col + dx < g.columns and 0 <= r + dy < g.rows):
            continue
        mine = _on_line(pts, axis, v)
        nb = [q for t, q in cell_polys(area, P, (r + dy) * g.columns + col + dx) if ok(t)]
        out |= sum(1 << j for j, q in enumerate(nb[:4])          # 4 bits: polygons past the 4th are not linked
                   if any(min(a1, b1) > max(a0, b0) for a0, a1 in mine for b0, b1 in _on_line(q, axis, v))) << 4 * nib
    edges = {frozenset(e) for e in zip(pts, pts[1:] + pts[:1])}
    same = [q for t, q in cell_polys(area, P, i) if ok(t)]
    out |= sum(1 << j for j, q in enumerate(same[:4]) if q != pts and edges & {frozenset(e) for e in zip(q, q[1:] + q[:1])}) << 8
    return out


def add_rims(area, P):
    """Vanilla is welded: both cells split every shared side identically, so a sea side never faces an off-map side
    (tools/pf_check.py; 0 mismatches in vanilla). G3's first build put uniform sea next to uniform off-map and the
    engine looped tracing outlines (1 GiB alloc, crash in the AI turn). Fix on a half-cell raster: a quadrant of a
    uniform sea cell turns off-map if any cell it touches is uniform off-map; each cell becomes the union of its sea
    quadrants (kind 1) and of its off quadrants (kind 2), which keeps all new sides welded. Where a sea cell faces
    a vanilla mixed cell whose shared side has off-map intervals, a half-cell-deep off strip on exactly those
    intervals welds it to the vanilla geometry."""
    from shapely.geometry import box
    from shapely.ops import unary_union
    g, s = area.grid, area.grid.cell_size_fixed
    C, R, h = g.columns, g.rows, s // 2
    U = [c.uniform.kind if c.uniform else None for c in g.cells]
    def kind_at(col, r):
        return U[r * C + col] if 0 <= col < C and 0 <= r < R else None
    verts, key, rims = list(area.vertices_fixed), max(P) + 1000, []
    vid = {p: k for k, p in enumerate(verts) if k >= 4}
    for i in range(C * R):
        if U[i] != 1:
            continue
        r, col = divmod(i, C)
        (x0, y0), (x1, y1) = g.corners(i)[0], g.corners(i)[3]
        off = [box(x0 + qx * h, y0 + qy * h, x0 + (qx + 1) * h, y0 + (qy + 1) * h) for qx in (0, 1) for qy in (0, 1)
               if 2 in (kind_at(col + 2 * qx - 1, r), kind_at(col, r + 2 * qy - 1), kind_at(col + 2 * qx - 1, r + 2 * qy - 1))]
        for dx, dy, axis, v in ((1, 0, 0, x1), (-1, 0, 0, x0), (0, 1, 1, y1), (0, -1, 1, y0)):
            if 0 <= col + dx < C and 0 <= r + dy < R and U[(r + dy) * C + col + dx] is None:
                for lo, hi, cls in pf_check.side_intervals(area, P, (r + dy) * C + col + dx, axis, v):
                    if cls == 'x':
                        d = v - h if v in (x1, y1) else v
                        off.append(box(d, lo, d + h, hi) if axis == 0 else box(lo, d, hi, d + h))
                    elif lo not in (x0, y0) or hi not in (x1, y1):
                        off.append(box(x0, y0, x0, y0))      # side vertices to import: rim cell, maybe all sea
        if off:
            rims.append((i, unary_union(off)))
    def weld(pts, i):
        r, col = divmod(i, C)
        (x0, y0), (x1, y1) = g.corners(i)[0], g.corners(i)[3]
        side_pts = {}
        for dx, dy, axis, v in ((1, 0, 0, x1), (-1, 0, 0, x0), (0, 1, 1, y1), (0, -1, 1, y0)):
            if 0 <= col + dx < C and 0 <= r + dy < R and U[(r + dy) * C + col + dx] is None:
                side_pts[(axis, v)] = {t for lo, hi, _ in pf_check.side_intervals(area, P, (r + dy) * C + col + dx, axis, v)
                                       for t in (lo, hi)}
        out = []
        for p, q in zip(pts, pts[1:] + pts[:1]):
            out.append(p)
            for (axis, v), ts in side_pts.items():
                if p[axis] == q[axis] == v:
                    lo, hi = sorted((p[1 - axis], q[1 - axis]))
                    mid = sorted((t for t in ts if lo < t < hi), reverse=p[1 - axis] > q[1 - axis])
                    out += [(v, t) if axis == 0 else (t, v) for t in mid]
        return out
    for i, offg in rims:
        corners = g.corners(i)
        x0, y0 = corners[0]
        bounds = []
        for trait, u in ((SEA, box(x0, y0, x0 + s, y0 + s).difference(offg)), (OFF, offg)):
            if u.is_empty:
                continue
            for poly in getattr(u, 'geoms', [u]):
                if poly.is_empty or poly.area == 0:
                    continue
                assert not poly.interiors, ('hole', i)
                poly = poly.simplify(0)                       # drop collinear midpoints
                pts = [tuple(map(int, p)) for p in list(poly.exterior.coords)[:-1]]
                if not poly.exterior.is_ccw:
                    pts.reverse()
                pts = weld(pts, i)
                out = []
                for p in pts:
                    if p in corners:
                        out.append(corners.index(p))
                    else:
                        if p not in vid:
                            vid[p] = len(verts); verts.append(p)
                        out.append(vid[p])
                P[key] = tuple(out)
                bounds.append(pm.Boundary(trait, key)); key += 1
        g.cells[i] = pm.Cell(g.cells[i].costs8, bounds)
    area.vertices_fixed = tuple(verts)
    rimset = {i for i, _ in rims}
    near = {(i // C + dy) * C + i % C + dx for i in rimset for dx, dy in DIRS
            if 0 <= i % C + dx < C and 0 <= i // C + dy < R} - rimset
    sides = {0: (0, -1), 1: (-1, 0), 3: (1, 0), 4: (0, 1)}
    for i in rimset | near:
        c, (r, col) = g.cells[i], divmod(i, C)
        if c.boundaries:
            for b in c.boundaries:
                if b.trait.kind in (2, 3):
                    continue
                pts = area.points(i, P[b.polygon_offset])
                m = middle20(area, P, i, pts, b.trait)
                if i not in rimset:                           # vanilla cell: only the nibbles facing a rim cell change
                    mask = sum(15 << 4 * n for n, (dx, dy) in sides.items() if (r + dy) * C + col + dx in rimset
                               and 0 <= col + dx < C and 0 <= r + dy < R)
                    m = (b.trait.middle20 & ~mask) | (m & mask)
                    b.trait = pm.Trait(b.trait.kind, m, b.trait.contact_mask, b.trait.path_id)
                else:
                    b.trait = pm.Trait(b.trait.kind, m, pm.contact_mask(pts, g.corners(i)), b.trait.path_id)
        elif U[i] in (0, 1):
            m = middle20(area, P, i, area.points(i, (0, 2, 3, 1)), c.uniform)
            assert m == c.uniform.middle20, ('uniform neighbour needs a non-default trait', col, r, hex(m))
    for i in range(C * R):                                    # no sea step into a uniform off-map cell
        if U[i] == 1 or i in rimset:
            r, col = divmod(i, C)
            cs = bytearray(g.cells[i].costs8)
            for d, (dx, dy) in enumerate(DIRS):
                if kind_at(col + dx, r + dy) == 2:
                    cs[d] = INTERIOR[d]
            c = g.cells[i]
            g.cells[i] = pm.Cell(bytes(cs), c.boundaries, c.uniform)
    return len(rims)


def build_grid(area):
    g = area.grid
    C, R = (TH_MAX[0] - TH_MIN[0]) // 2, (TH_MAX[1] - TH_MIN[1]) // 2
    dc, dr = (VT_MIN[0] - TH_MIN[0]) // 2, (VT_MIN[1] - TH_MIN[1]) // 2
    cells = [None] * (C * R)
    for i, c in enumerate(g.cells):
        r, col = divmod(i, g.columns)
        if r == g.rows - 1:              # vanilla half-cell top row (kind 2 / kind 3 halves): now fully inside
            c = pm.Cell(c.costs8, uniform=OFF)
        cells[(r + dr) * C + col + dc] = c
    x0, y0, x1, y1 = CORRIDOR
    for i in range(C * R):
        r, col = divmod(i, C)
        cx, cy = TH_MIN[0] + 2 * col + 1, TH_MIN[1] + 2 * r + 1
        c = cells[i]
        traits = [c.uniform] if c and c.uniform else [b.trait for b in c.boundaries] if c else [OFF]
        if x0 <= cx < x1 and y0 <= cy < y1 and all(t.kind in (1, 2) or (t.kind, t.path_id) == (7, 72) for t in traits):
            c = pm.Cell(bytes.fromhex('0825201414080320'), uniform=SEA)
        elif c is None:
            c = pm.Cell(INTERIOR, uniform=OFF)
        cells[i] = pm.Cell(edge_costs(c.costs8, col, r, C, R), c.boundaries, c.uniform)
    P = area.polygons()
    g.cells, g.columns, g.rows = cells, C, R
    g.origin_fixed = tuple(v << 20 for v in TH_MIN)
    print('rim cells', add_rims(area, P))
    # compact the polygon stream: drop polygons no longer referenced, keep cell order
    words, remap = [4, 0, 2, 3, 1], {0: 0}
    cells = g.cells
    for c in cells:
        for b in c.boundaries:
            if b.polygon_offset not in remap:
                remap[b.polygon_offset] = len(words)
                ids = P[b.polygon_offset]
                words += [len(ids), *ids]
            b.polygon_offset = remap[b.polygon_offset]
    g.starting_cell = ((TH_MIN[0] + 1920) // 2, (TH_MIN[1] + 960) // 2)
    g.trait_count = sum(len(c.boundaries) or 1 for c in cells)
    area.polygon_words = tuple(words)
    return C, R


def paste(van, shape, at, fill):
    out = np.full(shape, fill, van.dtype)
    out[at[0]:at[0] + van.shape[0], at[1]:at[1] + van.shape[1]] = van
    return out


def build_theatre(e):
    r = e.root
    for th in (r.find('theatres').items[0][0], r.find('theatres_and_region_keys').items[0][0]):
        th.children[1], th.children[2] = esf.Val(0x0c, tuple(map(float, TH_MIN))), esf.Val(0x0c, tuple(map(float, TH_MAX)))
    th = r.find('theatres').items[0][0]
    W, H = TH_MAX[0] - TH_MIN[0], TH_MAX[1] - TH_MIN[1]
    off = (VT_MIN[1] - TH_MIN[1], VT_MIN[0] - TH_MIN[0])                  # rows from the south, cols from the west
    for cmr in th.findall('climate_map'):
        w, h = cmr.children[0].value, cmr.children[1].value
        v = rm.nparr(cmr.children[2]).reshape(h, w)                      # row 0 = south
        vw, vh = int(round(750 * CLIMATE_PPU)), int(round(385 * CLIMATE_PPU))
        v = v[(np.arange(vh) * h // vh)[:, None], (np.arange(vw) * w // vw)[None, :]]
        nw, nh = int(W * CLIMATE_PPU), int(H * CLIMATE_PPU)
        new = paste(v, (nh, nw), [int(o * CLIMATE_PPU) for o in off], v[0, 0])
        cmr.children[0].value, cmr.children[1].value = nw, nh
        cmr.children[2] = esf.Val(cmr.children[2].tag, new.tobytes())
    wm = th.find('wind_map')
    w, h = wm.children[0].value, wm.children[1].value
    v = np.frombuffer(wm.children[3].value, np.int8).reshape(h, w, 2)
    nw, nh = int(W * WIND_PPU), int(H * WIND_PPU)
    new = paste(v, (nh, nw, 2), [int(o * WIND_PPU) for o in off], 0)
    wm.children[0].value, wm.children[1].value = nw, nh
    wm.children[3] = esf.Val(wm.children[3].tag, new.tobytes())


def grow_atlantic(e):
    """Push the Atlantic's west border, and the thin eur_map_west margin strip behind it (x -415..-393), west over
    the corridor's y-span, so the eur_atlantic_ocean_n sea region covers the corridor."""
    rd = e.root.find('region_data')
    V = rm.verts(rd)
    x0, y0, x1, y1 = CORRIDOR
    border = [i for i, (x, y) in enumerate(V) if -420 < x < -390 and y0 <= y <= y1]
    rm.move_vertices(rd, {i: (V[i][0] - (x1 - x0), V[i][1]) for i in border})
    bad = [c for c, poly in rm.area_polygons(rd).items() if not poly.is_valid]
    assert not bad, bad
    e.root.children[e.root.children.index(e.root.find('query_info'))] = rm.build_query_info(rd, True)
    return len(border)


def build_sea_grid(e):
    s = cm.read_sea_grids(e)
    cols, rows, cells = cm.make_sea_grid_cells(TH_MIN, TH_MAX, s.cell)
    dx, dy = int((VT_MIN[0] - TH_MIN[0]) // s.cell), int((VT_MIN[1] - TH_MIN[1]) // s.cell)
    assert (dx * s.cell, dy * s.cell) == (VT_MIN[0] - TH_MIN[0], VT_MIN[1] - TH_MIN[1]), 'vanilla sea cells must stay aligned'
    k = lambda i: (i // s.cols + dy) * cols + i % s.cols + dx
    info = [[[], [], [], []] for _ in cells]
    for i, lists in enumerate(s.info):
        info[k(i)] = lists
    s.bmin, s.bmax, s.cols, s.rows, s.cells, s.info = tuple(map(float, TH_MIN)), tuple(map(float, TH_MAX)), cols, rows, cells, info
    s.edges = [(k(a), k(b), c) for a, b, c in s.edges]
    return cm.write_sea_grids(s)


def empty_obstacles(sp):
    rec, = cm._iter_recs(sp.root, 'CAMPAIGN_PATHFINDER')
    g, = rec.find('PATHFINDING_GRID').items
    g[0].value = 0
    for i in (1, 5):
        g[i].value = b''
    g[2].children[0].items = []
    g[3].children[0].value = b''
    g[4].items = []
    ol = g[6]
    for c in ol.children:
        if isinstance(c, esf.Rec):
            c.items = []
        else:
            c.value = b''


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    shutil.copytree(G2, OUT)
    m = pm.PathfindingModel.load(OUT + '/pathfinding.esf')
    print('pathfinding grid', build_grid(m.areas[0]))
    open(OUT + '/pathfinding.esf', 'wb').write(m.encode())
    e = esf.load(OUT + '/regions.esf'); build_theatre(e)
    print('atlantic border vertices moved', grow_atlantic(e))
    open(OUT + '/regions.esf', 'wb').write(esf.dumps(e))
    sg = esf.dumps(build_sea_grid(esf.load(OUT + '/sea_grids.esf')))
    open(OUT + '/sea_grids.esf', 'wb').write(sg)
    sp = esf.load(os.path.join(ROOT, 'work/startpos_c3_vis.esf')); empty_obstacles(sp)
    open(os.path.join(ROOT, 'work/startpos_g3.esf'), 'wb').write(esf.dumps(sp))
    # self-check: re-decode what we wrote
    g = pm.PathfindingModel.load(OUT + '/pathfinding.esf').areas[0].grid
    assert (g.columns, g.rows, len(g.cells)) == (1910, 945, 1910 * 945)
    assert g.trait_count == sum(len(c.boundaries) or 1 for c in g.cells)
    area = pm.PathfindingModel.load(OUT + '/pathfinding.esf').areas[0]
    pm.rebuild_spatial_grid(area)                 # asserts CCW polygons, full tile area, contact masks
    bad, ex = pf_check.check(area)
    print('unwelded sides', dict(bad), ex[:3])
    s = cm.read_sea_grids(esf.load(OUT + '/sea_grids.esf'))
    assert (s.cols, s.rows) == (51, 26) and sum(bool(i[1]) for i in s.info) == 39
    print('ok; sea cells', sum(c.uniform == SEA for c in g.cells))


if __name__ == '__main__':
    main()
