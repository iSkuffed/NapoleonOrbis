"""Readers/writers for Napoleon: Total War campaign-map display/ formats.

Spec and coordinate conventions: research/07-display-formats.md.
All 3D data uses x = east, y = up, z = north (z has the same sign as world y).
rigid_spline and bridge.markers are in world/40 units; everything else is in world units.

Run `python tools/display.py` for the byte-exact round-trip self-check on the vanilla maps.
"""
import io
import struct
import zlib

import numpy as np
from PIL import Image

SPLINE_SCALE = 40.0          # rigid_spline / bridge.markers coordinate = world / 40
SUPERTEXTURE_PX_PER_UNIT = 25.6  # all vanilla maps (Europe 32768/1280, Egypt 16384/640)
TILE = 512                   # supertexture tile edge, texels
TILE_BYTES = TILE * TILE     # DXT5 = 1 byte per texel
CHUNK = 32768                # supertexture tiles are stored as 8 zlib chunks of 64 texel rows


class _R:
    """Little-endian cursor over bytes."""

    def __init__(self, b, o=0):
        self.b, self.o = b, o

    def take(self, fmt):
        v = struct.unpack_from('<' + fmt, self.b, self.o)
        self.o += struct.calcsize('<' + fmt)
        return v if len(v) > 1 else v[0]

    def raw(self, n):
        v = self.b[self.o:self.o + n]
        self.o += n
        return v

    def s(self):
        return self.raw(2 * self.take('H')).decode('utf-16le')

    def arr(self, dtype, count, cols=None):
        a = np.frombuffer(self.b, dtype, count * (cols or 1), self.o).copy()
        self.o += a.nbytes
        return a.reshape(count, cols) if cols else a

    def end(self):
        assert self.o == len(self.b), 'trailing %d bytes' % (len(self.b) - self.o)


def _s(text):
    return struct.pack('<H', len(text)) + text.encode('utf-16le')


def _f32(a, cols):
    a = np.ascontiguousarray(a, '<f4')
    assert a.ndim == 2 and a.shape[1] == cols
    return a.tobytes()


# ---------------------------------------------------------------- rigid_spline
def read_spline(b):
    """-> list of (name, flag, points float32 (n,3) in world/40 units)."""
    r = _R(b)
    assert r.raw(4) == b'SPLN'
    ver, n = r.take('II')
    assert ver == 1
    out = []
    for _ in range(n):
        name = r.s()
        flag, npts = r.take('II')
        out.append((name, flag, r.arr('<f4', npts, 3)))
    r.end()
    return out


def write_spline(splines):
    out = [b'SPLN', struct.pack('<II', 1, len(splines))]
    for name, flag, pts in splines:
        out += [_s(name), struct.pack('<II', flag, len(pts)), _f32(pts, 3)]
    return b''.join(out)


def spline_from_world(name, xy, height=0.0, flag=1):
    """World (x, y) polyline -> one spline tuple. height: vanilla borders and roads 2.8e-4, rivers 0."""
    xy = np.asarray(xy, float)
    pts = np.column_stack([xy[:, 0] / SPLINE_SCALE, np.full(len(xy), height), xy[:, 1] / SPLINE_SCALE])
    return (name, flag, pts.astype('<f4'))


# ---------------------------------------------------------------- bridge.markers
def read_markers(b):
    """bridge.markers -> list of (name, float32 (4,4) row-major matrix; row 3 = translation in world/40)."""
    r = _R(b)
    out = []
    while r.o < len(b):
        out.append((r.s(), r.arr('<f4', 4, 4)))
    return out


def write_markers(markers):
    return b''.join(_s(n) + _f32(m, 4) for n, m in markers)


# ---------------------------------------------------------------- rigid_mesh (coastline)
def read_rigid_mesh(b):
    """-> dict(streams=[(bool, str)], unk=u32, verts=f32 (n,20), idx=u32 (m,))."""
    r = _R(b)
    assert r.take('I') == 0x12345678
    streams = [(r.take('B'), r.s()) for _ in range(r.take('I'))]
    unk = r.take('I')
    verts = r.arr('<f4', r.take('I'), 20)
    idx = r.arr('<u4', r.take('I'))
    r.end()
    return dict(streams=streams, unk=unk, verts=verts, idx=idx)


