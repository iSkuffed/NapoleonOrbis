"""World projection and raster baking from open geodata (ETOPO 2022, Natural Earth).

Projection: plate carree like vanilla nap_europe (fitted: x = 13.14*lon - 240.9, y = 13.04*lat - 636.1).
A whole world must fit |x| < 2048 (int32 * 2^-20 fixed point), so the world map uses a smaller scale.

  python tools/geo.py heightmap OUT.tga [--scale 11.3] [--lat -58 78] [--ppu 3.2]
  python tools/geo.py preview OUT.png        # small world preview with vanilla Europe theatre outlined
"""
import argparse, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ETOPO = os.path.join(ROOT, 'work/geodata/etopo60s_surface.nc')
GAME = os.path.expanduser('~/.local/share/Steam/steamapps/common/Napoleon Total War/data')

# vanilla nap_europe fit (research/00-local-findings.md)
VAN_SX, VAN_X0, VAN_SY, VAN_Y0 = 13.14, -240.9, 13.04, -636.1


class World:
    """Plate carree world: lon0 at x=0 (centre), lat_c at y=0. Units per degree `scale`."""
    def __init__(self, scale=11.3, lat_min=-58.0, lat_max=78.0, lon0=10.5):
        self.scale, self.lat_min, self.lat_max, self.lon0 = scale, lat_min, lat_max, lon0
        self.lat_c = (lat_min + lat_max) / 2
        self.half_w = 180 * scale
        self.half_h = (lat_max - lat_min) / 2 * scale
        assert self.half_w < 2048, 'world exceeds the int32*2^-20 fixed-point range'

    def to_world(self, lon, lat):
        dl = (np.asarray(lon) - self.lon0 + 180) % 360 - 180   # seam at lon0 +- 180
        return dl * self.scale, (np.asarray(lat) - self.lat_c) * self.scale

    def to_lonlat(self, x, y):
        return (np.asarray(x) / self.scale + self.lon0 + 180) % 360 - 180, np.asarray(y) / self.scale + self.lat_c

    @property
    def bounds(self):
        return (-self.half_w, -self.half_h), (self.half_w, self.half_h)


def etopo_sample(lon, lat):
    """Nearest-neighbour ETOPO 60s elevation (metres) at arrays lon, lat."""
    import h5py
    f = h5py.File(ETOPO)
    la, lo = f['lat'], f['lon']
    i = np.clip(np.round((lat - la[0]) / (la[1] - la[0])).astype(int), 0, la.shape[0] - 1)
    j = np.clip(np.round((lon - lo[0]) / (lo[1] - lo[0])).astype(int), 0, lo.shape[0] - 1)
    z = f['z']
    out = np.empty(i.shape, np.float32)
    rows = np.unique(i)
    for r0 in range(0, len(rows), 512):        # read in row blocks: whole grid is 0.9 GB as float32
        blk = rows[r0:r0 + 512]
        data = z[blk[0]:blk[-1] + 1, :]
        m = (i >= blk[0]) & (i <= blk[-1])
        out[m] = data[i[m] - blk[0], j[m]]
    return out


def vanilla_calibration():
    """Quantile table mapping ETOPO land elevation -> vanilla heightmap value, from the Europe theatre."""
    from PIL import Image
    h = np.array(Image.open(GAME + '/campaign_maps/nap_europe/display/heightmap/heightmap.tga')).astype(np.float32)
    wx, wy = np.meshgrid(np.arange(-400, 330, 0.5), np.arange(-185, 190, 0.5))
    z = etopo_sample((wx - VAN_X0) / VAN_SX, (wy - VAN_Y0) / VAN_SY)
    hv = h[np.round((320 - wy) * 3.2).astype(int), np.round((wx + 640) * 3.2).astype(int)]
    land = z > 0
    q = np.linspace(0, 100, 201)
    return np.percentile(z[land], q), np.percentile(hv[land], q)


