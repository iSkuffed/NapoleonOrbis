"""Assemble the world campaign map (Phase 4 M1) from the lane outputs and build the test pack.

  python tools/world_build.py --trees-for pt_w10 [--regions work/world/regions/regions_reuse.esf]
      -> work/mods/world_m1/campaign_maps/nap_world, work/world/startpos_m1.esf, then pack:
  python tools/world_build.py --trees-for pt_w10 --display-only   # refresh only world_m1's terrain rasters and trees (after a rebake)
  .venv/bin/python tools/packtool.py build "$G/zz_gn_world.pack" work/mods/world_m1   (mod pack, listed in user.script)
  .venv/bin/python tools/packtool.py build --type 2 "$G/local_en_gn.pack" work/mods/world_loc   (auto-loaded even in
      vanilla play: remove it after tests)

Inputs: work/world/pf/pathfinding.esf (tools/pf_gen.py), work/world/regions/*.esf (tools/regions_world.py),
work/world/terrain/{heightmap.tga, supertexture.stp?, campaign_detail_mask.dds} (tools/bake_terrain.py); world trees
(tools/gen_trees.py, kept off the towns and ports of work/world/<--trees-for>; world_m1 is built in nap_world.new and swapped in at the end).
Built here: sea_grids.esf for the world theatre, the startpos (vanilla Coalition, map renamed, visibility regridded
to the box, EPISODIC rect = box, pathfinder obstacle state emptied: research/00 G1-G3).
"""
import argparse, os, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esf, geo, proj, loc, packtool, campaign_misc as cm
from probe_g3 import empty_obstacles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = geo.GAME + '/campaign_maps/nap_europe'
MOD = os.path.join(ROOT, 'work/mods/world_m1')
LOC_MOD = os.path.join(ROOT, 'work/mods/world_loc')  # own pack: localisation.loc is read only from type-2 (patch) packs
OUT = MOD + '/campaign_maps/nap_world'
W = os.path.join(ROOT, 'work/world')
VANILLA_SP = os.path.join(ROOT, 'work/vanilla_loose_backup/campaigns/mp_eur_napoleon/startpos.esf')
VBOX_MIN = (-640, -320)


