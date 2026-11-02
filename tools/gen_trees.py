"""World campaign-map trees (research/15): CA's vanilla Europe trees kept, generated forests wherever CA did not paint.

  python tools/gen_trees.py OUT.rigid_trees VARIANT_DIR [--scale 0.35] [--seed 7] [--preview PNG]
VARIANT_DIR (e.g. work/world/pt_w10) holds the startpos.esf and build_info.json whose towns the trees avoid.
world_build.py calls build() for the base mod's display/trees/campaign.rigid_trees.

Pipeline per 1 u cell of the theatre: land (worldgeo, Natural Earth minus natural lakes) outside vanilla's painted map
sheet (bake_terrain.painted) -> RESOLVE biome -> forest patches = rank of (smooth noise + 0.6 BMNG darkness) above
1 - F[biome] x 1805 clearing x polar fade -> Poisson candidates at RHO[biome] x scale, blue-noise thinned to MIN_D ->
per-biome model mix (cluster size/density by position in the patch) -> y = bilinear heightmap / 53.2, w = U(35, 38.5).
Keep-out: no new tree within KEEPOUT u of any settlement, town or port, vanilla ones included (vanilla trees near the new
regions' ones go too; CA's own placement around CA's towns is kept),
and no new tree within MIN_D of a vanilla one. Vanilla's 174 model paths stay in vanilla order (the model index is a u8).
Inputs: RESOLVE Ecoregions 2017 (Dinerstein et al., CC BY 4.0) work/geodata/ecoregions/Ecoregions2017.zip, rasterised once
to work/world/terrain/cache/biome.npy; the bake_terrain BMNG cache; work/world/terrain/heightmap.tga. About 1.5 GB, 15 s.
"""
import argparse, io, json, os, re, sys, time, zipfile
import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proj, display, geo, worldgeo, bake_terrain as bt

Image.MAX_IMAGE_PIXELS = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ECO_ZIP = os.path.join(ROOT, 'work/geodata/ecoregions/Ecoregions2017.zip')
BIOME = os.path.join(bt.CACHE, 'biome.npy')
VANILLA = geo.GAME + '/campaign_maps/nap_europe/display/trees/campaign.rigid_trees'
RES = 0.05            # biome raster, degrees
SCALE = 0.35          # instance density x RHO; tier A of research/15 (about 1.5x CA's own test file), the user's pick
KEEPOUT = 2.3         # u around settlements and ports: vanilla's 5th-percentile tree-to-settlement distance
MIN_D = 0.55          # vanilla nearest-neighbour 1st percentile

# RESOLVE BIOME_NUM -> mix; family weights: (w, 'c' cluster family | 's' single trees, model prefix)
MIX = {1: 'jungle', 2: 'dry', 3: 'conifer', 4: 'temperate', 5: 'conifer', 6: 'boreal', 7: 'savanna', 8: 'steppe',
       9: 'flooded', 10: 'montane', 11: 'tundra', 12: 'med', 14: 'mangrove'}
