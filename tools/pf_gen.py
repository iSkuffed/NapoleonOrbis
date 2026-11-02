"""World pathfinding.esf, Phase 4 M1 "world ocean": vanilla Europe kept, the rest of the world sea or off-map.

  python tools/pf_gen.py OUT_DIR [--check]   # writes OUT_DIR/pathfinding.esf; self-check: CCW/tile area, pf_check 0,
                                             # world seas reachable by sea from Biscay

Grid = proj.THEATRE at 2 units, vanilla 375x193 pasted at its identity position. Regenerated cells: everything
outside the vanilla theatre, plus the vanilla off-map rim (pure off-map cells flood-connected to the vanilla grid
edge) and the sea/off cells touching it, so seas run on past the old edge. Their class field is "ocean" (the
largest water body of worldgeo.land(); lakes and the Caspian stay off-map) united with any vanilla sea polygons.
Every cell is clipped from that one field in fixed point (grid_size=1), so generated neighbours split shared sides
identically (research/06 welding invariant). Sides facing kept cells (vanilla, or the 1-cell off-map frame) get a
STRIP-deep band copying the kept side's intervals, with 45-degree ends so bands of adjacent sides never overlap.
"""
import os, sys, collections
import numpy as np
import shapely
from shapely.geometry import box, Polygon, MultiPolygon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proj, worldgeo, geo, pathfinding_model as pm, pf_check
from probe_g3 import middle20, DIRS, INTERIOR, OFF, SEA

