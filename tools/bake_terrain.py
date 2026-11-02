"""Bake the world campaign map's terrain rasters into work/world/terrain/ (Phase 4 lane B).

  heightmap.tga                 12288x8192 L8 (3.2 px/u), whole box (-1920,-1280)..(1920,1280)
  supertexture.stpi/.stpd       98304x65536 level 0 (25.6 texels/u), 6 levels, 512-px DXT5+zlib tiles
  campaign_detail_mask.dds      3072x2048 DXT3 + mips (0.8 px/u)

Vanilla nap_europe is kept, unchanged, only where vanilla PAINTED the map: the "painted" mask is the torn map sheet,
i.e. the connected non-parchment region around the map centre on vanilla's supertexture level 2 (holes filled, the
torn-edge outline eroded away); it lies inside VT (tools/proj.py, identity projection there). Inside it, heightmap
pixels and supertexture/detail texels are bit-identical to vanilla: supertexture and detail-mask DXT blocks are vanilla's
own blocks (the vanilla grids are 4-texel aligned at every level), and supertexture tiles wholly painted are vanilla's
tile bytes. Everywhere else (outside VT, and VT's parchment frame: Anatolia, Caucasus, North Africa, north Scandinavia):
  - land/sea from worldgeo.land(natural=True) (alpha 255 = water, like vanilla),
  - land colour = NASA Blue Marble Next Generation (July 2004, 21600x10800; NASA imagery, not subject to US copyright,
    credit NASA Earth Observatory) quantile-matched per channel to vanilla's painted land,
  - sea colour = distance from the coast -> vanilla painted-sea colour (median per distance bin, as vanilla paints a
    light coastal halo fading to one blue-grey; constant beyond 30 u, so open-ocean tiles deduplicate),
  - heightmap = ETOPO roughness (local std + positive relief above a 40-px low-pass; scores ~2x better than absolute
    elevation against vanilla) quantile-matched to vanilla painted land, sea 0,
  - detail mask RGB = mean vanilla detail weights per vanilla heightmap value, applied to our heightmap.
Feather: over FEATHER units on the generated side of the painted edge, colour/height blends from vanilla's nearest
painted value (mask-normalised 0.5-unit blur of the painted side) into the generated one (painted side untouched). Coarser supertexture levels are 2x2 means of their
children, with vanilla level-L texels on the painted mask.

  python tools/bake_terrain.py all                       # full bake (prep caches, heightmap, supertexture, detail, check)
  python tools/bake_terrain.py heightmap|supertexture|detail|check
  python tools/bake_terrain.py region X0 Y0 X1 Y1        # level-0 preview of a world window -> region_l0.png
  python tools/bake_terrain.py                           # = check (asserts identity on the painted mask)
"""
import os, shutil, struct, sys, time, zlib
import multiprocessing
Pool = multiprocessing.get_context("fork").Pool   # workers inherit _G (py3.14 defaults to forkserver)
import numpy as np
import shapely
from shapely.geometry import MultiPolygon
from PIL import Image
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import display, geo, proj, worldgeo

Image.MAX_IMAGE_PIXELS = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'work/world/terrain')
CACHE = os.path.join(OUT, 'cache')
BMNG = os.path.join(ROOT, 'work/geodata/bmng/world.200407.3x21600x10800.jpg')
VAN = geo.GAME + '/campaign_maps/nap_europe/display'
VSTPI, VSTPD = VAN + '/supertexture/supertexture.stpi', VAN + '/supertexture/supertexture.stpd'
VDETAIL = VAN + '/detail/campaign_detail_mask.dds'

(BX0, BY0), (BX1, BY1) = proj.BOX_MIN, proj.BOX_MAX
(VX0, VY0), (VX1, VY1) = proj.VT_MIN, proj.VT_MAX
(TX0, TY0), (TX1, TY1) = proj.THEATRE_MIN, proj.THEATRE_MAX
VBOX = (-640, -320, 640, 320)               # vanilla world box
ST = display.SUPERTEXTURE_PX_PER_UNIT       # 25.6
P2 = ST / 4                                 # 6.4 px/u: vanilla level-2 grid, where the painted mask is defined
W0, H0 = int((BX1 - BX0) * ST), int((BY1 - BY0) * ST)   # 98304 x 65536
NLEV, T, NB = 6, display.TILE, display.TILE // 4        # NB = DXT blocks per tile side
VOFF = (int((VBOX[0] - BX0) * ST), int((BY1 - VBOX[3]) * ST))   # vanilla level-0 origin in new texels (32768, 24576)
FEATHER = 3.0                                # world units, on the generated side of the painted edge
EDGE_TRIM = 9.0                              # units trimmed off the torn edge: its outline, paper fibres and burnt
                                             # shading band (vanilla darkens ~1-3 u inside the edge)
PARCHMENT = np.array([206, 182, 112])        # vanilla frame colour
NPROC = max(1, (os.cpu_count() or 2) - 2)


# ---------------------------------------------------------------- shared helpers
def lonlat(x, y):
    """Separable projection: x (cols) -> lon, y (rows) -> lat, clamped to the theatre (outside it is filler)."""
    lon, _ = proj.to_lonlat(np.clip(x, TX0, TX1 - 1e-6), np.zeros_like(x))
    _, lat = proj.to_lonlat(np.zeros_like(y), np.clip(y, TY0, TY1))
    return lon, lat


def _frac(f, n, wrap):
    f = f - 0.5
    i0 = np.floor(f).astype(np.int64)
    t = (f - i0).astype(np.float32)
    i1 = i0 + 1
    return (i0 % n, i1 % n, t) if wrap else (np.clip(i0, 0, n - 1), np.clip(i1, 0, n - 1), t)


def sample_ll(grid, lat, lon):
    """Bilinear sample of a north-up global 1/60-degree grid (rows = lat, cols = lon, like BMNG) on the separable
    grid lat (rows) x lon (cols) -> float32 (len(lat), len(lon)[, C])."""
    return sample_rc(grid, (90 - lat) * 60, (lon + 180) * 60, True)


def sample_xy(grid, x, y, ppu):
    """Bilinear sample of a whole-box raster at ppu on world columns x, rows y."""
    return sample_rc(grid, (BY1 - y) * ppu, (x - BX0) * ppu, False)