FAM = {
    'jungle':    [(.45, 'c', 'jungle'), (.35, 'c', 'indianjungle'), (.10, 'c', 'indiantree'), (.10, 's', 'palm')],
    'dry':       [(.45, 'c', 'indiantree'), (.25, 'c', 'jungle'), (.15, 's', 'indiantree1_'), (.15, 's', 'deserttree')],
    'conifer':   [(.55, 'c', 'lightconiferous'), (.25, 'c', 'mixedconiferous'), (.20, 'c', 'darkconiferous')],
    'temperate': [(.55, 'c', 'deciduousconiferous'), (.12, 's', 'deciduous'), (.13, 'c', 'lightconiferous'),
                  (.10, 'c', 'darkdeciduous'), (.10, 'c', 'mixedconiferous')],
    'boreal':    [(.75, 'c', 'darkconiferous'), (.10, 's', 'darkconiferous'), (.08, 'c', 'lightconiferous'), (.07, 's', 'coniferous')],
    'savanna':   [(.45, 's', 'deserttree'), (.35, 'c', 'indiantree'), (.20, 's', 'indiantree1_')],
    'steppe':    [(1., 'c', 'mediteranean01')],
    'flooded':   [(.5, 's', 'palm'), (.5, 'c', 'indiantree')],
    'montane':   [(.7, 'c', 'lightconiferous'), (.3, 'c', 'darkconiferous')],
    'tundra':    [(.8, 'c', 'darkconiferous'), (.2, 'c', 'lightconiferous')],
    'med':       [(.40, 'c', 'mediteranean01'), (.25, 'c', 'mediteranean02'), (.20, 'c', 'lightconiferous'), (.10, 's', 'olive'),
                  (.05, 's', 'palm')],
    'mangrove':  [(.6, 's', 'palm'), (.4, 'c', 'jungle')],
}
# forest share of the biome's land, and instances per u^2 inside a patch (calibrated on vanilla Europe, research/15 §3.2)
F = {1: .60, 2: .22, 3: .40, 4: .30, 5: .50, 6: .35, 7: .05, 8: .01, 9: .12, 10: .12, 11: .12, 12: .16, 14: .50}
RHO = {1: .20, 2: .15, 3: .22, 4: .26, 5: .28, 6: .28, 7: .12, 8: .15, 9: .15, 10: .20, 11: .22, 12: .26, 14: .20}
# 1805 clearing (lon0, lon1, lat0, lat1, keep): India, China, Japan, Java; eastern North America still mostly wooded.
# ponytail: placeholder boxes; HYDE 3.3 cropland for 1800 is the real source (research/15 §4)
CLEAR = [(68, 90, 8, 30, .35), (100, 125, 20, 40, .35), (128, 142, 30, 40, .5), (104, 112, -9, -6, .3), (-90, -60, 33, 47, .8)]
ASIA = (60, 155)      # lon: tropical forest here uses the indianjungle models


def biome_raster():
    """uint8 (3600, 7200) RESOLVE BIOME_NUM at 0.05 deg, north-up, 0 = none; cached."""
    if os.path.exists(BIOME):
        return np.load(BIOME)
    import shapefile, struct
    z = zipfile.ZipFile(ECO_ZIP)
    dbf = shapefile.Reader(dbf=io.BytesIO(z.read('Ecoregions2017.dbf')), encoding='latin-1')
    k = [x[0] for x in dbf.fields[1:]].index('BIOME_NUM')
    biomes = [int(float(r[k])) for r in dbf.iterRecords()]
    shp = z.read('Ecoregions2017.shp')                             # 243 MB; parsed as numpy views, not pyshp tuples
    recs, o = [], 100
    while o < len(shp):
        n, cl = struct.unpack_from('>II', shp, o); o += 8
        if struct.unpack_from('<I', shp, o)[0]:
            npart, npts = struct.unpack_from('<II', shp, o + 36)
            parts = list(np.frombuffer(shp, '<i4', npart, o + 44))
            p = np.frombuffer(shp, '<f8', npts * 2, o + 44 + 4 * npart).reshape(npts, 2)
            recs.append((np.ptp(p[:, 0]) * np.ptp(p[:, 1]), biomes[n - 1], p, parts))
        o += cl * 2
    W, H = int(360 / RES), int(180 / RES)
    img = Image.new('L', (W, H), 0); d = ImageDraw.Draw(img)
    for _, b, p, parts in sorted(recs, key=lambda t: -t[0]):      # big first, so enclaves paint over their host
        for s, t in zip(parts, parts[1:] + [len(p)]):
            ring = p[s:t]
            if len(ring) < 3 or (ring[:, 0] * np.roll(ring[:, 1], -1) - np.roll(ring[:, 0], -1) * ring[:, 1]).sum() > 0:
                continue                                           # CCW = hole; enclaves are their own records
            d.polygon([((x + 180) / RES, (90 - y) / RES) for x, y in ring], fill=b if b <= 14 else 0)
    a = np.array(img)
    np.save(BIOME, a)
    return a