def sea_grid():
    s = cm.read_sea_grids(esf.load(SRC + '/sea_grids.esf'))
    lo, hi, vt = proj.THEATRE_MIN, proj.THEATRE_MAX, proj.VT_MIN
    cols, rows, cells = cm.make_sea_grid_cells(lo, hi, s.cell)
    dx, dy = int((vt[0] - lo[0]) // s.cell), int((vt[1] - lo[1]) // s.cell)
    assert (dx * s.cell, dy * s.cell) == (vt[0] - lo[0], vt[1] - lo[1]), 'vanilla sea cells must stay aligned'
    vc = s.cols
    k = lambda i: (i // vc + dy) * cols + i % vc + dx
    info = [[[], [], [], []] for _ in cells]
    for i, lists in enumerate(s.info):
        info[k(i)] = lists
    s.bmin, s.bmax, s.cols, s.rows, s.cells, s.info = tuple(map(float, lo)), tuple(map(float, hi)), cols, rows, cells, info
    s.edges = [(k(a), k(b), c) for a, b, c in s.edges]
    return esf.dumps(cm.write_sea_grids(s))


def minimap():
    """605x300 theatre image from the terrain bake's level-5 preview (0.8 px/u over the box), like vanilla's
    europe_map / stratradar (RGB TGA) and the startpos SAVE_GAME_HEADER/MAPS copy (BGRA u32, top-down).
    ponytail: aspect squeezed into vanilla's 605x300 frame; europe_lookup.tga (tools/lookup_tga.py) uses the same box."""
    import numpy as np
    from PIL import Image
    im = Image.open(W + '/terrain/preview_l5.png').convert('RGB')
    k = im.size[0] / (proj.BOX_MAX[0] - proj.BOX_MIN[0])
    crop = ((proj.THEATRE_MIN[0] - proj.BOX_MIN[0]) * k, (proj.BOX_MAX[1] - proj.THEATRE_MAX[1]) * k,
            (proj.THEATRE_MAX[0] - proj.BOX_MIN[0]) * k, (proj.BOX_MAX[1] - proj.THEATRE_MIN[1]) * k)
    return np.array(im.crop(tuple(map(round, crop))).resize((605, 300), Image.LANCZOS))


def startpos(mm=None):
    sp = esf.load(VANILLA_SP)
    if mm is not None:
        import numpy as np
        maps = next(iter(cm._iter_recs(sp.root, 'MAPS'))).items[0]
        assert [c.value for c in maps[1:4]] == [605, 300, 2420]
        bgra = np.concatenate([mm[..., ::-1], np.full(mm.shape[:2] + (1,), 255, np.uint8)], 2)
        maps[4].value = bgra.tobytes()
    n = cm.replace_strings(sp, {'nap_europe': 'nap_world', 'campaign_maps/nap_europe': 'campaign_maps/nap_world',
                                    'campaign_maps/nap_europe/display': 'campaign_maps/nap_world/display'})
    assert n == 4, n
    print('visibility arrays regridded', cm.regrid_visibility(sp, VBOX_MIN, proj.BOX_MIN, proj.BOX_MAX))
    rec = next(iter(cm._iter_recs(sp.root, 'EPISODIC_RESTRICTIONS')))
    assert [c.value for c in rec.children[9:13]] == [-640, -320, 640, 320]
    for c, v in zip(rec.children[9:13], (*proj.BOX_MIN, *proj.BOX_MAX)):
        c.value = float(v)
    empty_obstacles(sp)
    return esf.dumps(sp)


def loc_rows(probe=False):
    """Sea names for the new wld_ keys (data/world1805/seas.json). probe: also rename the vanilla Atlantic (in-game check
    that the merged localisation.loc is the one read)."""
    import json
    zones = json.load(open(os.path.join(ROOT, 'data/world1805/seas.json')))['zones']
    rows = [('regions_sea_onscreen_name_' + z['key'], z['name'], 0) for z in zones if z['key'].startswith('wld_')]
    if probe:
        rows.append(('regions_sea_onscreen_name_eur_atlantic_ocean_n', 'World Ocean (gn loc probe)', 0))
    return rows


def localisation(rows):
    """The game reads only vanilla-named loc files (an extra text/gn_world.loc is ignored, 2026-10-18), so merge our rows
    over the installed local_en_patch localisation.loc.
    ponytail: this embeds CA text in the test pack; a release must run this merge on the player's machine instead."""
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        assert packtool.extract(geo.GAME + '/local_en_patch.pack', t, 'text/localisation.loc') == 1
        ver, base = loc.parse(open(t + '/text/localisation.loc', 'rb').read())
    new = {k: (k, txt, tip) for k, txt, tip in rows}
    out = [new.pop(k, (k, txt, tip)) for k, txt, tip in base] + list(new.values())
    return loc.build(out, ver)


def display_files(out, trees):
    """Terrain rasters and the world trees (gen_trees.build bytes) into out/display."""
    d = out + '/display'
    for sub in ('heightmap', 'supertexture', 'detail', 'trees'):
        os.makedirs(d + '/' + sub, exist_ok=True)
    shutil.copy(W + '/terrain/heightmap.tga', d + '/heightmap/heightmap.tga')
    for ext in ('stpi', 'stpd'):
        shutil.copy(W + '/terrain/supertexture.' + ext, d + '/supertexture/supertexture.' + ext)
    shutil.copy(W + '/terrain/campaign_detail_mask.dds', d + '/detail/campaign_detail_mask.dds')
    open(d + '/trees/campaign.rigid_trees', 'wb').write(trees)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--regions', default=os.path.join(W, 'regions/regions_reuse.esf'))
    ap.add_argument('--loc-probe', action='store_true')
    ap.add_argument('--zones', action='store_true', help='named world seas: regions.esf + tools/world_zones.py')
    ap.add_argument('--trees-for', required=True, metavar='VARIANT',
                    help='work/world/VARIANT (startpos.esf + build_info.json): the towns and ports the trees avoid')
    ap.add_argument('--display-only', action='store_true')
    a = ap.parse_args()
    import gen_trees
    # ponytail: the keep-out is one variant's towns; regenerate the trees (--display-only) for a variant that moves them
    trees = gen_trees.build(gen_trees.keepout_points(os.path.join(W, a.trees_for)))
    if a.display_only:
        assert os.path.isdir(OUT), OUT
        display_files(OUT, trees)
        print('display refreshed', OUT)
        return
    out = OUT + '.new'                                  # built aside, swapped in at the end: a failure leaves OUT intact
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(SRC, out, ignore=shutil.ignore_patterns('fogmask', 'snow', 'snowmask', 'supertexture', 'heightmap'))
    if a.zones:
        a.regions = os.path.join(W, 'regions/regions.esf')
    shutil.copy(a.regions, out + '/regions.esf')
    shutil.copy(W + '/pf/pathfinding.esf', out + '/pathfinding.esf')
    display_files(out, trees)
    os.makedirs(LOC_MOD + '/text', exist_ok=True)
    open(LOC_MOD + '/text/localisation.loc', 'wb').write(localisation(loc_rows(a.loc_probe)))
    if a.zones:
        import world_zones as wz
        pb = wz.poi_zones(a.regions)
        open(out + '/poi.esf', 'wb').write(pb)
        open(out + '/sea_grids.esf', 'wb').write(wz.sea_grid_zones(a.regions, pb))
    else:
        open(out + '/sea_grids.esf', 'wb').write(sea_grid())
    from PIL import Image
    mm = minimap()
    for name in ('europe_map.tga', 'stratradar_europe.tga'):
        Image.fromarray(mm).save(out + '/' + name)
    import lookup_tga
    open(out + '/europe_lookup.tga', 'wb').write(lookup_tga.build(a.regions)[0])
    sp = startpos(mm)
    if a.zones:
        sp = esf.loads(sp)
        wz.startpos_zones(sp, a.regions)
        sp = esf.dumps(sp)
    shutil.rmtree(OUT + '.old', ignore_errors=True)
    if os.path.exists(OUT):
        os.rename(OUT, OUT + '.old')
    os.rename(out, OUT)
    shutil.rmtree(OUT + '.old', ignore_errors=True)
    open(os.path.join(W, 'startpos_m1.esf'), 'wb').write(sp)
    print('assembled', OUT)


if __name__ == '__main__':
    main()
