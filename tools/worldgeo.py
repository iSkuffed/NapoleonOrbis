"""World land/water geometry in world units (tools/proj.py), the shared input of every Phase 4 bake.

Natural Earth 10m land + minor islands, minus 10m lakes (public domain). Rings are cut at the seam, densified to 0.1 deg
before projecting (the projection is piecewise linear), and clipped to the theatre. Cached as WKB in work/world/.
land() removes every NE lake: the geometry stages (regions, pathfinding) read it, so their output never moves.
land(natural=True), for the display bakes (terrain, trees), drops dams: featurecla 'Reservoir' is land in 1805 unless
NATURAL_LAKES lists it (natural lakes dammed later). The reservoirs are pure holes, so both have the same lake-filled
outline (work/scratch/features/res_verify.py).

  python tools/worldgeo.py            # build cache + self-check (vanilla-theatre agreement with vanilla pathfinding)
  python tools/worldgeo.py preview    # work/world/land_preview.png
"""
import io, os, sys, zipfile
import numpy as np
import shapely
from shapely.geometry import box, Polygon, MultiPolygon

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proj

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEODATA, CACHE = os.path.join(ROOT, 'work/geodata'), os.path.join(ROOT, 'work/world')
THEATRE = box(*proj.THEATRE_MIN, *proj.THEATRE_MAX)
VANILLA = box(*proj.VT_MIN, *proj.VT_MAX)


# ne_10m_lakes 'Reservoir' features that are natural lakes regulated or raised by a later dam, so already water in 1805
# (the 'Reservoir' class also covers these: research/16 §3.1). NE name -> NE dam_name/year or note, and the natural lake.
NATURAL_LAKES = {
    "Lake Il'Men'": 'Volkhov 1926; Lake Ilmen',
    'Mjøsa': "Norway's largest lake, regulated",
    'Lake Zaysan': 'Bukhtarma 1960 raised it; Lake Zaysan',
    'Oulujärvi': 'Jylhama 1950; Lake Oulu',
    'Ozero Kubenskoye': 'Kubenskoye Dam 1917; Lake Kubenskoye',
    'Koitere': 'Kaltimo 1958; Lake Koitere',
    'Rikkavesi': 'Puntarikoski 1957; Lake Rikkavesi',
    'Ondozero': 'Onda 1956; Lake Ondozero',
    'Lake Kovdozero': 'Verkhne-Tulomskaya 1965 raised it; Lake Kovdozero',
    'Lake Imandra': 'Kumskaya 1963; Lake Imandra',
    'Umbozero Lake': 'Iova 1960; Lake Umbozero',
    'Kemijärvi': 'Seitakorva 1968; Lake Kemijärvi',
    'Stora Lulevatten': 'Suorva 1972 raised it; Lake Stora Lulevatten',
    'Cedar Lake': 'Grand Rapids 1965 raised it; Cedar Lake (Manitoba)',
    'Southern Indian Lake': 'Missi Falls 1976 raised it; Southern Indian Lake',
    'Lac Seul': 'Ear Falls, raised; Lac Seul',
    'Lac Saint-Jean': 'Isle Maligne 1925; Lac Saint-Jean',
    'Lake Abitibi': 'Twin Falls 1921; Lake Abitibi',
    'Lake Chelan': '1927 dam raised it; Lake Chelan',
    'Upper Arrow Lake': 'Keenleyside 1960 raised it; Arrow Lakes',
    'Lower Arrow Lake': 'Keenleyside 1960 raised it; Arrow Lakes',
    'Lake Te Anau': "NE note 'Natural lake'",
    'Lake Manapouri': "NE note 'natural lake used for hydro-electric power'",
    'Lake Pukaki': "NE note 'natural lake'",
    'Lake Hawea': "NE note 'natural lake'",
    'Lake Waikaremoana': "NE note 'natural lake'",
    'Lake Coleridge': "NE note 'natural lake'",
    'Lake Monowai': "NE note 'natural lake'",
}


def _shapes(name, keep=None):
    """Geometries of a Natural Earth zip; keep(record dict) filters."""
    import shapefile
    z = zipfile.ZipFile(os.path.join(GEODATA, name + '.zip'))
    r = shapefile.Reader(shp=io.BytesIO(z.read(name + '.shp')), dbf=io.BytesIO(z.read(name + '.dbf')))
    f = [x[0] for x in r.fields[1:]]
    for sr in r.iterShapeRecords():
        if keep is None or keep(dict(zip(f, sr.record))):
            yield shapely.geometry.shape(sr.shape.__geo_interface__)


def natural_lake(d):
    return d['featurecla'] != 'Reservoir' or d['name'] in NATURAL_LAKES


def src_tag(*parts):
    """Short hash of strings/functions (their source): cache names carry it, so an edit never reuses stale data."""
    import hashlib, inspect
    return hashlib.sha1(''.join(p if isinstance(p, str) else inspect.getsource(p) for p in parts).encode()).hexdigest()[:8]