def sample_rc(grid, rf, cf, wrap):
    H, W = grid.shape[:2]
    r0, r1, tr = _frac(rf, H, False)
    c0, c1, tc = _frac(cf, W, wrap)
    lo, hi = int(r0.min()), int(r1.max())
    sub = grid[lo:hi + 1]
    ex = (slice(None),) + (None,) * (grid.ndim - 1)
    tc = tc[(None, slice(None)) + (None,) * (grid.ndim - 2)]
    cols = sub[:, c0].astype(np.float32) * (1 - tc) + sub[:, c1].astype(np.float32) * tc
    return cols[r0 - lo] * (1 - tr[ex]) + cols[r1 - lo] * tr[ex]


def texel_xy(L, X0, Y0, n=T):
    """World coords of level-L texel centres for columns X0.. and rows Y0.. (new-box texel indices)."""
    ppu = ST / (1 << L)
    return BX0 + (X0 + np.arange(n) + 0.5) / ppu, BY1 - (Y0 + np.arange(n) + 0.5) / ppu


def half(a):
    return np.round(a.reshape(a.shape[0] // 2, 2, a.shape[1] // 2, 2, -1).astype(np.float32).mean((1, 3))).astype(np.uint8)


def pool_all(m, k):
    return m if k == 1 else m.reshape(m.shape[0] // k, k, m.shape[1] // k, k).all((1, 3))


def blocks_up(b, k=4):
    return np.repeat(np.repeat(b, k, 0), k, 1)


def vanilla_level(L):
    """Vanilla supertexture level L (L >= 2) as uint8 RGBA over the vanilla box, cached."""
    p = os.path.join(CACHE, f'van_l{L}.npy')
    if not os.path.exists(p):
        np.save(p, np.asarray(display.read_level_image(VSTPI, VSTPD, L)))
    return np.load(p, mmap_mode='r')


def vt_crop_coords(ppu):
    """Pixel slices of VT inside a vanilla-box raster at ppu, and the world coords of those pixel centres."""
    c0, c1 = int((VX0 - VBOX[0]) * ppu), int((VX1 - VBOX[0]) * ppu)
    r0, r1 = int((VBOX[3] - VY1) * ppu), int((VBOX[3] - VY0) * ppu)
    xs = VX0 + (np.arange(c1 - c0) + 0.5) / ppu
    ys = VY1 - (np.arange(r1 - r0) + 0.5) / ppu
    return (slice(r0, r1), slice(c0, c1)), xs, ys


def pad_vanilla(v, ppu, fill=0):
    """Vanilla-box raster -> whole-box raster (fill outside the vanilla box)."""
    out = np.full((int((BY1 - BY0) * ppu), int((BX1 - BX0) * ppu)) + v.shape[2:], fill, v.dtype)
    r0, c0 = int((BY1 - VBOX[3]) * ppu), int((VBOX[0] - BX0) * ppu)
    out[r0:r0 + v.shape[0], c0:c0 + v.shape[1]] = v
    return out


# ---------------------------------------------------------------- painted mask
def painted():
    """bool (4096, 8192) on vanilla's level-2 grid (6.4 px/u over the vanilla box): vanilla's painted map sheet."""
    p = os.path.join(CACHE, 'painted_l2.npy')
    if os.path.exists(p):
        return np.load(p)
    a = vanilla_level(2)
    parch = (a[..., 3] < 128) & (np.abs(a[..., :3].astype(np.int16) - PARCHMENT).sum(-1) <= 90)
    parch = ndimage.binary_closing(parch, iterations=3)          # swallow the grid lines drawn on the parchment
    lab, _ = ndimage.label(~parch)
    k = lab[a.shape[0] // 2, a.shape[1] // 2]                     # world (0, 0) is on the map
    assert k
    m = ndimage.binary_fill_holes(lab == k)                      # light painted patches (e.g. Hungarian plain)
    m = ndimage.distance_transform_edt(m) > EDGE_TRIM * P2      # drop the torn edge's outline/fibres/shading
    (rs, cs), _, _ = vt_crop_coords(P2)
    assert not (m.sum() - m[rs, cs].sum()), 'painted map leaves VT'
    np.save(p, m)
    return m


def fields(k):
    """Painted mask on the level-2 grid pooled by k (k=2: 3.2 px/u, 8: 0.8 px/u) and distance outside it in units."""
    m = pool_all(painted(), k)
    return m, (ndimage.distance_transform_edt(~m) * k / P2).astype(np.float32)


def extend(van, m, ppu, sigma=0.5):
    """Vanilla values carried off the painted mask m: mask-normalised gaussian (sigma units) of the painted values,
    nearest-filled where that has no support. Smooth along the torn edge (no nearest-pixel streaks)."""
    v = van.astype(np.float32).reshape(van.shape[:2] + (-1,))
    sp = sigma * ppu
    den = ndimage.gaussian_filter(m.astype(np.float32), sp)
    ext = np.stack([ndimage.gaussian_filter(v[..., c] * m, sp) for c in range(v.shape[2])], -1) / np.maximum(den, 1e-6)[..., None]
    idx = ndimage.distance_transform_edt(den < 0.05, return_distances=False, return_indices=True)
    ext = ext[idx[0], idx[1]]
    return ext.reshape(van.shape)


def paint_composite(gen, van, k, ppu, chans=None):
    """Whole-box raster gen (float) + vanilla-box raster van on the level-2/k grid -> (out, painted whole-box mask).
    Painted: vanilla exactly. Within FEATHER units outside: blend from vanilla's nearest painted value (chans only)."""
    m, d = fields(k)
    r0, c0 = int((BY1 - VBOX[3]) * ppu), int((VBOX[0] - BX0) * ppu)
    sl = (slice(r0, r0 + m.shape[0]), slice(c0, c0 + m.shape[1]))
    out = gen.astype(np.float32)
    reg = out[sl]
    w = np.clip(1 - d / FEATHER, 0, 1)
    ext = extend(van, m, ppu)
    if van.ndim == 3:
        chans = chans or slice(None)
        reg[..., chans] = w[..., None] * ext[..., chans] + (1 - w[..., None]) * reg[..., chans]
    else:
        reg[:] = w * ext + (1 - w) * reg
    reg[m] = van[m]
    return out, pad_vanilla(m, ppu, False)


# ---------------------------------------------------------------- source preparation (cached)
def etopo():
    """ETOPO 2022 60s surface as int16 metres, north-up (BMNG orientation), memmapped."""
    p = os.path.join(CACHE, 'etopo_n.npy')
    if not os.path.exists(p):
        import h5py
        z = h5py.File(geo.ETOPO)['z'][:]
        np.save(p, np.clip(np.round(z[::-1]), -32768, 32767).astype(np.int16))
    return np.load(p, mmap_mode='r')


def _vt_samples():
    """Vanilla level 3 over VT, its painted mask minus a 4-unit band along the torn edge (paper shading), and world
    coords of the pixel centres."""
    (rs, cs), xs, ys = vt_crop_coords(3.2)
    pm = pool_all(painted(), 2)
    core = ndimage.distance_transform_edt(pm) / 3.2 > 4
    return np.asarray(vanilla_level(3)[rs, cs]), core[rs, cs], xs, ys


def sea_lut():
    """(coast-distance knots in units, RGB): vanilla paints the sea by distance from the coast (a light halo fading to
    one dark blue-grey ~20 u out), not by depth. Median painted-sea colour per distance bin; flat beyond 30 u."""
    v, pm, xs, ys = _vt_samples()
    sea = v[..., 3] >= 128
    d = ndimage.distance_transform_edt(sea) / 3.2
    m0 = pm & sea
    d, rgb = d[m0], v[m0][:, :3].astype(np.float32)
    edges = [0.3, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30]
    knots, cols = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (d >= a) & (d < b)
        knots.append(np.median(d[m])); cols.append(np.median(rgb[m], 0))
    knots.append(30.0); cols.append(np.median(rgb[d >= 20], 0))
    return np.array(knots), np.round(np.array(cols))


def coast_dist():
    """Distance (units) from worldgeo land over the whole box at 3.2 px/u, float16, cached."""
    p = os.path.join(CACHE, f'coastdist_{worldgeo.NATURAL_TAG}.npy')
    if not os.path.exists(p):
        land = worldgeo.mask(worldgeo.land(natural=True), 3.2)
        np.save(p, (ndimage.distance_transform_edt(~land) / 3.2).astype(np.float16))
    return np.load(p, mmap_mode='r')


SEA_FADE, SEA_SIGMA = 40.0, 8.0   # units


def region_offset(res, use):
    """Regional palette correction: res = vanilla minus the generator's colour on the VT crop at 3.2 px/u, averaged
    over the use pixels, smoothed (SEA_SIGMA), carried off the painted mask and faded out over SEA_FADE units, so
    generated terrain meets painted terrain at its local tone (vanilla's central Mediterranean is darker than its
    Atlantic, its Lapland lighter than Blue Marble's). Whole box at 0.8 px/u, float32 RGB."""
    h, w = use.shape[0] // 4, use.shape[1] // 4
    num = np.zeros((int((BY1 - BY0) * 0.8), int((BX1 - BX0) * 0.8), 3), np.float32)
    cnt = np.zeros(num.shape[:2], np.float32)
    r0, c0 = int((BY1 - VY1) * 0.8), int((VX0 - BX0) * 0.8)
    num[r0:r0 + h, c0:c0 + w] = (res * use[..., None]).reshape(h, 4, w, 4, 3).sum((1, 3)) / 16
    cnt[r0:r0 + h, c0:c0 + w] = use.reshape(h, 4, w, 4).sum((1, 3)) / 16

    def nconv(sigma):
        den = ndimage.gaussian_filter(cnt, sigma * 0.8)
        o = np.stack([ndimage.gaussian_filter(num[..., c], sigma * 0.8) for c in range(3)], -1)
        return o / np.maximum(den, 1e-6)[..., None], den
    o1, d1 = nconv(SEA_SIGMA)
    o3, d3 = nconv(3 * SEA_SIGMA)        # wider support, so the correction never ends in a hard edge
    a = np.clip(d1 / 0.1, 0, 1)[..., None]
    off = np.clip(a * o1 + (1 - a) * o3 * np.clip(d3 / 0.05, 0, 1)[..., None], -40, 40)
    dout = ndimage.distance_transform_edt(~pad_vanilla(pool_all(painted(), 8), 0.8, False)) / 0.8
    return (off * np.clip(1 - dout / SEA_FADE, 0, 1)[..., None]).astype(np.float32)


def offsets(lut, bmng):
    """(sea, land) regional offsets, trained on painted vanilla level 3 more than 1 unit inside the painted edge."""
    (rs, cs), xs, ys = vt_crop_coords(3.2)
    pm = pool_all(painted(), 2)
    v = np.asarray(vanilla_level(3)[rs, cs])
    sea = v[..., 3] >= 128
    inner = (ndimage.distance_transform_edt(pm) / 3.2 > 1)[rs, cs]
    seares = v[..., :3] - sea_rgb(ndimage.distance_transform_edt(sea) / 3.2, lut)
    lon, lat = lonlat(xs, ys)
    landres = v[..., :3] - sample_ll(bmng, lat, lon)
    return region_offset(seares, inner & sea), region_offset(landres, inner & ~sea)


def sea_rgb(dist, lut):
    k, c = lut
    return np.stack([np.interp(dist, k, c[:, ch]) for ch in range(3)], -1)


def dams(shape):
    """Global 1/60-degree mask of the NE reservoirs that worldgeo.land(natural=True) makes land (BMNG shows them as dark,
    not blue, water), grown 2 px for the generalised outlines."""
    from PIL import ImageDraw
    H, W = shape
    img = Image.new('L', (W, H)); d = ImageDraw.Draw(img)
    px = lambda c: [((x + 180) * 60, (90 - y) * 60) for x, y in c]
    for g in worldgeo._shapes('ne_10m_lakes', lambda r: not worldgeo.natural_lake(r)):
        for p in getattr(g, 'geoms', [g]):
            d.polygon(px(p.exterior.coords), fill=1)
            for q in p.interiors:
                d.polygon(px(q.coords), fill=0)
    return ndimage.binary_dilation(np.asarray(img, bool), iterations=2)


def bmng_prep():
    """BMNG with water/ice-free land colour everywhere (water pixels filled from the nearest land), then mapped
    per channel to vanilla's land palette. uint8 (10800, 21600, 3), memmapped."""
    p = os.path.join(CACHE, f'bmng_prep_{worldgeo.src_tag(worldgeo.NATURAL_TAG, dams)}.npy')
    if os.path.exists(p):
        return np.load(p, mmap_mode='r')
    t0 = time.time()
    a = np.asarray(Image.open(BMNG).convert('RGB'))
    z = etopo()
    r, g, b = (a[..., k].astype(np.int16) for k in range(3))
    # water / lake / coast-blend pixels: ETOPO sea, or bluish-dark (land is greener or redder than blue; snow is bright)
    water = (np.asarray(z) <= 0) | ((b >= r) & (b + 8 >= g) & (r + g + b < 330)) | dams(a.shape[:2])
    del r, g, b
    valid = ~ndimage.binary_dilation(water)      # also drop the 1-px JPEG blend fringe along every shore
    del water
    # fill invalid pixels from a 2x coarser valid-weighted mean, nearest-neighbour filled, lightly smoothed
    k = 2
    H, W = valid.shape
    vw = valid.reshape(H // k, k, W // k, k).sum((1, 3)).astype(np.float32)
    cs = np.stack([(a[..., c] * valid).reshape(H // k, k, W // k, k).sum((1, 3)) for c in range(3)], -1)
    ok = vw > 0
    coarse = np.where(ok[..., None], cs / np.maximum(vw, 1)[..., None], 0).astype(np.uint8)
    del cs, vw
    idx = ndimage.distance_transform_edt(~ok, return_distances=False, return_indices=True).astype(np.int32)
    coarse = coarse[idx[0], idx[1]]
    del idx
    up = ndimage.uniform_filter(np.repeat(np.repeat(coarse, k, 0), k, 1), (3, 3, 1))
    a = np.where(valid[..., None], a, up)
    del up
    lut = land_lut(a)
    ice = np.clip((a.min(-1).astype(np.float32) - 150) / 60, 0, 1)[..., None]   # snow/ice: keep a cool white,
    for c in range(3):                                                         # not vanilla's parchment cream
        a[..., c] = lut[c][a[..., c]]
    a[:] = np.round((1 - ice) * a + ice * np.asarray(Image.open(BMNG).convert('RGB')) * 0.92).astype(np.uint8)
    np.save(p, a)
    print(f'bmng prep {time.time() - t0:.0f}s')
    return np.load(p, mmap_mode='r')


def land_lut(filled):
    """Per-channel quantile map BMNG -> vanilla land, trained on painted VT land pixels."""
    v, pm, xs, ys = _vt_samples()
    lon, lat = lonlat(xs, ys)
    s = sample_ll(filled, lat, lon)
    land = worldgeo.mask(worldgeo.land(natural=True), 3.2, proj.VT_MIN, proj.VT_MAX)
    m = land & pm & (v[..., 3] == 0)
    q = np.linspace(0, 100, 257)
    lut = []
    for c in range(3):
        sq, vq = np.percentile(s[m][:, c], q), np.percentile(v[m][:, c].astype(np.float32), q)
        sq = np.maximum.accumulate(sq + np.arange(len(sq)) * 1e-6)
        lut.append(np.clip(np.round(np.interp(np.arange(256), sq, vq)), 0, 255).astype(np.uint8))
    return lut


# ---------------------------------------------------------------- heightmap
def roughness(z):
    """Local std (3 px) + 0.5 * relief above a 40-px low-pass, on land elevation (ETOPO px, lon-wrapped)."""
    zl = np.maximum(z.astype(np.float32), 0)
    mode = ['nearest', 'wrap']
    m = ndimage.gaussian_filter(zl, 3, mode=mode)
    sd = np.sqrt(np.maximum(ndimage.gaussian_filter(zl * zl, 3, mode=mode) - m * m, 0))
    del m
    return sd + 0.5 * np.maximum(zl - ndimage.gaussian_filter(zl, 40, mode=mode), 0)


def bake_heightmap():
    t0 = time.time()
    ppu = 3.2
    van = np.array(Image.open(VAN + '/heightmap/heightmap.tga'))
    w, h = int((BX1 - BX0) * ppu), int((BY1 - BY0) * ppu)
    xs, ys = BX0 + (np.arange(w) + 0.5) / ppu, BY1 - (np.arange(h) + 0.5) / ppu
    lon, lat = lonlat(xs, ys)
    z = etopo()
    # roughness only over the theatre latitudes (+ filter margin)
    rlo, rhi = int((90 - lat.max()) * 60) - 200, int((90 - lat.min()) * 60) + 200
    rough = np.zeros(z.shape, np.float32)
    rough[rlo:rhi] = roughness(z[rlo:rhi])
    g = np.empty((h, w), np.float32)
    for r in range(0, h, 512):
        g[r:r + 512] = sample_ll(rough, lat[r:r + 512], lon)
    del rough
    land = worldgeo.mask(worldgeo.land(natural=True), ppu)
    # calibrate on painted land: quantiles of roughness -> quantiles of vanilla heightmap
    pm = pad_vanilla(pool_all(painted(), 2), ppu, False)
    m = land & pm
    q = np.linspace(0, 100, 401)
    gq, hq = np.percentile(g[m], q), np.percentile(pad_vanilla(van, ppu)[m].astype(np.float32), q)
    gq = np.maximum.accumulate(gq + np.arange(len(gq)) * 1e-6)
    gen = np.where(land, np.interp(g, gq, hq), 0).astype(np.float32)
    del g
    out, pm = paint_composite(gen, van, 2, ppu)
    out = np.clip(np.round(out), 0, 255).astype(np.uint8)
    open(os.path.join(OUT, 'heightmap.tga'), 'wb').write(display.write_l8_tga(out))
    pv = out.reshape(h // 4, 4, w // 4, 4).max((1, 3))
    Image.fromarray(np.minimum(255, pv.astype(int) * 3).astype(np.uint8)).save(os.path.join(OUT, 'heightmap_preview.png'))
    print(f'heightmap {w}x{h} written ({time.time() - t0:.0f}s); land>0 frac: generated {(out[land & ~pm] > 0).mean():.1%}, '
          f'painted {(out[land & pm] > 0).mean():.1%}')
    return out


# ---------------------------------------------------------------- supertexture
_G = {}   # worker globals (set before fork)


def _init_globals():
    land = worldgeo.land(natural=True)
    parts = list(land.geoms)
    m1, d1 = fields(1)
    ext = np.clip(np.round(extend(np.asarray(vanilla_level(2))[..., :3], m1, P2)), 0, 255).astype(np.uint8)
    _G.update(parts=parts, tree=shapely.STRtree(parts), bmng=bmng_prep(), cdist=coast_dist(), sea=(lut := sea_lut()), off=offsets(lut, bmng_prep()),
              vst=display.read_stpi(open(VSTPI, 'rb').read()), m={1: m1, 2: pool_all(m1, 2), 4: pool_all(m1, 4),
                                                                   8: pool_all(m1, 8)}, d1=d1, ext=ext)


def _vfh():
    if 'vfh' not in _G:
        _G['vfh'] = open(VSTPD, 'rb')
    return _G['vfh']


def vtile_raw(L, vi, vj):
    tx, ty, recs = _G['vst']['levels'][L]
    return display.read_tile_raw(_vfh(), recs[vj * tx + vi])


def tile_blocks(raw):
    """Stored tile bytes -> DXT5 blocks (128, 128, 16) uint8."""
    return np.frombuffer(b''.join(zlib.decompress(z) for z, _ in display.split_tile_chunks(raw)), np.uint8).reshape(NB, NB, 16)


def pack_tile(blocks):
    """DXT5 blocks -> stored tile bytes (8 x [u32 csize, u32 usize, zlib 9]), like display.encode_tile."""
    data = np.ascontiguousarray(blocks).tobytes()
    out = []
    for p in range(0, len(data), display.CHUNK):
        z = zlib.compress(data[p:p + display.CHUNK], 9)
        out += [struct.pack('<II', len(z), display.CHUNK), z]
    return b''.join(out)


def vblocks(L, X0, Y0):
    """Vanilla level-L DXT5 blocks covering the 512x512 new-box window (X0, Y0) -> (128, 128, 16) (zeros outside)."""
    tx, ty, _ = _G['vst']['levels'][L]
    bx, by = (X0 - (VOFF[0] >> L)) // 4, (Y0 - (VOFF[1] >> L)) // 4     # window origin in vanilla blocks
    out = np.zeros((NB, NB, 16), np.uint8)
    for vj in range(by // NB, (by + NB - 1) // NB + 1):
        for vi in range(bx // NB, (bx + NB - 1) // NB + 1):
            if 0 <= vi < tx and 0 <= vj < ty:
                t = tile_blocks(vtile_raw(L, vi, vj))
                x0, y0 = vi * NB - bx, vj * NB - by
                a, b, c, d = max(x0, 0), max(y0, 0), min(x0 + NB, NB), min(y0 + NB, NB)
                out[b:d, a:c] = t[b - y0:d - y0, a - x0:c - x0]
    return out


def decode_blocks(blocks):
    return np.asarray(display.dxt5_decode(np.ascontiguousarray(blocks).tobytes()))


def tile_grid(arr, L, i, j, fill):
    """Sample a vanilla-box grid at the texels of new tile (L, i, j): arr is the level-2 grid for L <= 2, else the
    level-L grid (level-2 grid pooled by 2^(L-2)). None if the tile misses the vanilla box."""
    X = i * T + np.arange(T) - (VOFF[0] >> L)
    Y = j * T + np.arange(T) - (VOFF[1] >> L)
    if L < 2:
        X, Y = X >> (2 - L), Y >> (2 - L)
    okx, oky = (X >= 0) & (X < arr.shape[1]), (Y >= 0) & (Y < arr.shape[0])
    if not okx.any() or not oky.any():
        return None
    out = np.full((T, T) + arr.shape[2:], fill, arr.dtype)
    out[np.ix_(oky, okx)] = arr[np.ix_(Y[oky], X[okx])]
    return out


def painted_blocks(L, i, j):
    """(128, 128) bool: DXT blocks of tile (L, i, j) wholly on the painted mask, or None."""
    k = 1 if L <= 2 else 1 << (L - 2)
    p = tile_grid(_G['m'][k], L, i, j, False)
    return None if p is None else pool_all(p, 4)


def vanilla_tile_index(L, i, j):
    """Vanilla tile (vi, vj) that coincides with new tile (L, i, j), or None (not tile-aligned at this level)."""
    ox, oy = VOFF[0] >> L, VOFF[1] >> L
    return (i - ox // T, j - oy // T) if ox % T == 0 and oy % T == 0 else None


def composite(img, L, i, j, pb):
    """-> (img, vanilla blocks or None). Painted blocks get vanilla texels; at level 0 the generated side within
    FEATHER units of the painted edge blends from vanilla's nearest painted colour."""
    out, vb = img, None
    if L == 0:
        d = tile_grid(_G['d1'], 0, i, j, np.inf)
        if d is not None and d.min() < FEATHER:
            w = np.clip(1 - d / FEATHER, 0, 1)[..., None]
            ext = tile_grid(_G['ext'], 0, i, j, 0)
            out = img.copy()
            out[..., :3] = np.round(w * ext + (1 - w) * img[..., :3]).astype(np.uint8)
    if pb is not None and pb.any():
        vb = vblocks(L, i * T, j * T)
        P = blocks_up(pb)
        out = out.copy() if out is img else out
        out[P] = decode_blocks(vb)[P]
    return out, vb


def gen_l0(i, j, polys):
    """Generated level-0 tile (no vanilla): RGBA uint8."""
    x, y = texel_xy(0, i * T, j * T)
    lo, hi = (BX0 + i * T / ST, BY1 - (j + 1) * T / ST), (BX0 + (i + 1) * T / ST, BY1 - j * T / ST)
    landf = np.zeros((T, T), np.float32)
    if polys:
        landf = worldgeo.mask(MultiPolygon(polys), 2 * ST, lo, hi).reshape(T, 2, T, 2).mean((1, 3))
    lon, lat = lonlat(x, y)
    dist = sample_xy(_G['cdist'], x, y, 3.2)
    # fade to the open-sea constant beyond the theatre (filler band, never playable)
    out_t = np.hypot(np.maximum(np.maximum(TX0 - x, x - TX1), 0)[None, :], np.maximum(np.maximum(TY0 - y, y - TY1), 0)[:, None])
    dist = np.where(out_t > 0, np.maximum(dist, np.minimum(1, out_t / 8) * _G['sea'][0][-1]), dist)
    rgb = sea_rgb(dist, _G['sea']) + sample_xy(_G['off'][0], x, y, 0.8)
    if polys:
        lrgb = sample_ll(_G['bmng'], lat, lon) + sample_xy(_G['off'][1], x, y, 0.8)
        rgb = landf[..., None] * lrgb + (1 - landf[..., None]) * rgb
    a = np.round(255 * (1 - landf))
    return np.concatenate([np.clip(np.round(rgb), 0, 255), a[..., None]], -1).astype(np.uint8)


def _strip_polys(j, L=0):
    ppu = ST / (1 << L)
    y1, y0 = BY1 - j * T / ppu, BY1 - (j + 1) * T / ppu
    out = []
    for k in _G['tree'].query(shapely.box(BX0, y0, BX1, y1)):
        g = shapely.clip_by_rect(_G['parts'][k], BX0, y0, BX1, y1)
        out += [p for p in shapely.get_parts(g) if p.geom_type == 'Polygon' and not p.is_empty]
    return out


def _tile_polys(strip, i):
    x0, x1 = BX0 + i * T / ST, BX0 + (i + 1) * T / ST
    out = []
    for p in strip:
        b = p.bounds
        if b[2] <= x0 or b[0] >= x1:
            continue
        g = shapely.clip_by_rect(p, x0, BY0, x1, BY1)   # strip already clipped in y
        out += [q for q in shapely.get_parts(g) if q.geom_type == 'Polygon' and not q.is_empty]
    return out


def _spill(L, i, j):
    return os.path.join(CACHE, 'spill', str(L), f'{j}_{i}.u8')


def _finish(L, i, j, img, raw=None, pb=None, vb=None, spill=True):
    """-> ('const', rgba) | ('raw', bytes); writes the half-res image for the next level. Painted blocks are stored
    as vanilla's own DXT blocks."""
    if raw is None and vb is None and (img == img[0, 0]).all():
        return ('const', tuple(int(c) for c in img[0, 0]))
    if spill and L + 1 < NLEV:
        half(img).tofile(_spill(L, i, j))
    if raw is None:
        b = np.frombuffer(display.dxt5_encode(Image.fromarray(img, 'RGBA')), np.uint8).reshape(NB, NB, 16)
        raw = pack_tile(np.where(pb[..., None], vb, b) if vb is not None else b)
    return ('raw', raw)


def _vanilla_copy(L, i, j, pb):
    """Tile wholly painted and on vanilla's tile grid -> vanilla tile bytes, else None."""
    va = vanilla_tile_index(L, i, j) if pb is not None and pb.all() else None
    return vtile_raw(L, *va) if va else None


def row_l0(args):
    """One level-0 tile row -> list of results (or images if not spill). args = (j, i0, i1, spill)."""
    j, i0, i1, spill = args
    strip = _strip_polys(j)
    res = []
    for i in range(i0, i1):
        pb = painted_blocks(0, i, j)
        raw = _vanilla_copy(0, i, j, pb)
        if raw:
            img = np.asarray(display.decode_tile(raw))
            res.append(_finish(0, i, j, img, raw) if spill else img)
            continue
        img, vb = composite(gen_l0(i, j, _tile_polys(strip, i)), 0, i, j, pb)
        res.append(_finish(0, i, j, img, None, pb, vb) if spill else img)
    return res


def row_up(args):
    """One level-L (L >= 1) tile row from the spilled level L-1 halves. args = (L, j, tx, child_consts)."""
    L, j, tx, consts = args
    res = []
    for i in range(tx):
        pb = painted_blocks(L, i, j)
        raw = _vanilla_copy(L, i, j, pb)
        if raw:
            res.append(_finish(L, i, j, np.asarray(display.decode_tile(raw)), raw))
            continue
        kids = [(2 * i + di, 2 * j + dj) for dj in (0, 1) for di in (0, 1)]
        img = np.empty((T, T, 4), np.uint8)
        for k, (ci, cj) in enumerate(kids):
            sl = (slice((k // 2) * 256, (k // 2) * 256 + 256), slice((k % 2) * 256, (k % 2) * 256 + 256))
            c = consts.get((ci, cj))
            img[sl] = c if c is not None else np.fromfile(_spill(L - 1, ci, cj), np.uint8).reshape(256, 256, 4)
        img, vb = composite(img, L, i, j, pb)
        res.append(_finish(L, i, j, img, None, pb, vb))
    return res


def bake_supertexture():
    t0 = time.time()
    _init_globals()
    stpi, stpd = os.path.join(OUT, 'supertexture.stpi'), os.path.join(OUT, 'supertexture.stpd')
    vpads = [lv[2][0][4] for lv in _G['vst']['levels']]      # as probe_g2 (in-game tested)
    const_raw = {}                                            # rgba -> (off, size), one stored tile per colour
    levels, off, ident = [], 0, 1
    with open(stpd, 'wb') as fo, Pool(NPROC) as pool:
        consts = {}
        for L in range(NLEV):
            t1 = time.time()
            os.makedirs(os.path.join(CACHE, 'spill', str(L)), exist_ok=True)
            tx, ty = (W0 >> L) // T, (H0 >> L) // T
            if L == 0:
                it = pool.imap(row_l0, [(j, 0, tx, True) for j in range(ty)])
            else:
                it = pool.imap(row_up, [(L, j, tx, {k: v for k, v in consts.items() if k[1] in (2 * j, 2 * j + 1)})
                                        for j in range(ty)])
            recs, new_consts, nraw = [], {}, 0
            for j, row in enumerate(it):
                for i, (kind, val) in enumerate(row):
                    if kind == 'const':
                        new_consts[(i, j)] = val
                        if val not in const_raw:
                            raw = display.encode_tile(Image.new('RGBA', (T, T), val))
                            fo.write(raw); const_raw[val] = (off, len(raw)); off += len(raw)
                        o, n = const_raw[val]
                    else:
                        fo.write(val); o, n = off, len(val); off += n; nraw += 1
                    recs.append((o, n, display.TILE_BYTES, ident, vpads[L])); ident += 1
            levels.append((tx, ty, recs))
            if L:
                shutil.rmtree(os.path.join(CACHE, 'spill', str(L - 1)))
            consts = new_consts
            print(f'  level {L}: {tx}x{ty} tiles, {nraw} stored, {len(new_consts)} constant, '
                  f'{off / 1e9:.2f} GB so far ({time.time() - t1:.0f}s)', flush=True)
        shutil.rmtree(os.path.join(CACHE, 'spill', str(NLEV - 1)), ignore_errors=True)
    s = dict(header=(6, W0, H0, T, display.TILE_BYTES), levels=levels, trailer=1)
    open(stpi, 'wb').write(display.write_stpi(s))
    print(f'supertexture {W0}x{H0}: {ident - 1} records, {len(const_raw)} constant colours, '
          f'stpd {off / 1e9:.2f} GB ({time.time() - t0:.0f}s)')


def bake_region(x0, y0, x1, y1, max_w=4096, name='region_l0'):
    """Level-0 tiles covering a world window, stitched -> NAME.png (downscaled to <= max_w)."""
    if 'tree' not in _G:
        _init_globals()
    i0, i1 = int((x0 - BX0) * ST // T), int(np.ceil((x1 - BX0) * ST / T))
    j0, j1 = int((BY1 - y1) * ST // T), int(np.ceil((BY1 - y0) * ST / T))
    with Pool(NPROC) as pool:
        rows = pool.map(row_l0, [(j, i0, i1, False) for j in range(j0, j1)])
    img = np.concatenate([np.concatenate(row, 1) for row in rows], 0)
    im = Image.fromarray(img[..., :3])
    k = max(1, -(-im.width // max_w))
    im.reduce(k).save(os.path.join(OUT, name + '.png'))
    Image.fromarray(img[..., 3]).reduce(k).save(os.path.join(OUT, name + '_alpha.png'))
    print(f'{name}: tiles i {i0}..{i1}, j {j0}..{j1} (1/{k})')


# ---------------------------------------------------------------- detail mask
def dxt3_mips(img, vhdr, base_override=None):
    """DXT3 DDS with a full mip chain, header laid out like vanilla's (vhdr = its 128 bytes; size fields patched).
    base_override(blocks (h/4, w/4, 16)) may replace base-level blocks."""
    import io
    w, h = img.size
    data, l = [], 0
    while True:
        lw, lh = max(1, w >> l), max(1, h >> l)
        m = img.resize((lw, lh), Image.BOX) if l else img
        if lw < 4 or lh < 4:   # encode in one padded block row/col
            pad = Image.new('RGBA', (max(4, lw), max(4, lh))); pad.paste(m); m = pad
        bio = io.BytesIO(); m.save(bio, 'DDS', pixel_format='DXT3')
        data.append(bio.getvalue()[128:128 + ((lw + 3) // 4) * ((lh + 3) // 4) * 16])
        if l == 0 and base_override:
            data[0] = base_override(np.frombuffer(data[0], np.uint8).reshape(h // 4, w // 4, 16)).tobytes()
        l += 1
        if lw == 1 and lh == 1:
            break
    hdr = bytearray(vhdr)
    struct.pack_into('<III', hdr, 12, h, w, len(data[0]))
    struct.pack_into('<I', hdr, 28, len(data))
    return bytes(hdr) + b''.join(data)


def detail_painted():
    """Detail-mask pixels (0.8 px/u, vanilla box) whose DXT3 block is wholly painted."""
    return blocks_up(pool_all(pool_all(painted(), 8), 4))


def bake_detail(hm=None):
    ppu = 0.8
    vraw = open(VDETAIL, 'rb').read()
    van = np.asarray(Image.open(VDETAIL).convert('RGBA'))
    vh_, vw_ = van.shape[:2]
    if hm is None:
        hm = np.array(Image.open(os.path.join(OUT, 'heightmap.tga')))
    hm4 = hm.reshape(hm.shape[0] // 4, 4, hm.shape[1] // 4, 4).astype(np.float32).mean((1, 3))
    # vanilla detail RGB per vanilla heightmap value (painted land, 0.8 px/u)
    vh = np.array(Image.open(VAN + '/heightmap/heightmap.tga')).astype(np.float32)
    vh4 = vh.reshape(vh.shape[0] // 4, 4, vh.shape[1] // 4, 4).mean((1, 3))
    land_v = (van[..., 3] < 128) & pool_all(painted(), 8)
    hb, vrgb = np.minimum(vh4[land_v], 254).astype(int) // 8, van[land_v][:, :3].astype(np.float32)
    lut = np.zeros((32, 3), np.float32)
    for b in range(32):
        m = hb == b
        lut[b] = vrgb[m].mean(0) if m.sum() > 50 else lut[b - 1]
    landf = worldgeo.mask(worldgeo.land(natural=True), 4 * ppu)
    landf = landf.reshape(landf.shape[0] // 4, 4, landf.shape[1] // 4, 4).mean((1, 3))
    gen = np.zeros(landf.shape + (4,), np.float32)
    gen[..., :3] = landf[..., None] * lut[np.minimum(hm4, 254).astype(int) // 8]
    gen[..., 3] = 255 * (1 - landf)
    out, _ = paint_composite(gen, van, 8, ppu, chans=slice(0, 3))
    out = np.clip(np.round(out), 0, 255).astype(np.uint8)
    # base level: vanilla's own DXT3 blocks wherever the block is wholly painted (grids are 4-px aligned)
    vblk = np.frombuffer(vraw, np.uint8, vh_ * vw_, 128).reshape(vh_ // 4, vw_ // 4, 16)
    pb = pool_all(pool_all(painted(), 8), 4)
    r0, c0 = int((BY1 - VBOX[3]) * ppu) // 4, int((VBOX[0] - BX0) * ppu) // 4

    def override(b):
        b = b.copy()
        reg = b[r0:r0 + pb.shape[0], c0:c0 + pb.shape[1]]
        reg[pb] = vblk[pb]
        return b
    dds = os.path.join(OUT, 'campaign_detail_mask.dds')
    open(dds, 'wb').write(dxt3_mips(Image.fromarray(out, 'RGBA'), vraw[:128], override))
    print('detail mask', Image.open(dds).size, 'mips', int.from_bytes(open(dds, 'rb').read()[28:32], 'little'))


# ---------------------------------------------------------------- checks
def check():
    m2 = painted()
    print(f'painted mask: {m2.sum() * 16:,} level-0 texels = {m2.sum() / P2 ** 2:,.0f} u^2 '
          f'({m2.sum() / P2 ** 2 / ((VX1 - VX0) * (VY1 - VY0)):.1%} of VT)')
    hm = np.array(Image.open(os.path.join(OUT, 'heightmap.tga')))
    van = pad_vanilla(np.array(Image.open(VAN + '/heightmap/heightmap.tga')), 3.2)
    pm = pad_vanilla(pool_all(m2, 2), 3.2, False)
    eq = (hm[pm] == van[pm]).all()
    print(f'heightmap {hm.shape[::-1]}: {pm.sum():,} painted pixels identical to vanilla: {eq}')
    assert hm.shape == (8192, 12288) and eq

    stpi, stpd = os.path.join(OUT, 'supertexture.stpi'), os.path.join(OUT, 'supertexture.stpd')
    s = display.read_stpi(open(stpi, 'rb').read())
    assert s['header'] == (6, W0, H0, T, display.TILE_BYTES), s['header']
    assert [l[:2] for l in s['levels']] == [((W0 >> L) // T, (H0 >> L) // T) for L in range(NLEV)]
    _G['vst'] = display.read_stpi(open(VSTPI, 'rb').read())
    _G['m'] = {1: m2, 2: pool_all(m2, 2), 4: pool_all(m2, 4), 8: pool_all(m2, 8)}
    with open(stpd, 'rb') as fh:
        for L in range(NLEV):
            tx, ty, recs = s['levels'][L]
            ncopy = nmix = ntex = 0
            for j in range(ty):
                for i in range(tx):
                    pb = painted_blocks(L, i, j)
                    if pb is None or not pb.any():
                        continue
                    raw = display.read_tile_raw(fh, recs[j * tx + i])
                    if _vanilla_copy(L, i, j, pb):
                        assert raw == _vanilla_copy(L, i, j, pb), (L, i, j)
                        ncopy += 1
                    else:
                        nmix += 1
                    mine, ref = tile_blocks(raw), vblocks(L, i * T, j * T)
                    assert (mine[pb] == ref[pb]).all(), (L, i, j)
                    P = blocks_up(pb)
                    assert (decode_blocks(mine)[P] == decode_blocks(ref)[P]).all(), (L, i, j)
                    ntex += int(P.sum())
            print(f'  supertexture level {L}: {ncopy} vanilla tile copies + {nmix} composited tiles; '
                  f'{ntex:,} painted texels bit-identical (DXT blocks and decoded)')

    # coasts: level-0 alpha vs worldgeo.mask on the generated texels
    land = worldgeo.land(natural=True)
    with open(stpd, 'rb') as fh:
        for name, lon, lat in (('Japan/Tokyo Bay', 139.8, 35.4), ('Florida', -80.5, 26.5), ('Cape', 18.6, -34.2),
                               ('Tunis (frame)', 10.3, 36.9), ('Izmir (frame)', 27.1, 38.4),
                               ('Benghazi', 20.0, 32.1), ('Beirut', 35.5, 33.9), ('Kola', 33.1, 69.0)):
            x, y = proj.to_world(lon, lat)
            i, j = int((x - BX0) * ST // T), int((BY1 - y) * ST // T)
            a = np.asarray(display.decode_tile(display.read_tile_raw(fh, s['levels'][0][2][j * s['levels'][0][0] + i])))[..., 3]
            m = worldgeo.mask(land, ST, (BX0 + i * T / ST, BY1 - (j + 1) * T / ST), (BX0 + (i + 1) * T / ST, BY1 - j * T / ST))
            pb = painted_blocks(0, i, j)
            gen = ~blocks_up(pb) if pb is not None else np.ones_like(m)
            agree = ((a >= 128) == ~m)[gen].mean()
            print(f'  coast {name:16s} tile ({i},{j}) land {m.mean():.0%}, painted {1 - gen.mean():.0%}: '
                  f'generated alpha agrees with worldgeo.mask {agree:.1%}')
    l5 = display.read_level_image(stpi, stpd, 5)
    l5.convert('RGB').save(os.path.join(OUT, 'preview_l5.png'))
    l5.getchannel('A').save(os.path.join(OUT, 'preview_l5_alpha.png'))
    e = (int((-560 - BX0) * ST / 32), int((BY1 - 260) * ST / 32), int((480 - BX0) * ST / 32), int((BY1 + 260) * ST / 32))
    l5.convert('RGB').crop(e).save(os.path.join(OUT, 'preview_l5_europe.png'))
    print('preview_l5.png', l5.size, 'stpd %.2f GB' % (os.path.getsize(stpd) / 1e9))

    dds = os.path.join(OUT, 'campaign_detail_mask.dds')
    d = np.asarray(Image.open(dds).convert('RGBA'))
    assert d.shape[:2] == (2048, 3072)
    dp = pad_vanilla(detail_painted(), 0.8, False)
    vd = pad_vanilla(np.asarray(Image.open(VDETAIL).convert('RGBA')), 0.8)
    eq = (d[dp] == vd[dp]).all()
    print(f'detail mask {d.shape[1::-1]}: {dp.sum():,} painted pixels identical to vanilla: {eq}')
    assert eq
    print('CHECK OK')


if __name__ == '__main__':
    os.makedirs(CACHE, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'check'
    t0 = time.time()
    if cmd == 'region':
        bake_region(*map(float, sys.argv[2:6]))
    elif cmd == 'all':
        bmng_prep()
        hm = bake_heightmap()
        bake_supertexture()
        bake_detail(hm)
        check()
    elif cmd == 'heightmap':
        bake_heightmap()
    elif cmd == 'supertexture':
        bake_supertexture()
    elif cmd == 'detail':
        bake_detail()
    else:
        check()
    print(f'{cmd} done in {time.time() - t0:.0f}s')