def keepout_points(vdir):
    """(xy, new): world xy of every settlement residence and settlement/town/port slot of vdir/startpos.esf, plus the
    settlements, port buildings and docks of vdir/build_info.json; new = the point belongs to a non-vanilla region."""
    import esf, campaign_misc as cm
    sp = esf.load(os.path.join(vdir, 'startpos.esf'))
    pts, new = [], []
    def add(xy, reg):
        if tuple(xy) != (0, 0):
            pts.append(xy); new.append(not reg.startswith('eur_'))
    for s in cm.all_recs(sp.root, 'REGION_SLOT'):
        kind, reg = s.children[3].value.split(':')[:2]
        if kind in ('settlement', 'town', 'port'):
            add((s.children[6].value / 2 ** 20, s.children[7].value / 2 ** 20), reg)
    for it in cm.first_rec(sp.root, 'REGIONS_ARRAY').items:
        r = it[0].find('SETTLEMENT').children[0]
        add((r.children[10].value / 2 ** 20, r.children[11].value / 2 ** 20), it[0].children[0].value)
    del sp
    bi = json.load(open(os.path.join(vdir, 'build_info.json')))
    for s in bi['settlements'].values():
        add(s['pos'], '')
    for p in bi['ports']['placed'].values():
        add(p['building'], ''); add(p['dock'], '')
    return np.array(pts, float), np.array(new)


