"""Gate G2 probe: vanilla nap_europe embedded unchanged in a bigger world box.

  python tools/probe_g2.py HALF_W HALF_H     # e.g. 1920 960 (centred box); writes work/mods/world_g2/campaign_maps/nap_world
  python tools/probe_g2.py X0 Y0 X1 Y1       # any box containing the vanilla one

Resized: regions.esf (outer filler regions + quadtrees), heightmap (zero pad), supertexture (vanilla tiles in the
middle, one shared filler tile per level elsewhere), campaign_detail_mask (pad). Omitted like other vanilla maps:
fogmask, snow, snowmask. pathfinding.esf grid start cells re-based on the box min. Theatre unchanged.
The startpos must be regridded to match: campaign_misc.regrid_visibility + EPISODIC_RESTRICTIONS rect (research/00, G2).
"""
import os, shutil, subprocess, sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esf, regions_model, display, geo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = geo.GAME + '/campaign_maps/nap_europe'
VW, VH = 640, 320          # vanilla half extents


def build(lo, hi, out):
    (x0, y0), (x1, y1) = lo, hi
    assert (x1 - x0) % 640 == 0 and (y1 - y0) % 640 == 0, 'keep the box a multiple of 640 like vanilla'
    if os.path.exists(out):
        shutil.rmtree(out)
    shutil.copytree(SRC, out, ignore=shutil.ignore_patterns('fogmask', 'snow', 'snowmask', 'supertexture', 'heightmap'))

    e = esf.load(SRC + '/regions.esf')
    print('regions: moved', regions_model.resize_world(e, lo, hi), 'border vertices')
    open(out + '/regions.esf', 'wb').write(esf.dumps(e))

    # pathfinding grid_data stores its start cell relative to the world-box min (u16 115, 65 = (-410+640)/2, (-190+320)/2)
    p = esf.load(SRC + '/pathfinding.esf')
    gd = p.root.find('pathfinding_areas').items[0][2].children
    ox, oy, cell = gd[0].value / 2**20, gd[1].value / 2**20, gd[4].value / 2**20
    assert (gd[2].value, gd[3].value) == ((ox + VW) / cell, (oy + VH) / cell)
    gd[2].value, gd[3].value = int((ox - x0) / cell), int((oy - y0) / cell)
    open(out + '/pathfinding.esf', 'wb').write(esf.dumps(p))

    os.makedirs(out + '/display/heightmap')
    h = np.zeros((int((y1 - y0) * 3.2), int((x1 - x0) * 3.2)), np.uint8)
    v = np.array(Image.open(SRC + '/display/heightmap/heightmap.tga'))
    r0, c0 = int((y1 - VH) * 3.2), int((-VW - x0) * 3.2)        # rows from the top (north)
    h[r0:r0 + v.shape[0], c0:c0 + v.shape[1]] = v
    geo.save_tga(out + '/display/heightmap/heightmap.tga', h)

    # supertexture: copy vanilla tile bytes; every other record points at one filler tile per level
    os.makedirs(out + '/display/supertexture')
    s = display.read_stpi(open(SRC + '/display/supertexture/supertexture.stpi', 'rb').read())
    W, H = int((x1 - x0) * 25.6), int((y1 - y0) * 25.6)
    levels, off, ident = [], 0, 1
    with open(SRC + '/display/supertexture/supertexture.stpd', 'rb') as fi, \
            open(out + '/display/supertexture/supertexture.stpd', 'wb') as fo:
        for L, (vtx, vty, recs) in enumerate(s['levels']):
            tx, ty = (W >> L) // 512, (H >> L) // 512
            ox, oy = int((-VW - x0) * 25.6 / 512) >> L, int((y1 - VH) * 25.6 / 512) >> L   # tile rows from the top
            filler = None
            new = []
            for j in range(ty):
                for i in range(tx):
                    vi, vj = i - ox, j - oy
                    if 0 <= vi < vtx and 0 <= vj < vty:
                        raw = display.read_tile_raw(fi, recs[vj * vtx + vi])
                    elif filler is not None:
                        new.append((filler[0], filler[1], display.TILE_BYTES, ident, recs[0][4])); ident += 1
                        continue
                    else:
                        raw = display.read_tile_raw(fi, recs[0])     # vanilla corner tile (off-theatre sea)
                    fo.write(raw)
                    if not (0 <= vi < vtx and 0 <= vj < vty):
                        filler = (off, len(raw))
                    new.append((off, len(raw), display.TILE_BYTES, ident, recs[0][4])); ident += 1
                    off += len(raw)
            levels.append((tx, ty, new))
    s2 = dict(header=(s['header'][0], W, H) + tuple(s['header'][3:]), levels=levels, trailer=s['trailer'])
    open(out + '/display/supertexture/supertexture.stpi', 'wb').write(display.write_stpi(s2))
    print('supertexture', W, H, [l[:2] for l in levels], off >> 20, 'MB')

    m = out + '/display/detail/campaign_detail_mask.dds'
    pw, ph = int((x1 - x0) * 0.8), int((y1 - y0) * 0.8)
    ex, ey = int((x0 + VW) * 0.8), int((VH - y1) * 0.8)        # offset of the new box's top-left corner
    subprocess.run(['magick', SRC + '/display/detail/campaign_detail_mask.dds', '-background', 'rgba(0,0,0,1)',
                    '-extent', f'{pw}x{ph}{ex:+d}{ey:+d}', '-define', 'dds:compression=dxt3', m], check=True)
    print('detail mask', Image.open(m).size)


if __name__ == '__main__':
    a = [float(x) for x in sys.argv[1:]]
    lo, hi = ((-a[0], -a[1]), (a[0], a[1])) if len(a) == 2 else ((a[0], a[1]), (a[2], a[3]))
    build(lo, hi, os.path.join(ROOT, 'work/mods/world_g2/campaign_maps/nap_world'))