def write_rigid_mesh(m):
    out = [struct.pack('<II', 0x12345678, len(m['streams']))]
    out += [struct.pack('<B', f) + _s(s) for f, s in m['streams']]
    out += [struct.pack('<II', m['unk'], len(m['verts'])), _f32(m['verts'], 20),
            struct.pack('<I', len(m['idx'])), np.ascontiguousarray(m['idx'], '<u4').tobytes()]
    return b''.join(out)


def coastline_mesh(strips, width=1.0):
    """Build a coastline rigid_mesh dict from shoreline polylines (world x, y), vanilla layout:
    pairs of vertices (shore, shore + width offshore), col 6 = s/len, 7 = 0 shore/1 offshore,
    18 = arc length s, 19 = strip length. Offshore side = left of travel direction; reverse a strip if wrong."""
    verts, idx = [], []
    for xy in strips:
        xy = np.asarray(xy, float)
        d = np.gradient(xy, axis=0)
        d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
        normal = np.column_stack([-d[:, 1], d[:, 0]])
        s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))])
        length = s[-1] if s[-1] > 0 else 1.0
        base = sum(len(v) for v in verts)
        v = np.zeros((2 * len(xy), 20), '<f4')
        for k, off in ((0, 0.0), (1, width)):
            p = xy + normal * off
            v[k::2, 0], v[k::2, 2], v[k::2, 7] = p[:, 0], p[:, 1], k
            v[k::2, 6], v[k::2, 18], v[k::2, 19] = s / length, s, length
        verts.append(v)
        for i in range(len(xy) - 1):
            a = base + 2 * i
            idx += [a + 2, a + 3, a, a + 3, a + 1, a]
    return dict(streams=[(1, ''), (1, ''), (1, ''), (0, ''), (0, '')], unk=0,
                verts=np.concatenate(verts) if verts else np.zeros((0, 20), '<f4'),
                idx=np.array(idx, '<u4'))


# ---------------------------------------------------------------- rigid_trees
def read_rigid_trees(b):
    """-> dict(version, f1, u1, models=[(model_path, [(bbox f32[6], inst f32 (n,4) x,y,z,w)])])."""
    r = _R(b)
    assert r.raw(4) == b'G@M='
    version, f1, u1, nmodels = r.take('IfII')
    models = []
    for _ in range(nmodels):
        name = r.s()
        cells = []
        for _ in range(r.take('I')):
            n = r.take('I')
            cells.append((r.arr('<f4', 6), r.arr('<f4', n, 4)))
        models.append((name, cells))
    r.end()
    return dict(version=version, f1=f1, u1=u1, models=models)


def write_rigid_trees(t):
    out = [b'G@M=', struct.pack('<IfII', t['version'], t['f1'], t['u1'], len(t['models']))]
    for name, cells in t['models']:
        out += [_s(name), struct.pack('<I', len(cells))]
        for bbox, inst in cells:
            out += [struct.pack('<I', len(inst)), np.asarray(bbox, '<f4').tobytes(), _f32(inst, 4)]
    return b''.join(out)


# ---------------------------------------------------------------- world.markers
EMITTER, MODEL, OVERLAY = ('CAMPAIGN_DISPLAY_EMITTER_MARKER', 'CAMPAIGN_DISPLAY_MODEL_MARKER',
                           'CAMPAIGN_DISPLAY_OVERLAY_MARKER')


def _handle(r):
    assert r.raw(12) == bytes(12), 'non-zero handle padding at %#x' % (r.o - 12)
    return r.take('I')