NATURAL_TAG = src_tag(repr(sorted(NATURAL_LAKES)), natural_lake)


def _lonlat_to_world(g):
    """Seam-cut, densify, project one lon/lat (multi)polygon."""
    lat0, lat1 = proj.to_lonlat(0, [proj.THEATRE_MIN[1], proj.THEATRE_MAX[1]])[1]
    strip = box(proj.SEAM, lat0, proj.SEAM + 360, lat1)
    parts = []
    for k in (-360, 0, 360):
        q = shapely.affinity.translate(g, k).intersection(strip)
        if not q.is_empty:
            parts.append(q)
    g = shapely.segmentize(shapely.union_all(parts), 0.1)
    return shapely.make_valid(shapely.transform(g, lambda c: np.column_stack(proj.to_world(c[:, 0], c[:, 1], wrap=False))))


def _load(name, keep=None):
    return shapely.union_all([_lonlat_to_world(shapely.make_valid(g)) for g in _shapes(name, keep)])


def land(natural=False):
    """World-unit land (MultiPolygon) over the theatre, lakes removed (natural=True: natural lakes only). Cached."""
    path = os.path.join(CACHE, f'land_natural_{NATURAL_TAG}.wkb' if natural else 'land.wkb')
    if os.path.exists(path):
        return shapely.from_wkb(open(path, 'rb').read())
    os.makedirs(CACHE, exist_ok=True)
    g = shapely.union_all([_load('ne_10m_land'), _load('ne_10m_minor_islands')])
    g = g.difference(_load('ne_10m_lakes', natural_lake if natural else None)).intersection(THEATRE)
    g = shapely.make_valid(g)
    open(path, 'wb').write(shapely.to_wkb(g))
    return g


def mask(geom, ppu, lo=proj.BOX_MIN, hi=proj.BOX_MAX):
    """bool raster of geom over lo..hi at ppu pixels/unit, row 0 = north (like the vanilla TGAs)."""
    from PIL import Image, ImageDraw
    w, h = int(round((hi[0] - lo[0]) * ppu)), int(round((hi[1] - lo[1]) * ppu))
    img = Image.new('1', (w, h)); d = ImageDraw.Draw(img)
    px = lambda c: [((x - lo[0]) * ppu, (hi[1] - y) * ppu) for x, y in c]
    for p in getattr(geom, 'geoms', [geom]):
        if p.geom_type != 'Polygon' or p.is_empty:
            continue
        d.polygon(px(p.exterior.coords), fill=1)
        for r in p.interiors:
            d.polygon(px(r.coords), fill=0)
    return np.array(img, bool)


def _selfcheck():
    import pathfinding_model as pm, geo
    g = land()
    a = shapely.area(g)
    print(f'land: {len(g.geoms)} polygons, {a:.0f} u^2 ({a / shapely.area(THEATRE):.1%} of theatre)')
    # inside the vanilla theatre, NE land under this projection should agree with vanilla land/sea cells
    grid = pm.PathfindingModel.load(geo.GAME + '/campaign_maps/nap_europe/pathfinding.esf').areas[0].grid
    m = mask(g, 0.5, proj.VT_MIN, proj.VT_MAX)                       # one pixel per 2-unit cell
    agree = total = 0
    for i, c in enumerate(grid.cells):
        if not c.uniform or c.uniform.kind not in (0, 1):
            continue
        r, col = divmod(i, grid.columns)
        if r >= m.shape[0] or col >= m.shape[1]:
            continue
        total += 1
        agree += m[m.shape[0] - 1 - r, col] == (c.uniform.kind == 0)
    print(f'vanilla agreement on {total} uniform cells: {agree / total:.1%}')
    assert agree / total > 0.9
    # no seam-wrap slivers: nothing wide and hairline-thin
    thin = [p.bounds for p in g.geoms if p.bounds[2] - p.bounds[0] > 100 and p.bounds[3] - p.bounds[1] < 1]
    def long_edges(c):
        c = np.asarray(c)
        on_edge = np.isin(c[:-1, 1], proj.THEATRE_MIN[1:] + proj.THEATRE_MAX[1:]) & (c[:-1, 1] == c[1:, 1])
        return int(((np.abs(np.diff(c[:, 0])) > 300) & ~on_edge).sum())
    spikes = sum(long_edges(r.coords) for p in g.geoms for r in [p.exterior, *p.interiors])
    assert not spikes, f'{spikes} long ring edges (seam wrap?)'


if __name__ == '__main__':
    if sys.argv[1:] == ['preview']:
        from PIL import Image
        Image.fromarray(mask(land(), 0.25)).save(os.path.join(CACHE, 'land_preview.png'))
    else:
        _selfcheck()
