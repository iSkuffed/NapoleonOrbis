#!/usr/bin/env python3
"""Lossless NTW pathfinding model and independently checked derived geometry.

Run without arguments for five-map round trips, four-map geometry/grid rebuilds,
Europe/startpos reference checks, and PNG/JSON diagnostics under scratch_pathfinding.
No game files are written. See research/06-pathfinding-esf.md for evidence limits.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
import esf

SCALE = 1 << 20
SENTINEL = -2147483647
MASK22 = (1 << 22) - 1
STATIC_LIMIT = 1 << 21    # boundary offsets with bit 21 set are dynamic polygons (engine 0xB108D0): files stay below
DATA = Path.home() / '.local/share/Steam/steamapps/common/Napoleon Total War/data'
SCRATCH = Path(__file__).resolve().parents[1] / 'work/scratch_pathfinding'
MAPS = ('nap_europe', 'nap_egypt', 'nap_italy', 'nap_spain', 'nap_tut')
PATH_TYPES = ('passable area', 'sea boundary', 'transition area', 'river',
              'land bridge area', 'land bridge transition area', 'road', 'slot')


def _words(raw, fmt):
    size = struct.calcsize('<' + fmt)
    if len(raw) % size:
        raise ValueError('unaligned scalar array')
    return tuple(v[0] for v in struct.iter_unpack('<' + fmt, raw))


def _array(tag, values, fmt='I'):
    return esf.Val(tag, b''.join(struct.pack('<' + fmt, v) for v in values))


def _vals(row, tags):
    if len(row) != len(tags) or any(not isinstance(v, esf.Val) or v.tag != t
                                     for v, t in zip(row, tags)):
        raise ValueError('unexpected ESF value layout')
    return tuple(v.value for v in row)


@dataclass(frozen=True)
class Trait:
    """A tile-clipped polygon's packed attributes and 10-bit path-domain ID.

    middle20 is intentionally unnamed; its generator is still unknown.
    contact_mask is geometric side/corner contact, not polygon area percentage.
    """
    kind: int
    middle20: int
    contact_mask: int
    path_id: int

    @classmethod
    def unpack(cls, word, path_id):
        return cls(word & 15, (word >> 4) & 0xfffff, word >> 24, path_id)

    def pack(self):
        if not (0 <= self.kind < 16 and 0 <= self.middle20 < 1 << 20
                and 0 <= self.contact_mask < 256 and 0 <= self.path_id < 1024):
            raise ValueError('trait field overflow')
        return self.kind | self.middle20 << 4 | self.contact_mask << 24


@dataclass
class Boundary:
    trait: Trait
    polygon_offset: int

    def __post_init__(self):
        if not 0 <= self.polygon_offset < STATIC_LIMIT:
            raise ValueError("polygon offset >= 2^21 (bit 21 = dynamic polygon; W5 load crash)")


@dataclass
class Cell:
    """One expanded cell; an implicit full quad or a list of clipped polygons."""
    costs8: bytes
    boundaries: list[Boundary] = field(default_factory=list)
    uniform: Trait | None = None

    def __post_init__(self):
        if len(self.costs8) != 8 or bool(self.boundaries) == (self.uniform is not None):
            raise ValueError('cell needs 8 bytes and exactly one polygon representation')


@dataclass
class Grid:
    origin_fixed: tuple[int, int]
    starting_cell: tuple[int, int]
    cell_size_fixed: int
    columns: int
    rows: int
    trait_count: int
    passable_region_count: int
    listed_region_count: int
    region_indices: tuple[int, ...]
    path_table: tuple[int, ...]
    cells: list[Cell]
    # Spain's geometry/header are scrambled. Cells remain interpretable structurally.
    obfuscated: bool = False

    def path_domains(self):
        """Domain IDs -> tuples of zero-based regions.esf region indices; () = sea.

        -1/1023 is outside/transition, separate from this table.
        """
        if self.obfuscated:
            raise ValueError('Spain path-domain table is obfuscated')
        sep = self.path_table.index(0)
        domains = [(self.region_indices[i - 1],) for i in self.path_table[:sep]]
        domains.append(())
        at = sep + 1
        while at < len(self.path_table):
            n = self.path_table[at]
            if n < 1 or at + n >= len(self.path_table):
                raise ValueError('bad path-domain set length')
            members = self.path_table[at + 1:at + 1 + n]
            if not all(1 <= i <= len(self.region_indices) for i in members):
                raise ValueError('bad region lookup')
            domains.append(tuple(self.region_indices[i - 1] for i in members))
            at += n + 1
        return tuple(domains)

    def trait_offsets(self):
        at, out = 0, []
        for cell in self.cells:
            out.append(at)
            at += len(cell.boundaries) or 1
        return tuple(out)

    def corners(self, index):
        x = self.origin_fixed[0] + index % self.columns * self.cell_size_fixed
        y = self.origin_fixed[1] + index // self.columns * self.cell_size_fixed
        s = self.cell_size_fixed
        return ((x, y), (x, y + s), (x + s, y), (x + s, y + s))


@dataclass
class Area:
    vertices_fixed: tuple[tuple[int, int], ...]
    polygon_words: tuple[int, ...]
    grid: Grid

    def polygons(self):
        if self.grid.obfuscated:
            raise ValueError('Spain polygon stream is obfuscated')
        out, at = {}, 0
        while at < len(self.polygon_words):
            n = self.polygon_words[at]
            if n < 3 or at + n >= len(self.polygon_words):
                raise ValueError(f'invalid polygon length at word {at}')
            ids = self.polygon_words[at + 1:at + 1 + n]
            if any(i >= len(self.vertices_fixed) for i in ids):
                raise ValueError('polygon vertex outside table')
            out[at] = ids
            at += n + 1
        return out

    def points(self, cell_index, vertex_ids):
        corners = self.grid.corners(cell_index)
        return tuple(corners[i] if i < 4 else self.vertices_fixed[i] for i in vertex_ids)


@dataclass
class Barrier:
    name: str
    outlines_fixed: tuple[tuple[tuple[int, int], ...], ...]


@dataclass
class PathfindingModel:
    timestamp: int
    names: tuple[str, ...]
    areas: list[Area]
    root_order: tuple[str, ...]
    obstacles: bytes | None = None
    barriers: list[Barrier] | None = None

    @classmethod
    def load(cls, path):
        return cls.decode(esf.load(path))

    @classmethod
    def decode(cls, source):
        root = source.root
        if root.name != 'root' or root.version != 0:
            raise ValueError('unsupported root')
        order = tuple(r.name for r in root.children)
        if len(set(order)) != len(order) or not set(order) <= {'pathfinding_areas', 'obstacles', 'barriers'}:
            raise ValueError('unsupported root children')
        ob = root.find('obstacles')
        obstacles = _vals(ob.children, (0x46,))[0] if ob else None
        areas = []
        ar = root.find('pathfinding_areas')
        if ar is None or ar.version != 0:
            raise ValueError('missing area array')
        for row in ar.items:
            if len(row) != 3:
                raise ValueError('unexpected area layout')
            vr, words, gr = row
            if vr.name != 'vertices' or gr.name != 'grid_data' or words.tag != 0x48:
                raise ValueError('unexpected area fields')
            if vr.version or gr.version:
                raise ValueError('unsupported area version')
            vertices = tuple(_vals(it, (4, 4)) for it in vr.items)
            h = _vals(gr.children[:10], (4, 4, 7, 7, 4, 8, 8, 8, 7, 7))
            ri, pt, cr = gr.children[10:]
            if (ri.tag, pt.tag, cr.name, cr.version) != (0x43, 0x47, 'grid_cells', 0):
                raise ValueError('unsupported grid layout')
            cells = []
            for cellrow in cr.items:
                if len(cellrow) not in (2, 5):
                    raise ValueError('unexpected cell length')
                costs, br = cellrow[:2]
                if costs.tag != 0x46 or br.name != 'boundaries' or br.version:
                    raise ValueError('unsupported cell layout')
                boundaries = []
                for b in br.items:
                    w, ref = _vals(b, (8, 8))
                    boundaries.append(Boundary(Trait.unpack(w, ref >> 22), ref & MASK22))
                if len(cellrow) == 2:
                    cells.append(Cell(costs.value, boundaries))
                else:
                    if boundaries:
                        raise ValueError('uniform run has boundaries')
                    w, pid, blob = _vals(cellrow[2:], (8, 7, 0x46))
                    cells.append(Cell(costs.value, uniform=Trait.unpack(w, pid)))
                    if len(blob) % 12:
                        raise ValueError('invalid uniform-cell run')
                    for at in range(0, len(blob), 12):
                        word = struct.unpack_from('<I', blob, at + 8)[0]
                        cells.append(Cell(blob[at:at + 8], uniform=Trait.unpack(word, pid)))
            grid = Grid((h[0], h[1]), (h[2], h[3]), *h[4:],
                        _words(ri.value, 'h'), _words(pt.value, 'H'), cells,
                        obfuscated=obstacles is not None)
            areas.append(Area(vertices, _words(words.value, 'I'), grid))
        barriers_record = root.find('barriers')
        barriers = None
        if barriers_record:
            if barriers_record.version:
                raise ValueError('unsupported barriers version')
            barriers = []
            for row in barriers_record.items:
                if row[0].tag != 0x0e or any(v.tag != 0x48 for v in row[1:]):
                    raise ValueError('unexpected barrier layout')
                outlines = []
                for v in row[1:]:
                    words = _words(v.value, 'i')
                    if len(words) % 2:
                        raise ValueError('odd barrier coordinate count')
                    outlines.append(tuple(zip(words[::2], words[1::2])))
                barriers.append(Barrier(row[0].value, tuple(outlines)))
        return cls(source.timestamp, tuple(source.names), areas, order, obstacles, barriers)

    def encode(self):
        """Build a fresh ESF tree. No retained Esf/Rec nodes or original file bytes."""
        area_rows = []
        for area in self.areas:
            g = area.grid
            verts = esf.Rec('vertices', items=[[esf.Val(4, x), esf.Val(4, y)]
                                             for x, y in area.vertices_fixed])
            h = (*g.origin_fixed, *g.starting_cell, g.cell_size_fixed, g.columns, g.rows,
                 g.trait_count, g.passable_region_count, g.listed_region_count)
            gr = [esf.Val(t, v) for t, v in zip((4, 4, 7, 7, 4, 8, 8, 8, 7, 7), h)]
            gr += [_array(0x43, g.region_indices, 'h'), _array(0x47, g.path_table, 'H')]
            rows, at = [], 0
            while at < len(g.cells):
                c = g.cells[at]
                boundaries = [[esf.Val(8, b.trait.pack()),
                               esf.Val(8, b.trait.path_id << 22 | b.polygon_offset)]
                              for b in c.boundaries]
                row = [esf.Val(0x46, c.costs8), esf.Rec('boundaries', items=boundaries)]
                at += 1
                if c.uniform is not None:
                    blob = bytearray()
                    while at < len(g.cells):
                        nxt = g.cells[at]
                        if nxt.uniform is None or nxt.uniform.path_id != c.uniform.path_id:
                            break
                        blob += nxt.costs8 + struct.pack('<I', nxt.uniform.pack())
                        at += 1
                    row += [esf.Val(8, c.uniform.pack()), esf.Val(7, c.uniform.path_id),
                            esf.Val(0x46, bytes(blob))]
                rows.append(row)
            gr.append(esf.Rec('grid_cells', items=rows))
            area_rows.append([verts, _array(0x48, area.polygon_words), esf.Rec('grid_data', children=gr)])
        children = {'pathfinding_areas': esf.Rec('pathfinding_areas', items=area_rows)}
        if self.obstacles is not None:
            children['obstacles'] = esf.Rec('obstacles', children=[esf.Val(0x46, self.obstacles)])
        if self.barriers is not None:
            rows = []
            for b in self.barriers:
                rows.append([esf.Val(0x0e, b.name)] +
                            [_array(0x48, (v & 0xffffffff for xy in outline for v in xy))
                             for outline in b.outlines_fixed])
            children['barriers'] = esf.Rec('barriers', items=rows)
        root = esf.Rec('root', children=[children[name] for name in self.root_order])
        return esf.dumps(esf.Esf(root, self.timestamp, list(self.names)))


def contact_mask(points, corners):
    """Verified top-byte order: E, NW, N, NE, SW, S, SE, W."""
    x0, y0 = corners[0]
    x1, y1 = corners[3]
    p = set(points)
    e = sum(x == x1 for x, y in p) >= 2
    w = sum(x == x0 for x, y in p) >= 2
    n = sum(y == y1 for x, y in p) >= 2
    s = sum(y == y0 for x, y in p) >= 2
    bits = (e, corners[1] in p, n, corners[3] in p,
            corners[0] in p, s, corners[2] in p, w)
    return sum(int(value) << i for i, value in enumerate(bits))


def rebuild_spatial_grid(area):
    """Retile all explicit mesh polygons and regenerate offsets, counts and masks.

    Uniform coverage, middle20, costs8 and region domains remain primary inputs.
    This does NOT invent those unknown fields from a land/sea bitmap. Geometry
    retains the implicit-corner convention, but cell ownership is recomputed
    from each polygon's absolute bounding box, not copied into the output.
    """
    g = area.grid
    if g.obfuscated:
        raise ValueError('cannot rebuild Spain obfuscated geometry')
    polys = area.polygons()
    assert polys[0] == (0, 2, 3, 1)
    tiles = [[] for _ in g.cells]
    used = {0}
    geometric_masks = 0
    for index, c in enumerate(g.cells):
        if not c.boundaries:                                  # uniform: nothing to retile
            continue
        corners = g.corners(index)
        x0, y0 = corners[0]
        x1, y1 = corners[3]
        tile_twice_area = 0
        for b in c.boundaries:
            ids = polys[b.polygon_offset]
            points = area.points(index, ids)
            assert all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in points)
            twice_area = sum(x * qy - y * qx for (x, y), (qx, qy)
                             in zip(points, points[1:] + points[:1]))
            assert twice_area > 0, "polygon must have positive CCW area"
            tile_twice_area += twice_area
            # Integer midpoint avoids a float rounding error at grid edges.
            cx = (min(p[0] for p in points) + max(p[0] for p in points)) // 2
            cy = (min(p[1] for p in points) + max(p[1] for p in points)) // 2
            col = (cx - g.origin_fixed[0]) // g.cell_size_fixed
            row = (cy - g.origin_fixed[1]) // g.cell_size_fixed
            target = row * g.columns + col
            assert target == index, (index, target)
            mask = 0 if b.trait.kind in (2, 3) else contact_mask(points, corners)
            assert mask == b.trait.contact_mask, (index, mask, b.trait.contact_mask)
            trait = Trait(b.trait.kind, b.trait.middle20, mask, b.trait.path_id)
            tiles[target].append((ids, trait))
            used.add(b.polygon_offset)
            geometric_masks += b.trait.kind not in (2, 3)
        assert tile_twice_area == 2 * g.cell_size_fixed ** 2, 'tile area mismatch'
    assert used == set(polys), 'unreferenced polygon'
    words = [4, 0, 2, 3, 1]
    cells = []
    for old, tile in zip(g.cells, tiles):
        boundaries = []
        for ids, trait in tile:
            boundaries.append(Boundary(trait, len(words)))
            words.extend((len(ids), *ids))
        cells.append(Cell(old.costs8, boundaries, old.uniform))
    count = sum(len(c.boundaries) or 1 for c in cells)
    return tuple(words), cells, count, geometric_masks


def generate(raster, origin, cell_size=2.0):
    """Return a geometry-only draft from a bottom-up 0=land,1=sea,2=blocked raster.

    Sketch for the raster compiler's first stage; intentionally returns no ESF.
    Each pixel becomes one full tile. A later compiler must assign region path
    domains, costs8, middle20 and startpos obstacles before encoding is valid.
    Polygonizing high-resolution input, clipping to 2-unit tiles and welding
    coordinates would replace this coarse one-pixel-per-tile sketch.
    """
    rows = [list(row) for row in raster]
    if not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError('raster must be nonempty and rectangular')
    if cell_size <= 0 or any(v not in (0, 1, 2) for row in rows for v in row):
        raise ValueError('positive cell size and classes 0,1,2 required')
    ox, oy = (round(v * SCALE) for v in origin)
    step = round(cell_size * SCALE)
    if step <= 0:
        raise ValueError('cell size below fixed-point precision')
    return [{'kind': kind, 'points_fixed': ((ox + x * step, oy + y * step),
            (ox + x * step, oy + (y + 1) * step),
            (ox + (x + 1) * step, oy + (y + 1) * step),
            (ox + (x + 1) * step, oy + y * step)),
            'missing': ('path_id', 'middle20', 'costs8', 'startpos overlay')}
            for y, row in enumerate(rows) for x, kind in enumerate(row)]


def _walk(rec):
    if isinstance(rec, esf.Rec):
        yield rec
        for child in rec.children:
            yield from _walk(child)
        for row in rec.items or ():
            for child in row:
                yield from _walk(child)


def inspect_startpos(path, area):
    """Decode and check concrete static/dynamic references; do not modify startpos."""
    source = esf.load(path)
    record, = [r for r in _walk(source.root) if r.name == 'CAMPAIGN_PATHFINDER']
    assert record.version == 5
    grid, = record.find('PATHFINDING_GRID').items
    path_words = _words(grid[1].value, 'I')
    paths, at = {}, 0
    while at < len(path_words):
        n = path_words[at]
        end = at + 2 * n + 2
        assert n >= 3 and end <= len(path_words)
        coords = tuple(((x + (1 << 31)) % (1 << 32)) - (1 << 31)
                       for x in path_words[at + 1:end - 1])
        paths[at] = (tuple(zip(coords[::2], coords[1::2])), path_words[end - 1])
        at = end
    assert len(paths) == grid[0].value
    nodes = grid[4].items
    lookup = _words(grid[5].value, 'I')
    assert len(lookup) == 2 * len(nodes)
    offsets = area.grid.trait_offsets()
    seen = set()
    for packed, index in zip(lookup[::2], lookup[1::2]):
        row, col = packed >> 16, packed & 65535
        assert 0 <= row < area.grid.rows and 0 <= col < area.grid.columns
        assert index < len(nodes) and index not in seen
        seen.add(index)
        linear = row * area.grid.columns + col
        node = nodes[index]
        assert node[0].value == offsets[linear]
        assert node[1].value == (len(area.grid.cells[linear].boundaries) or 1)
    assert len(seen) == len(nodes)
    overlay = _words(grid[3].children[0].value, 'I')
    static_offsets = area.polygons()
    at, count = 0, 0
    references = collections.Counter()
    while at < len(overlay):
        n = overlay[at]
        end = at + 2 * n + 3
        assert end <= len(overlay) and overlay[end - 1] == 0
        packed = overlay[end - 2]
        row, col = packed >> 16, packed & 65535
        assert row < area.grid.rows and col < area.grid.columns
        for word, ref in zip(overlay[at + 1:end - 2:2], overlay[at + 2:end - 2:2]):
            dynamic = bool(ref & (1 << 21))
            index = ref & ((1 << 21) - 1)
            references['dynamic' if dynamic else 'static'] += 1
            assert (index < len(paths) if dynamic else index in static_offsets), (dynamic, index)
        at, count = end, count + 1
    n_domains = len(area.grid.path_domains())
    assert len(grid[8].value) == n_domains
    assert len(grid[11].value) == 4 * n_domains
    return dict(grid_paths=len(paths), base_nodes=len(nodes), matched_base_nodes=len(seen),
                overlay_cells=count, overlay_references=dict(references),
                boundary_manager_entries=len(grid[2].children[0].items),
                characters=len(grid[6].find('CHARACTER_OBSTACLE').items),
                path_domain_flags=len(grid[8].value), path_domain_float_count=n_domains)


def correlate_wind_costs(area, regions_path):
    """Test the eight bytes against independent sea-wind data, without fitting ESF."""
    import numpy as np
    root = esf.load(regions_path).root
    theatre = root.find('theatres').items[0][0]
    wind = theatre.find('wind_map').children
    width, height, scale = (v.value for v in wind[:3])
    vectors = np.frombuffer(wind[3].value, dtype=np.int8).reshape(height, width, 2)
    lower, upper = theatre.children[1].value, theatre.children[2].value
    g = area.grid
    winds, costs = [], []
    for index, cell in enumerate(g.cells):
        if cell.uniform is None or cell.uniform.kind != 1 or 255 in cell.costs8:
            continue
        corners = g.corners(index)
        x = (corners[0][0] + corners[3][0]) / (2 * SCALE)
        y = (corners[0][1] + corners[3][1]) / (2 * SCALE)
        col = min(width - 1, int((x - lower[0]) / (upper[0] - lower[0]) * width))
        row = min(height - 1, int((y - lower[1]) / (upper[1] - lower[1]) * height))
        winds.append(vectors[row, col])
        costs.append(tuple(cell.costs8))
    winds, costs = np.asarray(winds, dtype=float), np.asarray(costs, dtype=float)
    cx = float(np.corrcoef(costs[:, 0] - costs[:, 7], winds[:, 0])[0, 1])
    cy = float(np.corrcoef(costs[:, 2] - costs[:, 5], winds[:, 1])[0, 1])
    assert cx > .99 and cy > .99
    return dict(samples=len(costs), east_west_windx_correlation=round(cx, 6),
                north_south_windy_correlation=round(cy, 6), wind_scale=scale)


def render(area, heightmap, output):
    from PIL import Image, ImageDraw
    # This diagnostic uses the verified Europe world box, not other maps' extents.
    image = Image.open(heightmap).convert('RGB')
    draw = ImageDraw.Draw(image)
    polys = area.polygons()
    colors = ((90, 225, 90), (60, 160, 255), (220, 80, 80), (180, 60, 230),
              (255, 210, 50), (255, 170, 60), (255, 255, 130), (255, 130, 180))
    for index, cell in enumerate(area.grid.cells):
        for b in cell.boundaries:
            points = area.points(index, polys[b.polygon_offset])
            pix = [((x / SCALE + 640) * image.width / 1280,
                    image.height - (y / SCALE + 320) * image.height / 640) for x, y in points]
            draw.line(pix + pix[:1], fill=colors[b.trait.kind % len(colors)], width=1)
    image.save(output)


def self_check():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    results, europe = {}, None
    assert generate([[0, 1], [2, 0]], (0, 0))[3]['points_fixed'][0] == (2 * SCALE, 2 * SCALE)
    for name in MAPS:
        path = DATA / 'campaign_maps' / name / 'pathfinding.esf'
        raw = path.read_bytes()
        model = PathfindingModel.load(path)
        encoded = model.encode()
        assert encoded == raw, f'{name}: semantic encoding differs'
        # Decode our newly encoded bytes into new semantic objects as well.
        assert PathfindingModel.decode(esf.loads(encoded)).encode() == raw
        a, = model.areas
        g = a.grid
        result = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                      vertices=len(a.vertices_fixed), expanded_cells=len(g.cells),
                      explicit_boundaries=sum(len(c.boundaries) for c in g.cells),
                      obfuscated=g.obfuscated)
        if not g.obfuscated:
            assert len(g.cells) == g.columns * g.rows
            assert a.vertices_fixed[:4] == ((SENTINEL, SENTINEL),) * 4
            assert len(g.region_indices) == g.listed_region_count
            words, cells, count, masks = rebuild_spatial_grid(a)
            assert words == a.polygon_words
            assert cells == g.cells
            assert count == g.trait_count
            domains = g.path_domains()
            assert all(b.trait.path_id == 1023 or b.trait.path_id < len(domains)
                       for c in cells for b in c.boundaries)
            assert all(c.uniform is None or c.uniform.path_id == 1023
                       or c.uniform.path_id < len(domains) for c in cells)
            regions = esf.load(path.with_name('regions.esf')).root.find('region_data').find('regions').items
            assert all(0 <= r < len(regions) for r in g.region_indices)
            # Derived counts actually flow through the encoder, rather than just a comparison.
            a.polygon_words, g.cells, g.trait_count = words, cells, count
            assert model.encode() == raw
            result.update(polygons=len(a.polygons()), columns=g.columns, rows=g.rows,
                          trait_count=count, path_domains=len(domains), verified_contact_masks=masks,
                          grid_rebuild='byte-exact')
        results[name] = result
        if name == 'nap_europe':
            europe = model
        print(f'{name}: semantic round-trip OK ({len(raw):,} bytes); ' +
              ('opaque geometry preserved; expanded cells=' + str(len(g.cells)) if g.obfuscated else
               f'grid rebuild OK; cells={len(g.cells)}, polygons={len(a.polygons())}, masks={masks}'))
    area = europe.areas[0]
    # Mutation check proves encoding uses semantic state and does not replay source bytes.
    old = area.grid.cells[0].costs8
    area.grid.cells[0].costs8 = bytes([old[0] ^ 1]) + old[1:]
    changed = PathfindingModel.decode(esf.loads(europe.encode()))
    assert changed.areas[0].grid.cells[0].costs8 != old
    area.grid.cells[0].costs8 = old
    start = inspect_startpos(DATA / 'campaigns/mp_eur_napoleon/startpos.esf', area)
    results['startpos'] = start
    wind = correlate_wind_costs(area, DATA / 'campaign_maps/nap_europe/regions.esf')
    results['wind'] = wind
    print('wind/cost correlation: ' + json.dumps(wind, sort_keys=True))
    print('startpos: ' + json.dumps(start, sort_keys=True))
    png = SCRATCH / 'europe_mesh_verified.png'
    render(area, DATA / 'campaign_maps/nap_europe/display/heightmap/heightmap.tga', png)
    (SCRATCH / 'self_check.json').write_text(json.dumps(results, indent=2) + '\n')
    print('mutation check OK; raster geometry draft OK')
    print('diagnostics: ' + str(png))
    print('PASS: static checks only; middle20/costs8/Spain cipher and runtime acceptance remain unresolved')


if __name__ == '__main__':
    self_check()