def read_world_markers(b):
    """-> dict(name, handle, version, groups=[dict(cls, h1, h2, version, records, names)]).
    records: EMITTER (ptr u32, x, z, flag u32) | MODEL (ptr u32, x, z, rot_rad, flag u32)
             | OVERLAY (flags u32, texture_set, verts f32 (n,6) x,y,z,u,v,alpha, idx u32).
    names: [(u16 one, name, [record indices])]; absent (None) when there are no records."""
    r = _R(b)
    root = dict(name=r.s(), handle=_handle(r), version=r.take('I'), groups=[])
    for _ in range(r.take('H')):
        g = dict(h1=_handle(r), cls=r.s(), h2=_handle(r), version=r.take('I'))
        n = r.take('I')
        if g['cls'] == EMITTER:
            g['records'] = [r.take('IffI') for _ in range(n)]
        elif g['cls'] == MODEL:
            g['records'] = [r.take('IfffI') for _ in range(n)]
        elif g['cls'] == OVERLAY:
            g['records'] = []
            for _ in range(n):
                flags, tex = r.take('I'), r.s()
                verts = r.arr('<f4', r.take('I'), 6)
                g['records'].append((flags, tex, verts, r.arr('<u4', r.take('I'))))
        else:
            raise ValueError('unknown marker class ' + g['cls'])
        g['names'] = None
        if n:  # vanilla omits the name table entirely for empty groups
            g['names'] = []
            for _ in range(r.take('H')):
                one, name = r.take('H'), r.s()
                g['names'].append((one, name, r.arr('<u4', r.take('I')).tolist()))
        root['groups'].append(g)
    r.end()
    return root


def write_world_markers(m):
    h = lambda v: bytes(12) + struct.pack('<I', v)
    out = [_s(m['name']), h(m['handle']), struct.pack('<IH', m['version'], len(m['groups']))]
    for g in m['groups']:
        out += [h(g['h1']), _s(g['cls']), h(g['h2']), struct.pack('<II', g['version'], len(g['records']))]
        for rec in g['records']:
            if g['cls'] == EMITTER:
                out.append(struct.pack('<IffI', *rec))
            elif g['cls'] == MODEL:
                out.append(struct.pack('<IfffI', *rec))
            else:
                flags, tex, verts, idx = rec
                out += [struct.pack('<I', flags), _s(tex), struct.pack('<I', len(verts)), _f32(verts, 6),
                        struct.pack('<I', len(idx)), np.ascontiguousarray(idx, '<u4').tobytes()]
        if g['records']:
            names = g['names'] or []
            out.append(struct.pack('<H', len(names)))
            for one, name, ids in names:
                out += [struct.pack('<H', one), _s(name), struct.pack('<I%dI' % len(ids), len(ids), *ids)]
    return b''.join(out)


def empty_world_markers():
    """Minimal repository with the three vanilla groups and no records (untested in game)."""
    return dict(name='BASE_MARKER_REPOSITORY', handle=0x9D9BB, version=1, groups=[
        dict(h1=0x2A5DF200 + i, cls=c, h2=0x2A5DF200 + i, version=v, records=[], names=None)
        for i, (c, v) in enumerate(((EMITTER, 2), (MODEL, 2), (OVERLAY, 5)), 1)])