def build(keep, scale=SCALE, seed=7, preview=None):
    """keep = keepout_points(...) -> campaign.rigid_trees bytes."""
    keep_xy, new = keep
    t0 = time.time()
    rng = np.random.default_rng(seed)
    vt = display.read_rigid_trees(open(VANILLA, 'rb').read())
    stems = [os.path.basename(n)[14:-12].lower() for n, _ in vt['models']]
    sidx = {s: i for i, s in enumerate(stems)}
    clusters = lambda pre, size, dens: [i for s, i in sidx.items() if re.match(rf'^{pre}_{size}cluster_{dens}_+0?\d$', s)]
    singles = lambda pre: [i for s, i in sidx.items() if re.match(rf'^{pre}_?0?\d$', s)]
    lo, hi = proj.THEATRE_MIN, proj.THEATRE_MAX
    W, H = hi[0] - lo[0], hi[1] - lo[1]
    land = worldgeo.mask(worldgeo.land(natural=True), 1, lo, hi)               # (H, W), row 0 = north
    ys, xs = np.mgrid[0:H, 0:W]
    X, Z = lo[0] + xs + 0.5, hi[1] - ys - 0.5
    del xs, ys
    lon, lat = proj.to_lonlat(X, Z)
    bio = biome_raster()
    B = bio[((90 - lat) / RES).astype(int).clip(0, bio.shape[0] - 1), ((lon + 180) / RES).astype(int).clip(0, bio.shape[1] - 1)]
    miss = land & (B == 0)                                         # coast mismatch ecoregions vs NE: nearest biome
    if miss.any():
        _, (iy, ix) = ndimage.distance_transform_edt(B == 0, return_indices=True)
        B = np.where(miss, B[iy, ix], B)
    # CA's map sheet keeps CA's trees: sample the painted mask (6.4 px/u over the vanilla box) at the cell centres
    pm = bt.painted()
    pr, pc = ((bt.VBOX[3] - Z) * bt.P2).astype(int), ((X - bt.VBOX[0]) * bt.P2).astype(int)
    inside = (pr >= 0) & (pr < pm.shape[0]) & (pc >= 0) & (pc < pm.shape[1])
    painted = np.zeros(land.shape, bool)
    painted[inside] = pm[pr[inside], pc[inside]]
    del pm, pr, pc, inside
    clear = np.ones(lon.shape, np.float32)
    for l0, l1, a0, a1, k in CLEAR:
        clear[(lon >= l0) & (lon <= l1) & (lat >= a0) & (lat <= a1)] = k
    polar = np.clip((72 - np.abs(lat)) / 10, 0, 1)
    # patch field: two-scale smooth noise + BMNG darkness, rank-normalised over land
    nz = ndimage.gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), 4) * 4 \
        + 1.5 * ndimage.gaussian_filter(rng.standard_normal((H, W)).astype(np.float32), 14) * 14 / 4
    nz = (nz - nz.mean()) / nz.std()
    bm = bt.bmng_prep()
    er, ec = ((90 - lat) * 60).astype(int).clip(0, 10799), ((lon + 180) * 60).astype(int).clip(0, 21599)
    dark = np.zeros((H, W), np.float32)
    for r0 in range(0, H, 200):
        sl = slice(r0, r0 + 200); m = land[sl]
        tmp = np.zeros(m.shape, np.float32); tmp[m] = 255 - np.asarray(bm[er[sl][m], ec[sl][m]], np.float32).mean(1); dark[sl] = tmp
    del er, ec
    fld = nz + 0.6 * (dark - dark[land].mean()) / dark[land].std()
    del nz, dark
    u = np.zeros((H, W), np.float32)
    u[land] = fld[land].argsort().argsort() / (land.sum() - 1)
    f_eff = np.zeros((H, W), np.float32); rho = np.zeros((H, W), np.float32)
    for b in F:
        f_eff[B == b], rho[B == b] = F[b], RHO[b]
    f_eff *= clear * np.where(np.isin(B, (10, 11)), polar, 1)
    forest = land & ~painted & (u > 1 - f_eff)
    core = np.clip((u - (1 - f_eff)) / np.maximum(f_eff, 1e-3), 0, 1)
    # candidates, blue-noise thinning, then per-biome acceptance back to RHO x scale
    fy, fx = np.nonzero(forest)
    rep = np.repeat(np.arange(len(fy)), rng.poisson(rho[fy, fx] * 1.6 * scale))
    pts = np.column_stack([lo[0] + fx[rep] + rng.random(len(rep)), hi[1] - fy[rep] - rng.random(len(rep))])
    cell = np.column_stack([fy[rep], fx[rep]])
    keep = np.ones(len(pts), bool)
    pairs = cKDTree(pts).query_pairs(MIN_D, output_type='ndarray')
    for i, j in pairs[np.random.default_rng(1).permutation(len(pairs))]:
        if keep[i] and keep[j]:
            keep[j] = False
    van = [np.concatenate([c[1] for c in cells]) if cells else np.zeros((0, 4), 'f4') for _, cells in vt['models']]
    vxz = np.concatenate(van)[:, [0, 2]]
    keep &= ~np.isfinite(cKDTree(vxz).query(pts, distance_upper_bound=MIN_D)[0])
    ko, kn = cKDTree(keep_xy), cKDTree(keep_xy[new])
    n_near = int(np.isfinite(ko.query(pts[keep], distance_upper_bound=KEEPOUT)[0]).sum())
    n_vanilla = n_near - int(np.isfinite(kn.query(pts[keep], distance_upper_bound=KEEPOUT)[0]).sum())
    keep &= ~np.isfinite(ko.query(pts, distance_upper_bound=KEEPOUT)[0])
    pts, cell = pts[keep], cell[keep]
    Bc = B[cell[:, 0], cell[:, 1]]
    acc = np.ones(len(pts))
    for b in np.unique(Bc):
        acc[Bc == b] = min(1, RHO[b] * forest[B == b].sum() * scale / max((Bc == b).sum(), 1))
    sel = rng.random(len(pts)) < acc
    pts, cell, Bc = pts[sel], cell[sel], Bc[sel]
    # models
    cr = core[cell[:, 0], cell[:, 1]]
    asia = (lon[cell[:, 0], cell[:, 1]] > ASIA[0]) & (lon[cell[:, 0], cell[:, 1]] < ASIA[1])
    mid = np.zeros(len(pts), int)
    for b, fam in MIX.items():
        m = np.nonzero(Bc == b)[0]
        if not len(m):
            continue
        w = np.array([f[0] for f in FAM[fam]]); ch = rng.choice(len(w), len(m), p=w / w.sum())
        for k, (_, kind, pre) in enumerate(FAM[fam]):
            mk = m[ch == k]
            if kind == 's':
                if len(mk):
                    mid[mk] = rng.choice(singles(pre), len(mk))
                continue
            large = rng.random(len(mk)) < (.12 if fam in ('boreal', 'tundra') else .25)
            dense = (cr[mk] > .45) | (rng.random(len(mk)) < .15)
            for lg in (0, 1):
                for dn in (0, 1):
                    for a in (False, True):
                        s = mk[(large == lg) & (dense == dn) & (asia[mk] == a)]
                        if not len(s):
                            continue
                        p = {'jungle': 'indianjungle', 'indianjungle': 'indianjungle'}.get(pre, pre) if a else \
                            {'indianjungle': 'jungle'}.get(pre, pre)
                        ids = clusters(p, 'large' if lg else 'small', 'dense' if dn else 'sparse') \
                            or clusters(p, 'small', 'sparse') or clusters(p, 'small', 'dense')
                        assert ids, (p, lg, dn)
                        mid[s] = rng.choice(ids, len(s))
    # height: bilinear on the world heightmap (3.2 px/u, pixel centres), y = h / 53.2 (vanilla fit, r = 0.98)
    hm = np.array(Image.open(os.path.join(bt.OUT, 'heightmap.tga')), np.float32)
    fxp = np.clip((pts[:, 0] - proj.BOX_MIN[0]) * 3.2 - 0.5, 0, hm.shape[1] - 1.001)
    fyp = np.clip((proj.BOX_MAX[1] - pts[:, 1]) * 3.2 - 0.5, 0, hm.shape[0] - 1.001)
    i0, j0 = fyp.astype(int), fxp.astype(int); ty, tx = fyp - i0, fxp - j0
    h = (hm[i0, j0] * (1 - tx) + hm[i0, j0 + 1] * tx) * (1 - ty) + (hm[i0 + 1, j0] * (1 - tx) + hm[i0 + 1, j0 + 1] * tx) * ty
    del hm
    inst = np.column_stack([pts[:, 0], h / 53.2, pts[:, 1], rng.uniform(35.0, 38.5, len(pts))]).astype('<f4')
    # vanilla instances kept (minus those on the new settlements), new ones appended per model, one cell per model
    bbox = np.array([-1, -1, -1, 1, 1, 1], 'f4')
    models, dropped = [], 0
    for i, (name, _) in enumerate(vt['models']):
        v = van[i]
        if len(v):
            ok = ~np.isfinite(kn.query(v[:, [0, 2]], distance_upper_bound=KEEPOUT)[0])
            dropped += int((~ok).sum()); v = v[ok]
        models.append((name, [(bbox, np.concatenate([v, inst[mid == i]]))]))
    raw = display.write_rigid_trees(dict(version=vt['version'], f1=vt['f1'], u1=vt['u1'], models=models))
    # self-check: round trip, keep-out, no new tree on sea or on CA's painted sheet, heights on the terrain
    chk = display.read_rigid_trees(raw)
    assert display.write_rigid_trees(chk) == raw and len(chk['models']) == len(vt['models']) <= 255
    allp = np.concatenate([c[1] for _, cs in chk['models'] for c in cs])
    assert np.isinf(kn.query(allp[:, [0, 2]], distance_upper_bound=KEEPOUT)[0]).all()
    assert np.isinf(ko.query(inst[:, [0, 2]], distance_upper_bound=KEEPOUT)[0]).all()
    assert land[cell[:, 0], cell[:, 1]].all() and not painted[cell[:, 0], cell[:, 1]].any()
    assert (inst[:, 1] >= 0).all() and (inst[:, 1] <= 256 / 53.2).all()
    print(f'trees: {len(allp)} instances = vanilla {sum(len(v) for v in van) - dropped} (dropped {dropped} on new settlements)'
          f' + new {len(inst)} (scale {scale}, seed {seed}; keep-out {len(keep_xy)} points, {int(new.sum())} new, removed '
          f'{n_near} candidates, {n_vanilla} of them only near vanilla towns); {len(raw)} bytes ({time.time() - t0:.0f}s)')
    if preview:
        g = np.zeros((H, W), np.float32)
        np.add.at(g, (cell[:, 0], cell[:, 1]), 1)
        g = np.clip(g[:H // 4 * 4, :W // 4 * 4].reshape(H // 4, 4, W // 4, 4).sum((1, 3)) / 3, 0, 1)[..., None]
        lm = land[:H // 4 * 4:4, :W // 4 * 4:4]
        img = np.where(lm[..., None], (70, 80, 60), (20, 30, 50)) * (1 - g) + np.array([30, 200, 60]) * g
        Image.fromarray(img.astype(np.uint8)).save(preview)
    return raw


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('variant_dir')
    ap.add_argument('--scale', type=float, default=SCALE)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--preview')
    a = ap.parse_args()
    open(a.out, 'wb').write(build(keepout_points(a.variant_dir), a.scale, a.seed, a.preview))
