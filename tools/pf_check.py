"""Shared-side consistency of a pathfinding grid: both cells must split every common side into the same
passable/off-map intervals (vanilla is welded this way; see research/06).

  python tools/pf_check.py PATHFINDING_ESF
"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pathfinding_model as pm


def sea_of(area):
    return 72                       # as side_intervals; land_probe points both at the grid's own sea domain


def side_intervals(area, P, i, axis, v):
    """[(lo, hi, cls)] along the line coord[axis]==v, cls 's' sea / 'l' land / 'x' blocked."""
    c = area.grid.cells[i]
    polys = ([(c.uniform, area.points(i, (0, 2, 3, 1)))] if c.uniform else
             [(b.trait, area.points(i, P[b.polygon_offset])) for b in c.boundaries])
    out = []
    for t, pts in polys:
        cls = 'x' if t.kind in (2, 3) else 's' if t.path_id == 72 else 'l'
        for p, q in zip(pts, pts[1:] + pts[:1]):
            if p[axis] == q[axis] == v and p[1 - axis] != q[1 - axis]:
                out.append((min(p[1 - axis], q[1 - axis]), max(p[1 - axis], q[1 - axis]), cls))
    return sorted(out)


def check(area, cells=None):
    g, P, s = area.grid, area.polygons(), area.grid.cell_size_fixed
    C, R = g.columns, g.rows
    cl, sea = g.cells, sea_of(area)
    cls = lambda t: 'x' if t.kind in (2, 3) else 's' if t.path_id == sea else 'l'
    bad = collections.Counter(); ex = []
    for i in (range(C * R) if cells is None else cells):
        r, col = divmod(i, C)
        x0, y0 = g.corners(i)[0]
        for dx, dy, axis, v in ((1, 0, 0, x0 + s), (0, 1, 1, y0 + s)):
            if col + dx >= C or r + dy >= R:
                continue
            j = (r + dy) * C + col + dx
            if cl[i].uniform and cl[j].uniform and cls(cl[i].uniform) == cls(cl[j].uniform):
                continue                    # one whole-side interval each, same coordinates and class
            a, b = side_intervals(area, P, i, axis, v), side_intervals(area, P, j, axis, v)
            if a != b:
                kinds = tuple(sorted({'U%d' % g.cells[k].uniform.kind if g.cells[k].uniform else 'M' for k in (i, j)}))
                bad[kinds] += 1
                if len(ex) < 5:
                    ex.append((col, r, 'E' if axis == 0 else 'N', a, b))
    return bad, ex


if __name__ == '__main__':
    area = pm.PathfindingModel.load(sys.argv[1]).areas[0]
    bad, ex = check(area)
    print('mismatched sides', sum(bad.values()), dict(bad))
    for e in ex:
        print(' ', e)