# ---------------------------------------------------------------- DDS helpers
def dds_header(w, h, fourcc=None, linear=None):
    """Minimal 128-byte DDS header. fourcc='DXT5'/'DXT1' or None for 8-bit luminance (fogmask/winter)."""
    if fourcc:
        pf = struct.pack('<II4s5I', 32, 0x4, fourcc.encode(), 0, 0, 0, 0, 0)
    else:
        pf = struct.pack('<II4s5I', 32, 0x20000, bytes(4), 8, 0xFF, 0, 0, 0)
    linear = linear if linear is not None else (w * h if not fourcc else max(1, w // 4) * max(1, h // 4) *
                                                (8 if fourcc == 'DXT1' else 16))
    return (struct.pack('<4s7I', b'DDS ', 124, 0x81007, h, w, linear, 0, 0) + bytes(44) + pf +
            struct.pack('<5I', 0x1000, 0, 0, 0, 0))


def write_l8_dds(a):
    """uint8 (h,w) array, row 0 = north -> fogmask.dds / winter.dds bytes (vanilla header layout)."""
    a = np.ascontiguousarray(a, np.uint8)
    return dds_header(a.shape[1], a.shape[0]) + a.tobytes()


def write_l8_tga(a):
    """uint8 (h,w) array, row 0 = north -> heightmap.tga bytes (type 3, 8 bpp, bottom-left origin)."""
    a = np.ascontiguousarray(a, np.uint8)
    return struct.pack('<BBB5xHHHHBB', 0, 0, 3, 0, 0, a.shape[1], a.shape[0], 8, 0) + a[::-1].tobytes()


def dxt5_decode(data, w=TILE, h=TILE):
    return Image.open(io.BytesIO(dds_header(w, h, 'DXT5') + data)).convert('RGBA')


def dxt5_encode(img):
    bio = io.BytesIO()
    img.convert('RGBA').save(bio, 'DDS', pixel_format='DXT5')
    b = bio.getvalue()
    assert b[84:88] == b'DXT5'
    return b[128:128 + (img.width // 4) * (img.height // 4) * 16]


# ---------------------------------------------------------------- supertexture .stpi/.stpd
def read_stpi(b):
    """-> dict(header=(6, W, H, 512, 262144), levels=[(tx, ty, [(off, csize, usize, id, pad)])], trailer)."""
    r = _R(b)
    header = r.take('5I')
    levels = []
    for _ in range(r.take('I')):
        tx, ty = r.take('II')
        levels.append((tx, ty, [r.take('5I') for _ in range(tx * ty)]))
    trailer = r.take('I')
    r.end()
    return dict(header=header, levels=levels, trailer=trailer)


def write_stpi(s):
    out = [struct.pack('<6I', *s['header'], len(s['levels']))]
    for tx, ty, recs in s['levels']:
        out += [struct.pack('<II', tx, ty)] + [struct.pack('<5I', *rec) for rec in recs]
    out.append(struct.pack('<I', s['trailer']))
    return b''.join(out)


def split_tile_chunks(raw):
    """Stored tile -> list of (zlib bytes, usize)."""
    out, p = [], 0
    while p < len(raw):
        c, u = struct.unpack_from('<II', raw, p)
        out.append((raw[p + 8:p + 8 + c], u))
        p += 8 + c
    assert p == len(raw)
    return out


def read_tile_raw(fh, rec):
    fh.seek(rec[0])
    return fh.read(rec[1])


def decode_tile(raw):
    """Stored tile bytes -> 512x512 RGBA image (RGB = colour, A = water mask: 255 sea/lake/river)."""
    data = b''.join(zlib.decompress(z) for z, _ in split_tile_chunks(raw))
    assert len(data) == TILE_BYTES
    return dxt5_decode(data)


def encode_tile(img):
    """512x512 image -> stored tile bytes (8 x [u32 csize, u32 usize, zlib level 9])."""
    assert img.size == (TILE, TILE)
    data = dxt5_encode(img)
    out = []
    for p in range(0, len(data), CHUNK):
        z = zlib.compress(data[p:p + CHUNK], 9)
        out += [struct.pack('<II', len(z), CHUNK), z]
    return b''.join(out)


def write_supertexture(stpi_path, stpd_path, width, height, tile_fn, nlevels=6, pad=0xFFFFFF00):
    """Stream a supertexture. width/height in level-0 texels (multiples of 512 << (nlevels-1)
    recommended; vanilla = 25.6 texels per world unit covering the whole world box).
    tile_fn(level, i, j) -> 512x512 image; level L texel = 2**L level-0 texels, j = 0 is the north row."""
    levels, off, ident = [], 0, 1
    with open(stpd_path, 'wb') as fh:
        for L in range(nlevels):
            tx, ty = max(1, (width >> L) // TILE), max(1, (height >> L) // TILE)
            recs = []
            for j in range(ty):
                for i in range(tx):
                    raw = encode_tile(tile_fn(L, i, j))
                    fh.write(raw)
                    recs.append((off, len(raw), TILE_BYTES, ident, pad))
                    off += len(raw)
                    ident += 1
            levels.append((tx, ty, recs))
    s = dict(header=(6, width, height, TILE, TILE_BYTES), levels=levels, trailer=1)
    with open(stpi_path, 'wb') as fh:
        fh.write(write_stpi(s))
    return s


def tile_fn_from_image(img):
    """Adapter for write_supertexture from one RGBA image covering the world box (any size).
    ponytail: whole source image in RAM; for >16k sources pass your own tile_fn that reads windows."""
    cache = {}

    def fn(level, i, j):
        if level not in cache:
            cache.clear()
            w, h = img.size
            cache[level] = img.resize((max(TILE, w >> level), max(TILE, h >> level)), Image.LANCZOS) if level else img
        return cache[level].crop((i * TILE, j * TILE, (i + 1) * TILE, (j + 1) * TILE))
    return fn


def read_level_image(stpi_path, stpd_path, level):
    """Assemble one pyramid level (use level >= 2 for Europe to keep memory sane)."""
    s = read_stpi(open(stpi_path, 'rb').read())
    tx, ty, recs = s['levels'][level]
    out = Image.new('RGBA', (tx * TILE, ty * TILE))
    with open(stpd_path, 'rb') as fh:
        for k, rec in enumerate(recs):
            out.paste(decode_tile(read_tile_raw(fh, rec)), ((k % tx) * TILE, (k // tx) * TILE))
    return out


# ---------------------------------------------------------------- world <-> raster helpers
def world_to_pixel(x, y, box, size):
    """World (x,y) -> (col,row) for any raster covering the world box (row 0 = north).
    box = (xmin, ymin, xmax, ymax), size = (w, h)."""
    xmin, ymin, xmax, ymax = box
    return (np.asarray(x) - xmin) * size[0] / (xmax - xmin), (ymax - np.asarray(y)) * size[1] / (ymax - ymin)


# ---------------------------------------------------------------- self-check
if __name__ == '__main__':
    import glob
    import hashlib
    import os
    import time

    ROOT = os.path.expanduser('~/.local/share/Steam/steamapps/common/Napoleon Total War/data/campaign_maps')
    SCRATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'work', 'scratch_display')
    rd = lambda p: open(p, 'rb').read()
    t0 = time.time()

    def check(pattern, reader, writer):
        files = sorted(glob.glob(os.path.join(ROOT, pattern), recursive=True))
        for f in files:
            b = rd(f)
            assert writer(reader(b)) == b, f
        return len(files)

    n = check('*/display/**/*.rigid_spline', read_spline, write_spline)
    print('rigid_spline   %4d files byte-exact' % n)
    n = check('*/display/bridges/*.markers', read_markers, write_markers)
    print('bridge.markers %4d files byte-exact' % n)
    n = check('*/display/world.markers', read_world_markers, write_world_markers)
    print('world.markers  %4d files byte-exact' % n)
    n = check('*/display/coastline/*.rigid_mesh', read_rigid_mesh, write_rigid_mesh)
    print('rigid_mesh     %4d files byte-exact' % n)
    n = check('*/display/trees/*.rigid_trees', read_rigid_trees, write_rigid_trees)
    print('rigid_trees    %4d files byte-exact' % n)
    n = check('*/display/supertexture/*.stpi', read_stpi, write_stpi)
    print('stpi           %4d files byte-exact' % n)
    for f in glob.glob(os.path.join(ROOT, '*/display/*/*.dds')):
        b = rd(f)
        if b[80:84] == struct.pack('<I', 0x20000) and struct.unpack_from('<I', b, 28)[0] == 0:
            h, w = struct.unpack_from('<II', b, 12)
            a = np.frombuffer(b, np.uint8, w * h, 128).reshape(h, w)
            assert write_l8_dds(a) == b, f
            assert (np.array(Image.open(f)) == a).all()  # Pillow agrees: row 0 = first stored row = north
    print('L8 dds (fogmask/winter, mip-less) byte-exact')
    n = 0
    for f in glob.glob(os.path.join(ROOT, '*/display/heightmap/heightmap.tga')):
        b = rd(f)
        if len(b) == 18 + np.prod(struct.unpack_from('<HH', b, 12)):  # egypt adds a TGA2 footer: skip
            assert write_l8_tga(np.array(Image.open(f))) == b, f
            n += 1
    print('heightmap.tga  %4d files byte-exact' % n)

    # semantic checks on Europe
    eu = os.path.join(ROOT, 'nap_europe/display')
    m = read_world_markers(rd(eu + '/world.markers'))
    print('europe world.markers:', [(g['cls'].split('_')[2], len(g['records'])) for g in m['groups']])
    assert write_world_markers(empty_world_markers())  # builds
    coast = read_rigid_mesh(rd(eu + '/coastline/coastline_group0.rigid_mesh'))
    v = coast['verts']
    assert np.allclose(np.hypot(*(v[0::2, [0, 2]] - v[1::2, [0, 2]]).T), 1.0, atol=1e-3)
    rebuilt = coastline_mesh([v[0::2, [0, 2]][:5]])
    assert rebuilt['verts'].shape == (10, 20) and len(rebuilt['idx']) == 24

    # supertexture: rebuild Europe .stpd from the index and compare streaming hashes
    s = read_stpi(rd(eu + '/supertexture/supertexture.stpi'))
    assert s['header'] == (6, 32768, 16384, 512, 262144) and [l[:2] for l in s['levels']] == \
        [(64, 32), (32, 16), (16, 8), (8, 4), (4, 2), (2, 1)]
    h1, h2, off, ident = hashlib.sha1(), hashlib.sha1(), 0, 1
    with open(eu + '/supertexture/supertexture.stpd', 'rb') as fh:
        for tx, ty, recs in s['levels']:
            for rec in recs:
                assert rec[0] == off and rec[2] == TILE_BYTES and rec[3] == ident
                raw = read_tile_raw(fh, rec)
                h1.update(raw)
                chunks = split_tile_chunks(raw)
                assert [u for _, u in chunks] == [CHUNK] * 8
                h2.update(b''.join(struct.pack('<II', len(z), u) + z for z, u in chunks))
                off += rec[1]
                ident += 1
        fh.seek(0)
        h0 = hashlib.sha1()
        for blk in iter(lambda: fh.read(1 << 24), b''):
            h0.update(blk)
    assert off == os.path.getsize(eu + '/supertexture/supertexture.stpd')
    assert h0.digest() == h1.digest() == h2.digest()
    print('stpd europe: %d tiles, chunk re-serialisation byte-exact (%.0f MB)' % (ident - 1, off / 1e6))

    # tile decode + re-encode (DXT5 is lossy and CA's zlib differs, so compare pixels not bytes)
    with open(eu + '/supertexture/supertexture.stpd', 'rb') as fh:
        tx, ty, recs = s['levels'][5]
        img = decode_tile(read_tile_raw(fh, recs[0]))
    again = decode_tile(encode_tile(img))
    err = np.abs(np.asarray(img, float) - np.asarray(again, float)).mean()
    assert err < 4, err
    print('tile re-encode mean abs error %.2f / 255' % err)

    # tiny synthetic supertexture write -> read
    os.makedirs(SCRATCH, exist_ok=True)
    src = Image.new('RGBA', (2048, 1024), (40, 90, 160, 255))
    src.paste((120, 140, 60, 0), (512, 256, 1536, 768))
    pi, pd = os.path.join(SCRATCH, 'test.stpi'), os.path.join(SCRATCH, 'test.stpd')
    write_supertexture(pi, pd, 2048, 1024, tile_fn_from_image(src), nlevels=3)
    s2 = read_stpi(rd(pi))
    assert [l[:2] for l in s2['levels']] == [(4, 2), (2, 1), (1, 1)]
    back = read_level_image(pi, pd, 0)
    assert np.abs(np.asarray(back, float) - np.asarray(src, float)).max() <= 8
    print('synthetic supertexture write/read ok (%d tiles)' % sum(len(l[2]) for l in s2['levels']))
    print('ALL OK in %.1fs' % (time.time() - t0))