FIX = 1 << 20
S = 2 * FIX                                   # cell size, fixed
STRIP = S // 4
RING = 2
EDGE7 = 12
TILE = 32 * FIX                               # land tiles for clipping (multiple of S)
C = (proj.THEATRE_MAX[0] - proj.THEATRE_MIN[0]) // 2
R = -(-(proj.THEATRE_MAX[1] - proj.THEATRE_MIN[1]) // 2)       # top row is half outside the theatre, like vanilla
DC, DR = (proj.VT_MIN[0] - proj.THEATRE_MIN[0]) // 2, (proj.VT_MIN[1] - proj.THEATRE_MIN[1]) // 2
X0, Y0 = proj.THEATRE_MIN[0] * FIX, proj.THEATRE_MIN[1] * FIX
CACHE = os.path.join(worldgeo.CACHE, 'pf_land.wkb')
OPP = (7, 6, 5, 4, 3, 2, 1, 0)                # DIRS index of the opposite direction
SEA_COST = 0x14                               # research/06: 20 + wind term; no wind yet
COAST_TOL = 0.25                              # u: generated coastline simplification (Douglas-Peucker, topology-preserving
                                              # so no strait closes); 10m NE cost ~2 polygon words a vertex: 1.67M -> ~1.0M


def land_fixed():
    """Theatre minus the world ocean, fixed point, no vertex on a grid line, simplified by COAST_TOL (the kept vertices
    are a subset, so still integer and off the grid lines). The unsimplified field is cached."""
    if os.path.exists(CACHE):
        return shapely.simplify(shapely.from_wkb(open(CACHE, 'rb').read()), COAST_TOL * FIX, preserve_topology=True)
    th = worldgeo.THEATRE
    land = worldgeo.land()
    filled = shapely.union_all([Polygon(p.exterior) for p in land.geoms])
    water = th.difference(filled)
    ocean = max(getattr(water, 'geoms', [water]), key=lambda p: p.area)
    g = shapely.set_precision(shapely.transform(th.difference(ocean), lambda c: c * FIX), 1.0)
    # nudge vertices lying exactly on a grid line (theatre-edge ones included: the frame is off-map anyway)
    g = shapely.make_valid(shapely.transform(g, lambda c: c + (c % S == 0)))
    g = shapely.set_precision(g, 1.0)
    open(CACHE, 'wb').write(shapely.to_wkb(g))
    return land_fixed()


def polygonal(g):
    """Drop the lines/points a grid_size overlay of the simplified field can leave (a GeometryCollection breaks the
    next overlay: 'mixed-dimension')."""
    if g.geom_type != 'GeometryCollection':
        return g
    return shapely.union_all([p for p in shapely.get_parts(g) if p.geom_type in ('Polygon', 'MultiPolygon')])


def land_tiles(g):
    """{(tx, ty): piece} by recursive quartering, so no clip runs against all of Eurasia."""
    out = {}
    def rec(geom, x0, y0, n):                  # n = side in tiles (power of two)
        if geom.is_empty:
            return
        if n == 1:
            out[((x0 - X0) // TILE, (y0 - Y0) // TILE)] = geom
            return
        h = n // 2
        for qx in (0, 1):
            for qy in (0, 1):
                bx, by = x0 + qx * h * TILE, y0 + qy * h * TILE
                rec(polygonal(shapely.intersection(geom, box(bx, by, bx + h * TILE, by + h * TILE), grid_size=1.0)), bx, by, h)
    n = 1
    while n * TILE < max(C, R) * S:
        n *= 2
    rec(g, X0, Y0, n)
    return out


def flood_rim(vgrid):
    """Vanilla cell indices (vanilla grid) to regenerate: pure off-map cells flood-connected to the grid edge, plus
    sea/off-only cells (sea slots included) within RING steps of them. The vanilla Atlantic edge has a second column
    of mixed cells (x ~ -392) whose off-map corners would otherwise stay as a fence."""
    vc, vr = vgrid.columns, vgrid.rows
    def traits(c):
        return [c.uniform] if c.uniform else [b.trait for b in c.boundaries]
    pure_x = [all(t.kind in (2, 3) for t in traits(c)) for c in vgrid.cells]
    # sea slots (kind 7) only in the map-edge band (<= EDGE7 cells): further in they are real ports
    edge = lambda i: min(i % vc, i // vc, vc - 1 - i % vc, vr - 1 - i // vc)
    seaoff = [all(t.kind in (2, 3) or (t.kind == 1 and t.path_id == 72) or
                  (t.kind == 7 and t.path_id == 72 and edge(i) <= EDGE7) for t in traits(c))
              for i, c in enumerate(vgrid.cells)]
    seen = {i for i in range(vc * vr) if pure_x[i] and (i % vc in (0, vc - 1) or i // vc in (0, vr - 1))}
    todo = list(seen)
    while todo:
        i = todo.pop()
        r, c = divmod(i, vc)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            j = (r + dy) * vc + c + dx
            if 0 <= c + dx < vc and 0 <= r + dy < vr and j not in seen and pure_x[j]:
                seen.add(j); todo.append(j)
    out = set(seen)
    for _ in range(RING):
        out |= {(r + dy) * vc + c + dx for i in out for r, c in [divmod(i, vc)]
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                if 0 <= c + dx < vc and 0 <= r + dy < vr and seaoff[(r + dy) * vc + c + dx]}
    return out


def strip(axis, v, lo, hi, inward, lo_corner, hi_corner):
    """Band of depth STRIP inside the cell along side coord[axis]==v over [lo, hi]; 45-degree ends at cell corners."""
    t = min(STRIP, (hi - lo) // max(1, lo_corner + hi_corner))      # short interval: shallower band, no bow-tie
    d = inward * t
    a, b = lo + (t if lo_corner else 0), hi - (t if hi_corner else 0)
    pts = [(v, lo), (v, hi), (v + d, b), (v + d, a)] if axis == 0 else [(lo, v), (hi, v), (b, v + d), (a, v + d)]
    return Polygon(pts)


def build(out_dir):
    van = pm.PathfindingModel.load(geo.GAME + '/campaign_maps/nap_europe/pathfinding.esf')
    area = van.areas[0]
    g, P = area.grid, area.polygons()
    vc, vr = g.columns, g.rows
    regen_v = flood_rim(g)
    vsea = {}                                  # new index -> vanilla sea polygons (fixed points) of regenerated cells
    cells = [None] * (C * R)
    kept = bytearray(C * R)                    # 1 = vanilla kept, 2 = frame (uniform off-map)
    for i, c in enumerate(g.cells):
        r, col = divmod(i, vc)
        k = (r + DR) * C + col + DC
        if i in regen_v:
            vsea[k] = [area.points(i, P[b.polygon_offset]) for b in c.boundaries if b.trait.kind in (1, 7) and b.trait.path_id == 72] + \
                      ([area.points(i, (0, 2, 3, 1))] if c.uniform and c.uniform.path_id == 72 else [])
        else:
            cells[k] = c; kept[k] = 1
    for k in range(C * R):
        r, col = divmod(k, C)
        if r in (0, R - 1) or col in (0, C - 1):
            assert not kept[k]
            cells[k] = pm.Cell(INTERIOR, uniform=OFF); kept[k] = 2
    g.cells, g.columns, g.rows, g.origin_fixed = cells, C, R, (X0, Y0)
    g.starting_cell = ((proj.THEATRE_MIN[0] - proj.BOX_MIN[0]) // 2, (proj.THEATRE_MIN[1] - proj.BOX_MIN[1]) // 2)
    print('regenerated vanilla cells', len(regen_v))

    tiles = land_tiles(land_fixed())
    print('land tiles', len(tiles))
    verts = list(area.vertices_fixed)
    vid = {p: n for n, p in enumerate(verts) if n >= 4}
    key = max(P) + 1000
    sides = ((1, 0, 0, 1), (-1, 0, 0, 0), (0, 1, 1, 1), (0, -1, 1, 0))      # dx, dy, axis, far side?
    stats = collections.Counter()
    gen = [k for k in range(C * R) if not kept[k]]
    # classify by tile: uniform land, uniform sea, or needs clipping
    boxes = shapely.box(*np.array([(X0 + k % C * S, Y0 + k // C * S) for k in gen]).T,
                        *(np.array([(X0 + k % C * S + S, Y0 + k // C * S + S) for k in gen]).T))
    tkey = [((k % C * S) // TILE, (k // C * S) // TILE) for k in gen]
    empty = shapely.Polygon()
    tl = np.array([tiles.get(t, empty) for t in tkey], object)
    land_c = np.array([polygonal(x) for x in shapely.intersection(boxes, tl, grid_size=1.0)], object)
    la = shapely.area(land_c)
    for n, k in enumerate(gen):
        r, col = divmod(k, C)
        if k not in vsea and not any(kept[(r + dy) * C + col + dx] for dx, dy, _, _ in sides):
            if la[n] == 0:
                cells[k] = pm.Cell(bytes([SEA_COST] * 8), uniform=SEA); stats['sea'] += 1
                continue
            if la[n] == S * S:
                cells[k] = pm.Cell(INTERIOR, uniform=OFF); stats['off'] += 1
                continue
        x0, y0 = X0 + col * S, Y0 + r * S
        cell = boxes[n]
        lc = land_c[n]
        sea = cell.difference(lc, grid_size=1.0) if not lc.is_empty else cell
        if k in vsea and vsea[k]:
            sea = shapely.union_all([sea] + [Polygon(p) for p in vsea[k]], grid_size=1.0)
        # bands copying kept neighbours' sides
        adds, subs = [], []
        for dx, dy, axis, far in sides:
            j = (r + dy) * C + col + dx
            if not kept[j]:
                continue
            v = (x0, y0)[axis] + far * S
            base = (y0, x0)[axis]
            # 45-degree ends at cell corners: a band then touches the perpendicular sides only at the corner point,
            # so generated neighbours (which never see this band) still agree on those sides
            for lo, hi, cls in pf_check.side_intervals(area, P, j, axis, v):
                assert cls in 'sx', ('land interval faces a regenerated cell', col, r, cls)
                band = strip(axis, v, lo, hi, -1 if far else 1, lo == base, hi == base + S)
                (adds if cls == 's' else subs).append(band)
        if adds:
            sea = shapely.union_all([sea] + adds, grid_size=1.0)
        if subs:
            sea = sea.difference(shapely.union_all(subs, grid_size=1.0), grid_size=1.0)
        sea = sea.intersection(cell, grid_size=1.0)
        # in-cell lakes (sea pieces off the cell boundary) -> off; in-cell islands (holes) -> sea
        ring = cell.exterior
        keep = [Polygon(p.exterior) for p in getattr(sea, 'geoms', [sea])
                if p.geom_type == 'Polygon' and not p.is_empty and p.intersection(ring).length > 0]
        if not keep:
            cells[k] = pm.Cell(INTERIOR, uniform=OFF); stats['off'] += 1
            continue
        sea = shapely.union_all(keep, grid_size=1.0)
        if sea.equals(cell):
            cells[k] = pm.Cell(bytes([SEA_COST] * 8), uniform=SEA); stats['sea'] += 1
            continue
        off = cell.difference(sea, grid_size=1.0)
        bounds = []
        for trait, geom in ((SEA, sea), (OFF, off)):
            # largest first: middle20 links only a neighbour's first 4 polygons per class
            polys = sorted((p for p in getattr(geom, 'geoms', [geom]) if p.geom_type == 'Polygon' and p.area > 0),
                           key=lambda p: -p.area)
            stats['max_%s' % trait.kind] = max(stats['max_%s' % trait.kind], len(polys))
            stats['over4_%s' % trait.kind] += len(polys) > 4
            for p in polys:
                assert not p.interiors, ('hole', col, r, trait.kind)
                p = shapely.simplify(p, 0)
                pts = [(int(x), int(y)) for x, y in p.exterior.coords[:-1]]
                if not p.exterior.is_ccw:
                    pts.reverse()
                corners = g.corners(k)
                ids = []
                for q in pts:
                    if q in corners:
                        ids.append(corners.index(q))
                    else:
                        if q not in vid:
                            vid[q] = len(verts); verts.append(q)
                        ids.append(vid[q])
                P[key] = tuple(ids)
                bounds.append(pm.Boundary(trait, key)); key += 1
        cells[k] = pm.Cell(bytes([SEA_COST] * 8), bounds); stats['mixed'] += 1
    area.vertices_fixed = tuple(verts)
    print('generated', dict(stats))
    weld(area, P, kept)
    traits_and_costs(area, P, kept)
    compact(area, P)
    m = van
    open(os.path.join(out_dir, 'pathfinding.esf'), 'wb').write(m.encode())
    return area


def side_pts(area, P, k, axis, v):
    """Non-corner vertices of cell k lying on the side line coord[axis]==v."""
    c = area.grid.cells[k]
    if c.uniform:
        return set()
    lo = area.grid.corners(k)[0][1 - axis]
    return {p[1 - axis] for b in c.boundaries for p in area.points(k, P[b.polygon_offset])
            if p[axis] == v and lo < p[1 - axis] < lo + S}


def weld(area, P, kept):
    """Insert the neighbour's side vertices into generated polygons (no T-junctions). A kept cell needing a vertex
    is a generator bug: assert."""
    g = area.grid
    verts, vid = list(area.vertices_fixed), {}
    for n, p in enumerate(verts):
        if n >= 4:
            vid.setdefault(p, n)
    fixes = 0
    for k in range(C * R):
        r, col = divmod(k, C)
        x0, y0 = g.corners(k)[0]
        for dx, dy, axis, v in ((1, 0, 0, x0 + S), (0, 1, 1, y0 + S)):
            if col + dx >= C or r + dy >= R:
                continue
            j = (r + dy) * C + col + dx
            if kept[k] and kept[j]:
                continue
            a, b = side_pts(area, P, k, axis, v), side_pts(area, P, j, axis, v)
            if a == b:
                continue
            for cell_i, need in ((k, b - a), (j, a - b)):
                if not need:
                    continue
                assert not kept[cell_i], ('kept cell needs side vertices', cell_i % C, cell_i // C, sorted(need))
                c = g.cells[cell_i]
                if c.uniform:                  # turn into one explicit square so it can carry side vertices
                    P[max(P) + 1000] = (0, 2, 3, 1)
                    c = pm.Cell(c.costs8, [pm.Boundary(c.uniform, max(P))])
                    g.cells[cell_i] = c
                for bnd in c.boundaries:
                    pts = area.points(cell_i, P[bnd.polygon_offset])
                    ids = list(P[bnd.polygon_offset])
                    out = []
                    for n2, (p, q) in enumerate(zip(pts, pts[1:] + pts[:1])):
                        out.append(ids[n2])
                        if p[axis] == q[axis] == v:
                            lo, hi = sorted((p[1 - axis], q[1 - axis]))
                            for t in sorted((t for t in need if lo < t < hi), reverse=p[1 - axis] > q[1 - axis]):
                                pt = (v, t) if axis == 0 else (t, v)
                                if pt not in vid:
                                    vid[pt] = len(verts); verts.append(pt)
                                out.append(vid[pt]); fixes += 1
                    P[bnd.polygon_offset] = tuple(out)
    area.vertices_fixed = tuple(verts)
    print('weld: vertices inserted', fixes)


def sea_mask(c):
    if c.uniform:
        return 255 if c.uniform.kind == 1 else 0
    m = 0
    for b in c.boundaries:
        if b.trait.kind not in (2, 3) and b.trait.path_id == 72:
            m |= b.trait.contact_mask
    return m


def traits_and_costs(area, P, kept):
    """contact masks + middle20 for generated sea polygons; vanilla kept cells facing generated ones get the facing
    nibbles recomputed; costs: open (SEA_COST) only where both cells' sea touches the shared side/corner."""
    g = area.grid
    near = set()
    for k in range(C * R):
        if kept[k] == 1:
            r, col = divmod(k, C)
            if any(not kept[(r + dy) * C + col + dx] for dx, dy in DIRS if 0 <= col + dx < C and 0 <= r + dy < R):
                near.add(k)
    gen = [k for k in range(C * R) if not kept[k]]
    for k in gen:                              # geometry-only fields first (contact masks feed middle20? no; costs yes)
        c = g.cells[k]
        for b in c.boundaries:
            if b.trait.kind == 1:
                pts = area.points(k, P[b.polygon_offset])
                b.trait = pm.Trait(1, 0, pm.contact_mask(pts, g.corners(k)), 72)
    nib = {0: (0, -1), 1: (-1, 0), 3: (1, 0), 4: (0, 1)}
    changed = 0
    for k in gen + sorted(near):
        c, (r, col) = g.cells[k], divmod(k, C)
        if c.uniform:
            if c.uniform.kind == 1 and any(g.cells[(r + dy) * C + col + dx].boundaries for dx, dy in nib.values()):
                m = middle20(area, P, k, area.points(k, (0, 2, 3, 1)), c.uniform)
                if m != c.uniform.middle20:
                    P[max(P) + 1000] = (0, 2, 3, 1)
                    g.cells[k] = pm.Cell(c.costs8, [pm.Boundary(pm.Trait(1, m, 255, 72), max(P))]); changed += 1
            continue
        for b in c.boundaries:
            if b.trait.kind in (2, 3):
                continue
            m = middle20(area, P, k, area.points(k, P[b.polygon_offset]), b.trait)
            if kept[k]:
                mask = sum(15 << 4 * n for n, (dx, dy) in nib.items() if not kept[(r + dy) * C + col + dx])
                m = (b.trait.middle20 & ~mask) | (m & mask)
            b.trait = pm.Trait(b.trait.kind, m, b.trait.contact_mask, b.trait.path_id)
    print('uniform sea cells made explicit for middle20', changed)
    masks = {}
    for k in gen + sorted(near):
        r, col = divmod(k, C)
        cs = bytearray(g.cells[k].costs8)
        m = sea_mask(g.cells[k])
        for d, (dx, dy) in enumerate(DIRS):
            j = (r + dy) * C + col + dx
            if not (0 <= col + dx < C and 0 <= r + dy < R):
                cs[d] = 1
            elif kept[k] and kept[j]:
                continue
            elif m >> d & 1 and sea_mask(g.cells[j]) >> OPP[d] & 1:
                if cs[d] in (0x1f, 0xff, 1) or not kept[k]:
                    cs[d] = SEA_COST
            else:
                cs[d] = INTERIOR[d]
        c = g.cells[k]
        g.cells[k] = pm.Cell(bytes(cs), c.boundaries, c.uniform)


def compact(area, P):
    g = area.grid
    words, remap = [4, 0, 2, 3, 1], {}
    for c in g.cells:
        for b in c.boundaries:
            ids = P[b.polygon_offset]
            if ids == (0, 2, 3, 1):
                b.polygon_offset = 0
                continue
            if b.polygon_offset not in remap:
                remap[b.polygon_offset] = len(words)
                words += [len(ids), *ids]
            b.polygon_offset = remap[b.polygon_offset]
    assert len(words) < pm.STATIC_LIMIT, ('polygon stream reaches 2^21 (bit 21 = dynamic polygon)', len(words))
    g.trait_count = sum(len(c.boundaries) or 1 for c in g.cells)
    area.polygon_words = tuple(words)
    print('polygon words', len(words), 'vertices', len(area.vertices_fixed), 'traits', g.trait_count)


def selfcheck(path):
    area = pm.PathfindingModel.load(path).areas[0]
    g = area.grid
    assert (g.columns, g.rows) == (C, R)
    pm.rebuild_spatial_grid(area)              # asserts CCW, in-cell polygons, tile area, contact masks
    bad, ex = pf_check.check(area)
    print('unwelded sides', sum(bad.values()), dict(bad), ex[:3])
    assert not bad
    # fleets: open cost steps from the Bay of Biscay must reach the world's seas
    cell = lambda lon, lat: (lambda x, y: int((y - proj.THEATRE_MIN[1]) // 2) * C + int((x - proj.THEATRE_MIN[0]) // 2))(
        *map(float, proj.to_world(lon, lat)))
    seen, todo = {cell(-5, 46)}, [cell(-5, 46)]
    while todo:
        k = todo.pop()
        r, col = divmod(k, C)
        cs = g.cells[k].costs8
        for d, (dx, dy) in enumerate(DIRS):
            j = (r + dy) * C + col + dx
            if cs[d] not in (0x1f, 0xff, 1) and j not in seen:
                seen.add(j); todo.append(j)
    for name, lon, lat in (('mid-Atlantic', -40, 30), ('Caribbean', -75, 15), ('mid-Pacific', -150, 0),
                           ('Indian Ocean', 75, -10), ('Bay of Bengal', 88, 15), ('Sea of Japan', 135, 40),
                           ('Tasman Sea', 160, -38), ('Black Sea', 34, 43), ('Baltic', 19, 57), ('Red Sea', 38, 20)):
        assert cell(lon, lat) in seen, ('unreachable by sea', name)
    print('sea reach: %d cells from Biscay; all test seas reachable' % len(seen))
    print('ok; uniform sea', sum(bool(c.uniform) and c.uniform.kind == 1 for c in g.cells),
          'explicit cells', sum(bool(c.boundaries) for c in g.cells))


if __name__ == '__main__':
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    if sys.argv[2:] != ['--check']:
        build(out)
    selfcheck(os.path.join(out, 'pathfinding.esf'))