def bake_heightmap(world, ppu=3.2):
    """L8 heightmap over the world box, top row = north. Sea = 0; land quantile-matched to vanilla."""
    # ponytail: absolute elevation, so plateaus (Tibet, Greenland) bake flat white; vanilla is local relief -> use elev minus a low-pass when tuning looks
    (x0, y0), (x1, y1) = world.bounds
    w, hgt = int(round((x1 - x0) * ppu)), int(round((y1 - y0) * ppu))
    xs = x0 + (np.arange(w) + 0.5) / ppu
    out = np.zeros((hgt, w), np.uint8)
    zq, hq = vanilla_calibration()
    for r0 in range(0, hgt, 256):
        ys = y1 - (np.arange(r0, min(hgt, r0 + 256)) + 0.5) / ppu
        X, Y = np.meshgrid(xs, ys)
        z = etopo_sample(*world.to_lonlat(X, Y))
        v = np.where(z > 0, np.interp(z, zq, hq), 0)
        out[r0:r0 + len(ys)] = np.clip(np.round(v), 0, 255)
    return out


def land_mask(world, ppu, shp='ne_10m_land', lakes=True):
    """bool raster over the world box (top row = north): Natural Earth land minus lakes."""
    import shapefile, zipfile, io
    from PIL import Image, ImageDraw
    (x0, y0), (x1, y1) = world.bounds
    w, h = int(round((x1 - x0) * ppu)), int(round((y1 - y0) * ppu))
    img = Image.new('L', (w, h)); d = ImageDraw.Draw(img)

    def paint(name, val):
        z = zipfile.ZipFile(os.path.join(ROOT, 'work/geodata', name + '.zip'))
        r = shapefile.Reader(shp=io.BytesIO(z.read(name + '.shp')), dbf=io.BytesIO(z.read(name + '.dbf')))
        for s in r.iterShapes():
            pts = np.array(s.points)
            for a, b in zip(s.parts, list(s.parts[1:]) + [len(pts)]):
                ring = pts[a:b]
                x, y = world.to_world(ring[:, 0], ring[:, 1])
                # ponytail: rings crossing the seam (lon0+-180) are split crudely by unwrapping; only Chukotka/Fiji touch it
                x = np.unwrap(x / world.scale, period=360) * world.scale
                for off in (0, -2 * world.half_w, 2 * world.half_w):
                    if (x + off).max() < x0 or (x + off).min() > x1:
                        continue
                    d.polygon(list(zip((x + off - x0) * ppu, (y1 - y) * ppu)), fill=val)
    # ponytail: holes are painted as separate rings by Natural Earth part order (outer first); fine for land at this scale
    paint(shp, 1)
    if lakes:
        paint('ne_10m_lakes', 0)
    return np.array(img, bool)


def save_tga(path, a):
    """Write L8 TGA like vanilla: 8 bpp, descriptor 0 (bottom-left origin, no alpha bits)."""
    hgt, w = a.shape
    hdr = bytes([0, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, w & 255, w >> 8, hgt & 255, hgt >> 8, 8, 0])
    with open(path, 'wb') as f:
        f.write(hdr + np.ascontiguousarray(a[::-1]).tobytes())


def _selfcheck():
    w = World()
    x, y = w.to_world(np.array([10.5, -169.5, 370.5]), np.array([10.0, 78.0, -58.0]))
    assert np.allclose(x, [0, -w.half_w, 0]) and np.allclose(y, [0, w.half_h, -w.half_h]), (x, y)
    lo, la = w.to_lonlat(*w.to_world(np.array([2.35, 139.7]), np.array([48.86, 35.7])))
    assert np.allclose([lo, la], [[2.35, 139.7], [48.86, 35.7]])
    a = (np.arange(12).reshape(3, 4) * 20).astype(np.uint8)
    p = os.path.join(ROOT, 'work/_geo_selfcheck.tga'); save_tga(p, a)
    from PIL import Image
    assert (np.array(Image.open(p)) == a).all(); os.remove(p)
    print('geo selfcheck ok; world', w.bounds)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', nargs='?', default='selfcheck', choices=['selfcheck', 'heightmap', 'preview'])
    ap.add_argument('out', nargs='?')
    ap.add_argument('--scale', type=float, default=11.3)
    ap.add_argument('--lat', type=float, nargs=2, default=[-58, 78])
    ap.add_argument('--ppu', type=float, default=3.2)
    a = ap.parse_args()
    w = World(a.scale, *a.lat)
    if a.cmd == 'selfcheck':
        _selfcheck()
    elif a.cmd == 'heightmap':
        save_tga(a.out, bake_heightmap(w, a.ppu))
    else:
        from PIL import Image
        Image.fromarray(np.minimum(255, bake_heightmap(w, 0.25).astype(int) * 3).astype(np.uint8)).save(a.out)
