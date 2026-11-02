"""W1: every North American region of data/world1805/regions.json as a land region on top of the zones build
(work/world/regions/regions.esf: 139 regions, wld_* seas; startpos = work/world/zones/sp_abndeg.esf, stages 'abrndeg'),
cut out of the eur_map_west filler with the land_probe_b recipe generalised (several filler areas / islands, every
landmass, any number of regions per border point).

  .venv/bin/python tools/world_regions.py [build] [--wave w1|w2 | --variant w1a|w1|w2a|w2] [--no-land-sea | --stages ls|lsv|lm] [--compact]
  .venv/bin/python tools/world_regions.py check  [--wave w1|w2 | --variant w1a|w1|w2a|w2] [--no-land-sea | --stages ls|lsv|lm] [--compact]

Output work/world/<variant>[_nol][_s|_m][_v][_compact]/ (layout of probe A/B): overlay/campaign_maps/nap_world/{regions,
pathfinding,poi,sea_grids,trade_routes}.esf + europe_lookup.tga, overlay/db/..., loc_rows.tsv (world_build sea names
+ ours), startpos.esf, build_info.json.  Napoleon.exe with the patched building-display box (+-2048) is required.

Regions: the WAVES slices of data/world1805 up to the variant's wave (w1 = ame_us_northeast .. ame_nicaragua_costa_rica
minus its exclude: 36; w2 = w1 + ame_panama .. ame_brazil_center_west: 59; --compact merges every
full_only region into its merge_into region).  A region gets the filler pieces of its 1805 polygon: the one at /
nearest its capital and every other piece >= MIN_PIECE u^2 within NEAR u of it (one regions.esf area each, one new
pass_group per source filler area).  A region whose land cannot hold the eur_ireland settlement template (a 10 u
lattice: the LINE_OF_SIGHT bit arrays move in whole 10 u blocks) is deferred and stays filler (build_info 'deferred').

Variants: w1a = checkpoint, every region owned by a live vanilla faction (W1A_OWNER maps the new owners); w1 = the
new factions of factions.json generated (land_probe_b.faction_new + cai_faction.clone_cai_faction, oldenburg's art).
Stage letter 'l' (default on, --no-land-sea off): CAI_REGION_BOUNDARYs between the new land and its seas.
Stage 's' / 'm' (--stages, needs 'l' to matter): per-region beliefs for the 38 wld seas (sea_beliefs).  Without them 'l'
crashes the load at 0xD6D9E0: the boundary walk 0xD6B5B0 takes the other end of each CAI_REGION_BOUNDARY (0xC1BCE0) and
looks it up in each military strength manager (0xA73490 at 0xD6B758 / 0xD6B835, keyed by the region id); a wld sea has
no CAI_REGION_MILITARY_STRENGTH, the lookup returns NULL and CAI_REGION_MILITARY_STRENGTH::find (0xD7C4F0 -> 0xD6D9E0)
reads [NULL+0x10C] (zones 'v' is the same crash from the vanilla-sea end).  's' = everything a vanilla sea has
(world_zones stage h on the wld seas only: border analysis, occupancy, 7 military strengths, border patrol, region-group
map entry; zones v+h hung at load, h without v never ran); 'm' = the 7 military strengths + the occupancy analysis they take as subject + the region-group
map entry (MS alone did not help in game: the MS clones had no subject).  In game (2026-10-19): w1a_s (stages ls, with the
stage h owner-link fix) loads and runs 3 AI turns; w1a_m still crashed.  Stage 'v' (needs 's'): the CAI_REGION_BOUNDARYs
between vanilla seas and wld seas that world_zones parks (its stage v).
Stage 'p': a PORT slot for every new region with a regions.json port (port_probe.add_ports, after the build; failed
placements deferred into build_info 'ports'); output dir gets '_p'.
"""
import argparse, builtins, dataclasses, dis, collections, copy, hashlib, io, itertools, json, math, os, pickle, platform, re, shutil, struct, sys, tempfile, time, types, unicodedata, zipfile, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import shapely, shapely.affinity, shapely.ops
from shapely.geometry import MultiLineString, MultiPolygon, Point, Polygon, box, shape

import esf, geo, proj, loc, dbtable, packtool, display, campaign_misc as cm, regions_model as rm
import pathfinding_model as pm, pf_check, pf_gen, probe_g3
import land_probe as lp                                   # also points pf_check.side_intervals at the sea-aware copy
import land_probe_b as lpb
import world_zones as wz
import cai_faction as cf
import protectorates
import religion
import lookup_tga
from esf import Rec, Val
from regions_world import clone, lonlat_poly, set_rings

ROOT, W, MAPDIR = lp.ROOT, lp.W, lp.MAPDIR
DATA = os.path.join(ROOT, 'data/world1805')
ZREGIONS = os.path.join(W, 'regions/regions.esf')
ZPF = os.path.join(W, 'pf/pathfinding.esf')
ZSP = os.path.join(W, 'zones/sp_abndeg.esf')              # = world_build --zones startpos (stages 'abrndeg')
SRC = lp.SRC
FIX, S = lp.FIX, lp.S
GRID = lpb.GRID
TPL, TPL_TOWN = lp.TPL, lp.TPL_TOWN
# wave -> regions.json slice [first .. last] minus exclude; a wave builds every slice up to its own (w2 = w1 + w2's)
WAVES = {'w1': ('ame_us_northeast', 'ame_nicaragua_costa_rica',
                {'ame_iceland': 'Europe (W1 is North America)', 'ame_greenland_arctic': 'impassable (regions.json)',
                 'ame_panama': 'merges into ame_new_granada (South America)'}),
         'w2': ('ame_panama', 'ame_brazil_center_west', {}),
         'w3': ('afr_morocco', 'afr_malta', {}),
         'w4': ('mea_cyprus', 'mea_north_caucasus', {}),
         'w5': ('asi_volga_urals', 'asi_ceylon_coast', {}),
         'w6': ('eas_north_china', 'eas_mindanao_sulu', {}),
         'w7': ('oce_hawaii', 'oce_te_waipounamu', {}),
         'w8': ('asi_olonets', 'asi_voronezh', {}),     # the Russian filler between vanilla Russia and w5 (weld step 1)
         'w9': ('eur_gotland', 'eur_yorkshire', {})}       # splits of vanilla Europe regions (regions.json split_of)
VARIANTS = [w + a for w in WAVES for a in ('a', '')]       # <wave>a = checkpoint (vanilla owners), <wave> = new factions
W1A_OWNER = {'united_states': 'britain', 'native_plains': 'spain', 'native_pacific_nw': 'britain', 'haiti': 'france',
             'amazonian_peoples': 'portugal', 'mapuche': 'spain'}
ADJ = {'united_states': 'American', 'native_plains': 'Plains', 'native_pacific_nw': 'Pacific Northwest', 'haiti': 'Haitian',
       'amazonian_peoples': 'Amazonian', 'mapuche': 'Mapuche',
       'morocco': 'Moroccan', 'algiers': 'Algerian', 'tunis': 'Tunisian', 'tripolitania': 'Tripolitanian', 'egypt': 'Egyptian',
       'mamluks': 'Mamluk', 'saharan_confederations': 'Saharan', 'sennar': 'Funj', 'darfur': 'Darfuri', 'ethiopia': 'Ethiopian',
       'oman': 'Omani', 'great_lakes_kingdoms': 'Great Lakes', 'lunda_luba_kingdoms': 'Lunda', 'west_central_african_peoples':
       'Lower Guinean', 'oyo': 'Oyo', 'sokoto_caliphate': 'Sokoto', 'bornu': 'Bornuan', 'segu_bambara': 'Bambara', 'asante': 'Asante',
       'guinea_coast_peoples': 'Guinea Coast', 'futa_jallon': 'Futa Jallon', 'south_african_chiefdoms': 'Southern African',
       'merina': 'Merina', 'persia': 'Persian', 'diriyah': 'Saudi', 'yemen': 'Yemeni',
       'kazakh_hordes': 'Kazakh', 'khiva': 'Khivan', 'bukhara': 'Bukharan', 'kokand': 'Kokandi', 'durrani_empire': 'Afghan',
       'sikh_empire': 'Sikh', 'sindh_baluchistan': 'Sindhi', 'kalat': 'Baloch', 'east_india_company': 'Company', 'assam_hill_peoples': 'Assamese',
       'nepal': 'Nepali', 'awadh': 'Awadhi', 'rajput_states': 'Rajput', 'maratha_peshwa': 'Maratha', 'hyderabad': 'Hyderabadi',
       'maratha_bhonsle': 'Bhonsle', 'maratha_scindia': 'Scindia', 'maratha_holkar': 'Holkar', 'mysore': 'Mysorean',
       'qing': 'Qing', 'joseon': 'Korean', 'tokugawa_japan': 'Japanese', 'dai_viet': 'Vietnamese',
       'siam': 'Siamese', 'konbaung_burma': 'Burmese', 'malay_sultanates': 'Malay', 'aceh': 'Acehnese',
       'bornean_sultanates': 'Bornean', 'banjar': 'Banjarese', 'kingdom_of_hawaii': 'Hawaiian', 'pomare_tahiti': 'Tahitian',
       'pacific_islanders': 'Pacific Islander', 'papuan_peoples': 'Papuan', 'aboriginal_nations': 'Aboriginal', 'maori_iwi': 'Maori',
       'russian_american_company': 'Russian-American'}
AMERICA_X = -600.0                # u: filler areas west of this are America
MIN_PIECE = 100.0                 # u^2: smallest extra filler piece (island, second landmass) a region takes
PIECE_MIN = {'asi_olonets': 10.0}  # u^2: per-region MIN_PIECE (pt_w11: Olonets' 10.8 u^2 of eur_map_west 3 reaches the vanilla
                                  # map edge at eur_finland, the WELD pair's border)
NEAR = 300.0                      # u: extra pieces this close to the capital only
CAP_NEAR = 30.0                   # u: a capital in the sea takes the nearest filler area this close
SETTLE_MARGIN = 1.5               # u: settlement this far inside its singleton land (land_probe_b: 3; narrow islands)
SETTLE_MARGIN_AT = {'ame_puerto_rico': 1.0}   # per region: Puerto Rico (inscribed radius 2.6 u) fits no spot at 1.5
MIN_LAND = 4.0                    # u^2: smaller pathfinding land parts are dropped (stay off-map)
BAND, LAND_BAND, MAX_LAND_POLYS = lpb.BAND, lp.LAND_BAND, lpb.MAX_LAND_POLYS
SIMPLIFY, SKIRT, BIG_GAP = lpb.SIMPLIFY, lpb.SKIRT, lpb.BIG_GAP
PF_WORDS_MAX = 1 << 21           # pathfinding polygon words: a boundary's 22-bit offset with bit 21 set is read as a
                                  # dynamic polygon (FUN_00b108d0 via FUN_00b79da0; W5 v1 crashed at load at 2^21 + 1082)
BAND_SIMPLIFY = 0.35              # u: composite band lines (was 0.02; < BAND keeps every region covered by its band)
LAND_SIMPLIFY = 0.45              # u: pathfinding land outline (was 0.05; < 0.5 LAND_BAND keeps the off-map margin)
FILLER_KEEP = 100.0               # u^2: a filler component this big stays filler (W5: the Caspian, the Lapland-Karelia-Vologda band
                                  # cut off by the new Russian regions, Chukotka) instead of joining a neighbour region
PATCHED_HALF, DISPLAY_MARGIN = lpb.PATCHED_HALF, lpb.DISPLAY_MARGIN
RGB0 = (201, 78)                  # regions_tables colour (201, 78, n)
LOC0 = 1805000101                 # settlement CAMPAIGN_LOCALISATION suffix base
STAGES = 'l'
REGION_CEILING = 360              # pt_w11: 347 regions played AI turns 1-8 (2026-10-28); G4b 333; no u8 region cap; w9 359
                                  # 4 AI turns. The binding limits are checked on their own: pathfinding domain ids (10-bit,
                                  # 1023 = none) and the lookup palette (PALETTE)
DOMAIN_IDS = 1023                 # pathfinding Trait.path_id is 10 bits, 1023 = no domain
ROUTES = os.path.join(DATA, 'routes.json')
SETTLE_R = 12.0                   # u: passable round the capital of a region inside a corridor mask
CORRIDOR_MIN = 2.0                # u^2: smaller impassable mask pieces stay passable
LAKE_MIN = 14.0                   # u^2 (~1.4 deg^2): natural lakes (worldgeo.natural_lake, touching NE lakes merged) this big are
                                  # impassable region areas (pt_w11; Lake Chad's modern NE outline is 14.3); smaller stay land
LAKE_SIMPLIFY = 0.3               # u: lake outline
# --stress-land N (G4b, region-count stress test): dummy regions 'stress_NNN' until regions.esf has N land regions
STRESS_OWNER = lp.OWNER           # Britain: the startpos template owner, no hand-over
STRESS_FILLER = 'eur_map_east'    # cut from its Afro-Eurasian filler area, outside the vanilla map box
STRESS_SIDE, STRESS_BAR, STRESS_GAP, STRESS_MARGIN = 20.0, 4, 6.0, 4.0   # u: square side, squares per bar, bar gap, coast
STRESS_OFF = 0.37                 # u: lattice offset (square edges off the 2 u pathfinding cell sides)
VANILLA_BOX = box(-394 - 20, -181 - 20, 330 + 20, 279 + 20)              # no dummies over the vanilla map


class Retry(Exception):
    """A region cannot be built: defer it and carve again."""


def out_dir(variant, stages, compact, stress=0):
    return os.path.join(W, variant + ('' if 'l' in stages else '_nol') + ''.join('_' + c for c in 'smvpj' if c in stages)
                        + ('_compact' if compact else '') + (f'_stress{stress}' if stress else ''))


def slug(name):
    s = unicodedata.normalize('NFKD', re.sub(r'\(.*?\)', '', name)).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '_', s.lower().replace("'", '')).strip('_')


# ---------------------------------------------------------------- specs
def waves(variant):
    """[(first, last, exclude)] of the waves up to variant's."""
    w = list(WAVES)
    return [WAVES[x] for x in w[:w.index(variant.rstrip('a')) + 1]]


def excluded(variant):
    """{key: reason} of the excluded regions no wave of variant builds."""
    built = {k for s in specs(variant) for k in s['members']}
    return {k: v for _, _, ex in waves(variant) for k, v in ex.items() if k not in built}


def specs(variant, compact=False):
    """[region spec] in build order (= regions.json order)."""
    R = json.load(open(os.path.join(DATA, 'regions.json')))
    keys = [r['key'] for r in R]
    na = [r for f, l, ex in waves(variant) for r in R[keys.index(f):keys.index(l) + 1] if r['key'] not in ex]
    out = []
    for r in na:
        if compact and r.get('full_only'):
            continue
        members = [r['key']] + [x['key'] for x in na if compact and x.get('full_only') and x['merge_into'] == r['key']]
        c = r['capital']
        owner = (W1A_OWNER.get(r['owner']) or (r['owner'] if r['owner'] in VANILLA else lp.OWNER)) if variant.endswith('a') else r['owner']
        out.append(dict(key=r['key'], name=r['name'], members=members, owner=owner, data_owner=r['owner'],
                        town=slug(c['name']), town_name=c['name'], cap=(c['lon'], c['lat']),
                        cap_xy=tuple(map(float, proj.to_world(c['lon'], c['lat']))), rebel=f"{r['name']} Rebels",
                        **({'minimap_parent': r['minimap_parent']} if r.get('minimap_parent') else {}),
                        **({'split_of': r['split_of'], 'split_areas': r.get('split_areas'), 'split_ring': r.get('split_ring')}
                           if r.get('split_of') else {})))
    assert len({s['key'] for s in out}) == len(out) and all(all(m in keys for m in s['members']) for s in out)
    for n, s in enumerate(out):
        s.update(rgb=rgb_of(n), loc_suffix=LOC0 + n)
    return out


VANILLA = {f['key'] for f in json.load(open(os.path.join(DATA, 'factions.json'))) if f.get('vanilla')}


def rgb_of(n):
    return RGB0[0], RGB0[1] + n // 256, n % 256


# ---------------------------------------------------------------- regions.esf
def is_america(key):
    return key.startswith('ame_')


_F = {}       # features() / corridor_masks(): results that depend on nothing a deferral changes, kept for the next attempt


def _memo(key, f):
    if key not in _F:
        _F[key] = f()
    return _F[key]


def features(sp_, deferred, east=False):
    """{key: world polygon} of every 1805 feature in America (x < AMERICA_X; east: the rest of the world), ours = union
    of the members; seaward skirt as land_probe_b.features (non-ours first)."""
    shp = _memo('shp', lambda: {f['properties']['key']: shape(f['geometry'])
                                for f in json.load(open(lpb.GEOJSON))['features']})
    win = (box(AMERICA_X, proj.BOX_MIN[1], proj.BOX_MAX[0], proj.BOX_MAX[1]) if east
           else box(proj.BOX_MIN[0], proj.BOX_MIN[1], AMERICA_X, proj.BOX_MAX[1]))
    world = lambda s: shapely.union_all([lonlat_poly(list(p.exterior.coords)) for p in getattr(s, 'geoms', [s])])
    keys = [s['key'] for s in sp_ if s['key'] not in deferred]
    ck = (keys, [s['members'] for s in sp_ if s['key'] in keys])
    last = _F.get(('last', east))                       # a deferral in the other window leaves this one's inputs as they were
    if last and last[0] == ck:
        return dict(last[1])
    mem = {m for s in sp_ if s['key'] in keys for m in s['members']}
    raw = {k: _memo((east, 'f', k), lambda: world(s).intersection(win)) for k, s in shp.items() if k not in mem}
    raw.update({s['key']: _memo((east, 'r', s['key'], tuple(s['members'])),
                                lambda: shapely.union_all([world(shp[m]) for m in s['members']]).intersection(win))
                for s in sp_ if s['key'] in keys})
    mine = shapely.union_all([raw[k] for k in keys])
    x0, y0, x1, y1 = mine.bounds
    near = box(x0 - 4, y0 - 4, x1 + 4, y1 + 4)
    out = {k: _memo((east, 'o', k, id(v)), lambda: shapely.make_valid(shapely.simplify(v, SIMPLIFY)))
           for k, v in raw.items() if not v.is_empty and v.intersects(near)}
    allf = shapely.union_all(list(out.values()))
    grown, taken = {}, None
    for k in sorted(out, key=lambda k: (k in keys, k)):
        gk = shapely.union_all([out[k], out[k].buffer(SKIRT).difference(allf)])
        if taken is not None:
            gk = gk.difference(taken)
        grown[k] = shapely.union_all([Polygon(q.exterior) for q in shapely.get_parts(shapely.make_valid(gk))
                                      if q.geom_type == 'Polygon'])
        taken = grown[k] if taken is None else shapely.union_all([taken, grown[k]])
    _F[('last', east)] = (ck, grown)
    return dict(grown)


def partition(A, feats, keys, holes=()):
    """land_probe_b.partition_filler for one filler area and any key set: -> {label: [rings]}, label None = filler
    (its largest component kept if >= BIG_GAP u^2, else the area is used up: no None entry); a key absent from the
    result lost all its faces.  Other filler components stay filler as labels ('filler', n) when >= FILLER_KEEP u^2
    (the Caspian; land no feature covers) or inside feature '_vanilla_gap' (vanilla_gap's strip), unless one region
    encloses it (lakes inside one region's admin-1 units stay its land: Aral, Balkhash, Baikal); smaller
    ones join their longest-bordering neighbour.  holes: labels whose piece may enclose holes (a split_ring piece round
    impassable areas it takes whole: Thuringia)."""
    cut = shapely.set_precision(MultiLineString([r for f in feats.values() for p in getattr(f, 'geoms', [f])
                                                 for r in [p.exterior] + list(p.interiors)]), GRID)
    cut = shapely.intersection(cut, A.buffer(1.0))
    net = shapely.union_all([A.exterior] + list(A.interiors) + [cut])
    faces = [p for p in shapely.get_parts(shapely.polygonize(shapely.get_parts(net))) if A.contains(p.representative_point())]
    assert abs(sum(p.area for p in faces) - A.area) < 1e-6 * A.area, 'faces must tile the filler area'
    tree = shapely.STRtree([feats[k] for k in feats])
    fk = list(feats)
    rings, lab, gapf, wlab = [], [], set(), {}
    for p in faces:
        o = shapely.geometry.polygon.orient(p, 1.0)
        rings.append([tuple((float(x), float(y)) for x, y in r.coords[:-1]) for r in [o.exterior] + list(o.interiors)])
        q = p.representative_point()
        hit = [fk[i] for i in tree.query(q, predicate='within')]
        ws = [h[len(WELD_STRIP):] for h in hit if h.startswith(WELD_STRIP)]
        hit = [h for h in hit if not h.startswith(WELD_STRIP)]
        if len(hit) > 1:                                  # an enclave inside another feature (features() fills holes): the
            hit = [h for h in hit if not any(o != h and feats[h].within(feats[o]) for o in hit)] or hit   # encloser, or
        lab.append(hit[0] if hit and hit[0] in keys else None if hit or p.area > BIG_GAP else '?')    # its face is a hole (W7: kazakh|p0 in khiva|p0)
        if '_vanilla_gap' in hit:
            gapf.add(len(lab) - 1)
        if ws and ws[0] in keys:
            wlab[len(lab) - 1] = ws[0]
    owner = {}
    for i, rs in enumerate(rings):
        for r in rs:
            for ed in lpb.ring_edges(r):
                owner[ed] = i
    adj = collections.defaultdict(collections.Counter)
    for (a, b), i in owner.items():
        j = owner.get((b, a))
        if j is not None and j != i:
            adj[i][j] += math.dist(a, b)

    def components(label):
        seen, comps = set(), []
        for i in (i for i, l in enumerate(lab) if l == label):
            if i in seen:
                continue
            comp, todo = [], [i]
            seen.add(i)
            while todo:
                k = todo.pop(); comp.append(k)
                for j in adj[k]:
                    if j not in seen and lab[j] == label:
                        seen.add(j); todo.append(j)
            comps.append(comp)
        return comps

    area = lambda cc: sum(faces[k].area for k in cc)
    def keep(cc):                                         # not a hole in one region: those stay part of it
        ss = set(cc)
        if not (area(cc) >= FILLER_KEEP or ss & gapf):
            return False
        edges = [ed for k in cc for r in rings[k] for ed in lpb.ring_edges(r)]
        nb = {lab[owner[(b, a)]] for a, b in edges if (b, a) in owner and owner[(b, a)] not in ss}
        return not (all((b, a) in owner for a, b in edges) and len(nb) == 1 and next(iter(nb)) is not None)
    for _ in range(100):
        changed = 0
        for i, l in enumerate(lab):
            if l == '?':
                c = collections.Counter({lab[j]: ln for j, ln in adj[i].items() if lab[j] != '?'})
                if c:
                    lab[i] = c.most_common(1)[0][0]; changed += 1
        for label in list(keys) + [None]:
            comps = sorted(components(label), key=lambda cc: -sum(faces[k].area for k in cc))
            big = comps and (label is not None or sum(faces[k].area for k in comps[0]) >= BIG_GAP)
            drop = comps[1:] if big else comps            # filler: even its largest piece goes if < BIG_GAP
            if label is None:
                drop = [cc for cc in drop if not keep(cc)]
            for cc in drop:
                c = collections.Counter()
                for k in cc:
                    for j, ln in adj[k].items():
                        if j not in cc and lab[j] != '?':
                            c[lab[j]] += ln
                c.pop(label, None)
                if c:
                    new = c.most_common(1)[0][0]
                    for k in cc:
                        lab[k] = new
                    changed += 1
        if not changed:
            break
    assert '?' not in lab
    for i, k in wlab.items():                             # the weld strip: filler faces join their welded region,
        if lab[i] is None:                                # pieces cut off from its main body stay filler
            lab[i] = k
    for k in set(wlab.values()):
        for cc in sorted(components(k), key=lambda cc: -area(cc))[1:]:
            for i in cc:
                assert i in wlab, ('weld strip split', k)
                lab[i] = None
    for _ in range(20):                                   # lake_cut labels: faces of one region enclosed by another of its
        moved = 0                                         # labels (pieces between a lake's arms) join the encloser
        for label in [l for l in keys if '|' in l or l + '|l0' in keys]:     # (a lake piece never turns passable)
            mine = [r for i, l in enumerate(lab) if l == label for r in rings[i]]
            rs = lpb.merge_faces(mine) if mine else None
            for r in [r for r in rs or [] if lpb.signed_area(r) < 0]:
                H = Polygon(r).buffer(1e-6)
                inn = [i for i, l in enumerate(lab) if l != label and faces[i].within(H)]
                if inn and all(isinstance(lab[i], str) and lab[i].split('|')[0] == label.split('|')[0]
                               and ('|l' in label or '|l' not in lab[i]) for i in inn):
                    for i in inn:
                        lab[i] = label
                    moved += 1
        if not moved:
            break
    comps = sorted(components(None), key=lambda cc: -area(cc))
    extra = comps[1:] if comps and area(comps[0]) >= BIG_GAP else comps
    for n, cc in enumerate(extra):
        for k in cc:
            lab[k] = ('filler', n)
    out = {}
    for label in list(keys) + [None] + [('filler', n) for n in range(len(extra))]:
        mine = [r for i, l in enumerate(lab) if l == label for r in rings[i]]
        if not mine:
            continue
        rs = lpb.merge_faces(mine)
        assert rs is not None, ('pinched boundary', label)
        outer = [r for r in rs if lpb.signed_area(r) > 0]
        assert len(outer) == 1 and (label is None or isinstance(label, tuple) or label in holes or len(rs) == 1), (label, len(outer), len(rs))
        out[label] = rs
    return out


def pieces(e, sp_, feats, deferred):
    """{key: [(filler region index, filler area index), primary first]} and the pieces not taken.  America takes
    eur_map_west's American areas; the rest of the world any theatre area of eur_map_west / eur_map_east (Malta is a
    west area)."""
    rd = e.root.find('region_data')
    names = [it[0].value for it in rd.find('regions').items]
    wi, ei = names.index('eur_map_west'), names.index('eur_map_east')
    tb = lambda q, x1: (q.bounds[0] > proj.THEATRE_MIN[0] and q.bounds[1] > proj.THEATRE_MIN[1] and q.bounds[2] < x1
                        and q.bounds[3] < proj.THEATRE_MAX[1])     # not the box frame fillers (west 9, east 86)
    AP = rm.area_polygons(rd)
    am = {(wi, c & 0xFFFF): q for c, q in AP.items() if c >> 16 == wi and tb(q, AMERICA_X)}
    ea = {(c >> 16, c & 0xFFFF): q for c, q in AP.items() if c >> 16 in (wi, ei) and tb(q, proj.THEATRE_MAX[0])}
    out, skipped = {}, []
    for zone in (am, ea):
        o, sk = _pieces(zone, [s for s in sp_ if is_america(s['key']) == (zone is am)], feats, deferred)
        out.update(o); skipped += [(k, a[1] if a[0] == wi else f'{names[a[0]]}:{a[1]}', v) for k, a, v in sk]
    return out, skipped


def _pieces(west, sp_, feats, deferred):
    ais = list(west)
    tree = shapely.STRtree([west[a] for a in ais])
    out, skipped = {}, []
    for s in sp_:
        k = s['key']
        if k in deferred:
            continue
        f, cap = feats[k], Point(s['cap_xy'])
        share = {ais[i]: west[ais[i]].intersection(f).area for i in tree.query(f, predicate='intersects')}
        share = {a: v for a, v in share.items() if v > 0}
        prim = next((a for a in share if west[a].contains(cap)), None)
        if prim is None:
            near = sorted((west[a].distance(cap), a) for a, v in share.items() if v > 1.0)
            prim = near[0][1] if near and near[0][0] <= CAP_NEAR else None
        if prim is None:
            deferred[k] = 'no filler land at / within %g u of the capital' % CAP_NEAR
            continue
        sec = sorted(a for a, v in share.items() if a != prim and v >= PIECE_MIN.get(k, MIN_PIECE) and west[a].distance(cap) <= NEAR)
        out[k] = [prim] + sec
        skipped += [(k, a, round(v, 1)) for a, v in sorted(share.items()) if a not in out[k] and v >= 1.0]
    return out, skipped


def split_pieces(e, sp_, feats, take, deferred):
    """Splits of vanilla Europe regions (regions.json split_of) -> take / feats in place.  split_areas: impassable areas
    taken whole (Gotland): feature = the areas' union, take = those areas (carve: like a filler area; the region's
    later areas re-index).  split_ring: a lon/lat ring cutting the region (Crimea): feature = the projected ring, take =
    every area of the region it meets, the one holding the capital first (carve keeps the areas' own flags)."""
    rd = e.root.find('region_data')
    names = [it[0].value for it in rd.find('regions').items]
    AP = rm.area_polygons(rd)
    for s in sp_:
        if 'split_of' not in s or s['key'] in deferred:
            continue
        ri = names.index(s['split_of'])
        if s.get('split_ring'):
            F = lonlat_geom(Polygon(s['split_ring']))
            hit = sorted((not AP[c].contains(Point(s['cap_xy'])), c & 0xFFFF) for c in AP
                         if c >> 16 == ri and AP[c].intersection(F).area > 0)
            assert hit and not hit[0][0], ('split_ring: the capital is in no area of the region it cuts', s['key'])
            take[s['key']] = [(ri, a) for _, a in hit]
            feats[s['key']] = F
            continue
        assert s['split_areas'], ('split without split_areas or split_ring', s['key'])
        take[s['key']] = [(ri, a) for a in s['split_areas']]
        feats[s['key']] = shapely.union_all([AP[ri << 16 | a] for a in s['split_areas']]).buffer(0.5)


VANILLA_GAP = 2.0                 # u: new land keeps this far from vanilla land that borders the filler (eur_little_tatary)
# stage 'j' (weld step 2): new region -> the vanilla land regions it joins (regions.esf edge, pathfinding land, CAI boundary,
# poi neighbours).  asi_olonets -> eur_finland (pt_w11): vanilla Finland's pathfinding land starts 14.3 u from the border,
# so that pair's weld land reaches WELD_DEEP into Finland (its off-map wedge east of the vanilla map edge); asi_olonets
# keeps its strip to eur_novgorod (vanilla land 3.0 u off; reached through asi_vologda)
WELD = {'asi_olonets': ('eur_finland',),
        'asi_vologda': ('eur_novgorod', 'eur_moscow_guberniya'),
        'asi_voronezh': ('eur_moscow_guberniya', 'eur_belgorod_guberniya', 'eur_little_tatary'),
        'asi_volga_urals': ('eur_moscow_guberniya',),
        'mea_north_caucasus': ('eur_little_tatary',)}
WELD_ZONE = VANILLA_GAP + 0.5     # u: weld cells = the cells within this of both regions of a pair
WELD_DEPTH = 3.0                  # u: weld land fills the vanilla region's off-map rim this deep
WELD_DEEP = {('asi_olonets', 'eur_finland'): 18.0}   # u: per-pair WELD_DEPTH; the weld cells then cover the vanilla region
                                  # this deep too (Finland's land 14.3 u off: 7.8 u^2 of it within 16 u, 32 within 18)
WELD_STRIP = '_weld|'             # vanilla_gap's feature for the strip a welded region keeps


def vanilla_gap(e, feats, keys, weld=None):
    """Filler strip between new regions and the vanilla land regions that share an edge with eur_map_west / east (Russia,
    Scandinavia): the pathfinding does not weld new land to vanilla land domains, so regions.esf must not join their
    pass groups either.  Our features lose the strip, which becomes feature '_vanilla_gap' (partition label None =
    filler).  weld (stage 'j', WELD): a feature keeps the strip of the vanilla regions it is welded to (its region then
    shares their edge): feats[k] stays as without the weld, that strip is feature WELD_STRIP + k, which partition
    labels k only after its filler decisions (every other face is labelled as without the weld).  -> (the strip, None when no feature
    comes near; geometry for pathfinding: the whole strip G and the welded vanilla regions' polygons)."""
    rg = rm.extract(e)['regions']
    nm = [r['name'] for r in rg]
    fill = {nm.index('eur_map_west'), nm.index('eur_map_east')}
    vl = sorted({a if b in fill else b for (a, b), ln in wz.shared_lengths(e).items()
                 if ln > 0 and (a in fill) != (b in fill) and rg[a if b in fill else b]['kind'] == 'land'})
    P = rm.area_polygons(e.root.find('region_data'))
    V = {i: shapely.union_all([P[c] for c in P if c >> 16 == i]) for i in vl}
    Gv = {i: V[i].buffer(VANILLA_GAP) for i in vl}
    G = shapely.union_all([P[c] for c in P if c >> 16 in vl]).buffer(VANILLA_GAP)   # as w8 (not the union of Gv: 1 vertex moves)
    hit = [k for k in keys if k in feats and feats[k].intersects(G)]
    if not hit:
        return None, None
    weld = {k: vs for k, vs in (weld or {}).items() if k in keys and k in feats}
    assert all(v in [nm[i] for i in vl] for vs in weld.values() for v in vs), ('weld to a region off the filler', weld)
    items = e.root.find('region_data').find('regions').items
    Vp, Gm = {}, {}                                     # welded: the main pass group's areas, the strip round the rest
    for i in {vi for vs in weld.values() for vi in vl if nm[vi] in vs}:
        fl = [rm.area_fields(ar) for ar in rm.sub(items[i], 'areas').items]
        main = max((P[i << 16 | a].area, f['pass_group']) for a, f in enumerate(fl) if f['passable'])[1]
        Vp[nm[i]] = shapely.union_all([P[i << 16 | a] for a, f in enumerate(fl) if f['passable'] and f['pass_group'] == main])
        rest = [P[i << 16 | a] for a, f in enumerate(fl) if f['passable'] and f['pass_group'] != main]   # eur_moscow_guberniya 1:
        Gm[i] = shapely.union_all(rest).buffer(VANILLA_GAP) if rest else Polygon()          # a 0.2 u sliver, pass group 2
    polys = lambda g: shapely.union_all([q for q in shapely.get_parts(shapely.make_valid(g)) if q.geom_type == 'Polygon'])
    for k in [k for k in feats if feats[k].intersects(G)]:
        if k in weld:
            Gk = shapely.union_all([Gv[i] for i in vl if nm[i] not in weld[k]] + [Gm[i] for i in Gm if nm[i] in weld[k]])
            feats[WELD_STRIP + k] = polys(feats[k].intersection(G).difference(Gk))
        feats[k] = polys(feats[k].difference(G))
    feats['_vanilla_gap'] = G
    out = dict(regions=hit, vanilla=[nm[i] for i in vl if any(shapely.distance(P[c], feats[k]) < 2 * VANILLA_GAP
                                                                for c in P if c >> 16 == i for k in hit)])
    if weld:
        out['welded'] = weld
    return out, dict(G=G, vanilla={nm[i]: V[i] for i in vl}, vanilla_pass=Vp, index={nm[i]: i for i in vl}) if weld else None


def lonlat_geom(g):
    return shapely.transform(shapely.segmentize(g, 0.05), lambda c: np.column_stack(proj.to_world(c[:, 0], c[:, 1])))


def corridor_masks(feats):
    """{mask key: (M, C, routes)} of routes.json, world polygons: M = the mask boxes minus the except_keys regions'
    features, C = every route of the mask buffered by width_deg / 2 (in degrees, then projected)."""
    J = _memo('routes', lambda: json.load(open(ROUTES)))
    out = {}
    for mk, m in J['masks'].items():
        B = _memo(('B', mk), lambda: shapely.union_all([lonlat_geom(box(*b)) for b in m['boxes']]))
        ex = [feats[k] for k in m['except_keys'] if k in feats]
        rs = [r for r in J['routes'] if r['mask'] == mk]
        C = _memo(('C', mk), lambda: shapely.union_all([lonlat_geom(shapely.LineString(r['path']).buffer(r['width_deg'] / 2))
                                                        for r in rs]))
        out[mk] = (B.difference(shapely.union_all(ex)) if ex else B, C, rs)
    return out


def split_holes(ps):
    """Polygons without holes: one with a hole is cut by a vertical line through the hole (both halves kept)."""
    out, todo = [], list(ps)
    while todo:
        p = todo.pop()
        if not p.interiors:
            out.append(p)
            continue
        x = Polygon(p.interiors[0]).representative_point().x
        y0, y1 = p.bounds[1] - 1, p.bounds[3] + 1
        todo += [q for q in shapely.get_parts(shapely.ops.split(p, shapely.LineString([(x, y0), (x, y1)])))
                 if q.geom_type == 'Polygon' and q.area > 0]
    return out


def corridors(feats, sp_):
    """Corridor masks (routes.json): a region's land inside a mask is impassable except within its routes' corridors
    and SETTLE_R round its capital (when that lies in the mask).  -> (sub {label: (key, passable)}, {label: polygon},
    stats); feats[k] becomes its main passable piece (the one at / nearest the capital), the other pieces are labels
    'k|pN' (passable) / 'k|iN' (impassable), all without holes (split_holes)."""
    sub, lab, st = {}, {}, {}
    for mk, (M, C, rs) in corridor_masks(feats).items():
        shapely.prepare(M)
        for s in sp_:
            k, F = s['key'], feats.get(s['key'])
            if F is None or not F.intersects(M):
                continue
            cap = Point(s['cap_xy'])
            keep = shapely.union_all([C, cap.buffer(SETTLE_R)]) if M.contains(cap) else C
            poly = lambda g: [q for q in shapely.get_parts(shapely.make_valid(g)) if q.geom_type == 'Polygon' and q.area > 0]
            imp = [q for q in poly(F.intersection(M).difference(keep)) if q.area >= CORRIDOR_MIN]
            if not imp:
                continue
            assert k not in st, (k, 'in two corridor masks')
            pas = split_holes(poly(F.difference(shapely.union_all(imp))))
            imp = split_holes(imp)
            main = min(pas, key=lambda q: (not q.covers(cap), q.distance(cap), -q.area))
            pas = [q for q in pas if q is main or q.area >= CORRIDOR_MIN]     # overlay slivers on region borders go
            feats[k] = main
            for n, q in enumerate(q for q in pas if q is not main):
                sub[f'{k}|p{n}'], lab[f'{k}|p{n}'] = (k, True), q
            for n, q in enumerate(imp):
                sub[f'{k}|i{n}'], lab[f'{k}|i{n}'] = (k, False), q
            st[k] = dict(mask=mk, land_u2=round(F.area, 1), passable_u2=round(sum(q.area for q in pas), 1),
                         impassable_u2=round(sum(q.area for q in imp), 1), passable_pieces=len(pas), impassable_pieces=len(imp),
                         capital_in_mask=M.contains(cap))
    return sub, lab, st


def lake_polys():
    """[(names, world polygon)] of the natural lakes >= LAKE_MIN u^2 (NE 10m lakes the display draws as water:
    worldgeo.natural_lake; touching features merged: Huron + Michigan, Great Slave + McLeod Bay), simplified."""
    def load():
        import shapefile, worldgeo
        name = 'ne_10m_lakes'
        z = zipfile.ZipFile(os.path.join(worldgeo.GEODATA, name + '.zip'))
        r = shapefile.Reader(shp=io.BytesIO(z.read(name + '.shp')), dbf=io.BytesIO(z.read(name + '.dbf')))
        fl = [x[0] for x in r.fields[1:]]
        gs = []
        for sr in r.iterShapeRecords():
            d = dict(zip(fl, sr.record))
            g = shapely.make_valid(shape(sr.shape.__geo_interface__))
            if worldgeo.natural_lake(d) and g.area >= 0.02:                   # deg^2: ~2 u^2
                gs.append((d['name'], worldgeo._lonlat_to_world(g)))
        out = []
        for q in shapely.get_parts(shapely.union_all([g for _, g in gs])):
            if q.geom_type == 'Polygon' and q.area >= LAKE_MIN:
                nm = [n for a, n in sorted(((g.intersection(q).area, n) for n, g in gs if g.intersects(q)), reverse=True) if n]
                out.append(('+'.join(nm[:3]) or '(unnamed)', shapely.make_valid(shapely.simplify(Polygon(q.exterior), LAKE_SIMPLIFY))))
        return out
    return _memo('lakes', load)


def vcut(ps, xs):
    """Polygons ps cut by the vertical lines x in xs (each across the whole polygon, as split_holes)."""
    for x in xs:
        out = []
        for p in ps:
            if p.bounds[0] < x < p.bounds[2]:
                line = shapely.LineString([(x, p.bounds[1] - 1), (x, p.bounds[3] + 1)])
                out += [q for q in shapely.get_parts(shapely.ops.split(p, line)) if q.geom_type == 'Polygon' and q.area > 0]
            else:
                out.append(p)
        ps = out
    return ps


def lake_cut(feats, sp_, sub):
    """Natural lakes (lake_polys) out of the regions' passable pieces (feats[k] and corridors' 'k|pN'), sub extended in
    place: lake pieces >= CORRIDOR_MIN are impassable labels 'k|lN', the passable rest feats[k] (the piece at / nearest
    the capital) and labels 'k|qN', all without holes and cut by a vertical line through every lake (a lake on the
    region's edge would else end up enclosed once partition gives the edge's unclaimed faces to the region: Champlain);
    carve takes '|l' / '|q' labels in every filler area of the region.
    -> ({label: polygon}, {key: stats})."""
    L = shapely.union_all([q for _, q in lake_polys()])
    shapely.prepare(L)
    names = lake_polys()
    lab, st = {}, {}
    poly = lambda g: [q for q in shapely.get_parts(shapely.make_valid(g)) if q.geom_type == 'Polygon' and q.area > 0]
    for s in sp_:
        k, cap = s['key'], Point(s['cap_xy'])
        if k not in feats:
            continue
        ps = [(None, feats[k])] + [(l, feats[l]) for l, (k2, pas) in sub.items() if k2 == k and pas and l in feats]
        cut, keep, imp = [], [], []
        for l, q in ps:
            I = [x for x in poly(q.intersection(L)) if x.area >= CORRIDOR_MIN] if q.intersects(L) else []
            if I:
                cut.append(l); imp += I
                keep += split_holes(vcut(poly(q.difference(shapely.union_all(I))), [x.representative_point().x for x in I]))
        if not imp:
            continue
        for l in cut:
            if l is not None:
                del sub[l]
                feats.pop(l)
        imp = split_holes(imp)
        if None in cut:
            main = min(keep, key=lambda q: (not q.covers(cap), q.distance(cap), -q.area))
            feats[k] = main
        else:
            main = None
        keep = [q for q in keep if q is not main and q.area >= CORRIDOR_MIN]
        for n, q in enumerate(keep):
            sub[f'{k}|q{n}'], lab[f'{k}|q{n}'] = (k, True), q
        for n, q in enumerate(imp):
            sub[f'{k}|l{n}'], lab[f'{k}|l{n}'] = (k, False), q
        U = shapely.union_all(imp)
        st[k] = dict(lakes=sorted({nm for nm, q in names if q.intersects(U) and q.intersection(U).area >= CORRIDOR_MIN}),
                     lake_u2=round(U.area, 1), lake_pieces=len(imp), passable_pieces=len(keep) + (main is not None))
    return lab, st


def stress_pool(e, n0):
    """Dummy region specs (G4b), most northern first: STRESS_SIDE u squares in bars of STRESS_BAR (neighbours share an
    edge: land boundaries, composite pathfinding domains), bars STRESS_GAP apart, all inside STRESS_FILLER's largest
    theatre filler area and outside VANILLA_BOX.  n0 = spec index of the first (rgb, loc suffix)."""
    rd = e.root.find('region_data')
    names = [it[0].value for it in rd.find('regions').items]
    fi = names.index(STRESS_FILLER)
    tb = box(*proj.THEATRE_MIN, *proj.THEATRE_MAX)
    ai, A = max(((c & 0xFFFF, q) for c, q in rm.area_polygons(rd).items() if c >> 16 == fi and q.within(tb)),
                key=lambda t: t[1].area)
    Am = A.buffer(-STRESS_MARGIN)
    shapely.prepare(Am)
    x0, y0, x1, y1 = Am.bounds
    bw, bh = STRESS_BAR * STRESS_SIDE + STRESS_GAP, STRESS_SIDE + STRESS_GAP
    out, nbar = [], 0
    for y in np.arange(math.floor(y1 / bh) * bh, y0 - bh, -bh):
        for x in np.arange(math.floor(x0 / bw) * bw, x1, bw):
            bx, by_ = float(x) + STRESS_OFF, float(y) + STRESS_OFF
            bar = box(bx, by_, bx + STRESS_BAR * STRESS_SIDE, by_ + STRESS_SIDE)
            if not Am.contains(bar) or bar.intersects(VANILLA_BOX):
                continue
            nbar += 1
            for j in range(STRESS_BAR):
                n = len(out) + 1
                q = box(bx + j * STRESS_SIDE, by_, bx + (j + 1) * STRESS_SIDE, by_ + STRESS_SIDE)
                c = q.centroid
                out.append(dict(key=f'stress_{n:03d}', name=f'Stress {n}', members=[f'stress_{n:03d}'], owner=STRESS_OWNER,
                                data_owner=STRESS_OWNER, town=f'stress_{n:03d}', town_name=f'Stress Town {n}',
                                cap=tuple(round(float(v), 3) for v in proj.to_lonlat(c.x, c.y)), cap_xy=(c.x, c.y),
                                rebel=f'Stress {n} Rebels', poly=q, area=ai, bar=nbar, rgb=rgb_of(n0 + n - 1), loc_suffix=LOC0 + n0 + n - 1))
    return out


def stress_pass_groups(e, dum, i2):
    """pass_group = connected passable land (regions_world id partitions): the dummies of one filler area got one, but
    every bar is its own island in the filler -> one pass group per bar (the first keeps carve's)."""
    rd = e.root.find('region_data')
    items = rd.find('regions').items
    nxt = max(rm.area_fields(a)['pass_group'] for _, _, _, a in rm.iter_areas(rd)) + 1
    (pg0,) = set(i2['pass_groups'].values())
    pg = {}
    for n, d in enumerate(dum):
        if d['bar'] not in pg:
            pg[d['bar']] = pg0 if not pg else nxt + len(pg) - 1
        for ar in rm.sub(items[i2['first_index'] + n], 'areas').items:
            ar[5] = Val(0x07, pg[d['bar']])
    i2['pass_groups'] = {f'bar {b}': v for b, v in pg.items()}


def carve(e, sp_, feats, take, sub=None, weld=False):
    """Cut every region's pieces out of the filler areas take names ((filler region, area); used-up areas are removed,
    areas processed by descending index so the rest keep theirs) -> info.  Region items cloned from TPL, appended in
    spec order.  sub (corridors): {label: (region key, passable)} extra pieces of a region inside its main filler area
    (their own areas: passable ones with the area's pass group, impassable ones a fresh singleton pass group each), then
    pass groups / nonwalk groups re-derived from the topology (fix_groups).  A split_ring split (split_pieces) cuts its
    vanilla region's areas: the new pieces keep the area's flags and pass group (the land stays one walkable mass)."""
    rd = e.root.find('region_data')
    items = rd.find('regions').items
    names = [it[0].value for it in items]
    w0 = names.index('eur_map_west')
    disp = lambda a: a[1] if a[0] == w0 else f'{names[a[0]]}:{a[1]}'      # build_info: west areas as plain ints
    sub = sub or {}
    splitk = {s['key'] for s in sp_ if 'split_of' in s}
    rsplit = {s['key'] for s in sp_ if s.get('split_ring') and s['key'] in take}
    by_area = collections.defaultdict(list)
    for k, ais in take.items():
        for a in ais:
            by_area[a].append(k)
    for lab, (k, _) in sub.items():
        for a in take[k] if lab.split('|')[1][0] in 'lq' else take[k][:1]:   # lake_cut pieces: any of the region's areas
            by_area[a].append(lab)
    allpg = [rm.area_fields(a)['pass_group'] for _, _, _, a in rm.iter_areas(rd)]
    pg_next = max(allpg) + 1
    made = collections.defaultdict(dict)                  # key -> {filler area: area record}
    kept_fill = []                                        # (filler region, area record) of partition's ('filler', n)
    stats = collections.Counter()
    removed, pgs = [], {}
    for fa in sorted(by_area, reverse=True):
        wi, ai = fa
        keys = by_area[fa]
        A = rm.area_polygon(rd, wi, ai)
        w_areas = rm.sub(items[wi], 'areas').items
        ar0 = w_areas[ai]
        keep_fields = bool(set(keys) & rsplit)                # a split_ring's vanilla area
        assert not keep_fields or set(keys) <= rsplit, ('a split_ring area shared with other pieces', keys)
        assert keep_fields or not rm.area_fields(ar0)['passable']
        V = rm.verts(rd)
        pool = dict(zip(map(tuple, V.astype(np.float64).tolist()), range(len(V))))   # = {(float(x), float(y)): i ...}, last wins
        old_rings = [r.tolist() for _, r, _ in rm.rings(ar0)]
        fill = names[wi] in ('eur_map_west', STRESS_FILLER)    # else a split's vanilla area: its own features only
        parts = partition(A, {k: v for k, v in feats.items() if k not in splitk} if fill else {k: feats[k] for k in keys}, keys,
                          holes=keys if keep_fields else ())
        for k in keys:
            if k not in parts:
                if k in take and fa == take[k][0]:
                    raise Retry(k, f'its piece of filler area {disp(fa)} vanished in the partition')
                stats['pieces lost in partition' if k in take else 'corridor pieces lost in partition'] += 1
        newV = []

        def idx(pt):
            i = pool.get(pt)
            if i is None:
                q = (round(pt[0] / GRID) * GRID, round(pt[1] / GRID) * GRID)
                i = pool.get(q)
                if i is None:
                    i = pool[q] = len(V) + len(newV); newV.append(q)
            return i

        def dedup(r):
            r = [idx(q) for q in r]
            return [v for n, v in enumerate(r) if v != r[n - 1]]
        rings = collapse({k: [(lpb.signed_area(r) > 0, dedup(r)) for r in rs] for k, rs in parts.items()}, V, newV)
        for k, rs in rings.items():
            for o, r in rs:
                q = Polygon([tuple(V[i]) if i < len(V) else newV[i - len(V)] for i in r])
                assert q.is_valid, (k, ai, shapely.is_valid_reason(q))
        used = {i for rs in rings.values() for _, r in rs for i in r}
        lost = [tuple(map(float, V[i])) for r in old_rings for i in r if i not in used]
        assert not lost, ('filler vertex lost', disp(fa), keys, lost[:4])
        E = {(a, b) for rs in rings.values() for _, r in rs for a, b in zip(r, r[1:] + r[:1])}
        bnd = {a: b for a, b in E if (b, a) not in E}
        split = {}
        for r in old_rings:
            for a, b in zip(r, r[1:] + r[:1]):
                if bnd.get(a) == b:
                    continue
                chain, v = [], bnd[a]
                while v != b:
                    chain.append(v); v = bnd[v]
                    assert len(chain) < 5000
                split[(a, b)] = chain
        own = rm.edge_owner(rd)
        # a neighbour filler area already carved whole into a region (w8: asi_olonets' area 7) is in made, not in rd
        mown = {e_: ar for d in made.values() for ar in d.values() for _, rr, _ in rm.rings(ar)
                for e_ in zip(rr.tolist(), np.roll(rr, -1).tolist())}
        nsplit = 0
        for (a, b), chain in split.items():
            c = own.get((b, a))
            tar = mown[(b, a)] if c is None else rm.sub(items[c >> 16], 'areas').items[c & 0xFFFF]
            for _, rr, ol in rm.rings(tar):
                r = rr.tolist()
                for n in range(len(r)):
                    if r[n] == b and r[(n + 1) % len(r)] == a:
                        r[n + 1:n + 1] = chain[::-1]
                        ol[3] = rm.mkarr(0x48, np.array(r, np.uint32)); nsplit += 1
                        break
        assert nsplit == len(split)
        if newV:
            rd.find('vertices').children[0] = rm.mkarr(0x4c, np.vstack([V, np.array(newV, np.float32).reshape(-1, 2)]))
        V2 = rm.verts(rd)
        tmpl_outline = rm.sub(ar0, 'outlines').items[0]
        if keep_fields:
            pgs[fa] = rm.area_fields(ar0)['pass_group']
            assert not [x for x in rings if isinstance(x, tuple)], ('split_ring leaves its region area in pieces', disp(fa), keys)
        else:
            pgs[fa] = pg_next; pg_next += 1
        for k in keys:
            if k not in rings:
                continue
            ar = clone(ar0)
            if keep_fields:                              # an impassable piece next to its old area's: own pass group
                if not rm.area_fields(ar0)['passable'] and None in rings:   # (Macedonia's share of a Greek mountain)
                    ar[5] = Val(0x07, pg_next); pg_next += 1
            elif k in take or sub[k][1]:
                ar[2], ar[5], ar[8] = Val(0x01, True), Val(0x07, pgs[fa]), Val(0x07, 0xFFFF)
            else:                                        # impassable corridor-mask piece: filler flags, own pass group
                ar[5] = Val(0x07, pg_next); pg_next += 1; stats['impassable areas'] += 1
            set_rings(ar, rings[k], tmpl_outline)
            rm.sub(ar, 'faces').children[0] = rm.mkarr(0x48, rm.triangulate(V2, [[(o, np.array(r)) for o, r in rings[k]]]).ravel())
            made[k][fa] = ar
        for lab_ in [x for x in rings if isinstance(x, tuple)]:      # kept filler pieces: own filler areas
            ar = clone(ar0)
            ar[5] = Val(0x07, pg_next); pg_next += 1; stats['filler areas kept'] += 1
            set_rings(ar, rings[lab_], tmpl_outline)
            rm.sub(ar, 'faces').children[0] = rm.mkarr(0x48, rm.triangulate(V2, [[(o, np.array(r)) for o, r in rings[lab_]]]).ravel())
            w_areas.append(ar); kept_fill.append((wi, ar))
        blob0 = rm.sub(ar0, 'faces').children[0].value
        if None in rings:
            set_rings(ar0, rings[None], tmpl_outline)
            rm.sub(ar0, 'faces').children[0] = rm.mkarr(0x48, rm.triangulate(V2, [[(o, np.array(r)) for o, r in rings[None]]]).ravel())
        else:
            w_areas.pop(ai); removed.append(fa)
        sibs = [ar for ar in w_areas if ar is not ar0 and rm.sub(ar, 'faces').children[0].value == blob0]
        if sibs:                        # areas sharing ar0's old face blob (w8: eur_map_east 1-9): the blob of the rest
            T = rm.triangulate(V2, [[(o, r) for o, r, _ in rm.rings(ar)] for ar in sibs]).ravel()
            for ar in sibs:
                rm.sub(ar, 'faces').children[0] = rm.mkarr(0x48, T)
            stats['face groups re-triangulated'] += 1
        stats['new vertices'] += len(newV); stats['split sea edges'] += nsplit
    tpl = items[names.index(TPL)]
    first = len(items)
    keys = [s['key'] for s in sp_ if s['key'] in made]
    labs = {k: [k] + [lab for lab, (k2, _) in sub.items() if k2 == k] for k in keys}
    imp = {}
    for k in keys:
        it = clone(tpl)
        it[0] = Val(0x0e, k)
        rm.sub(it, 'areas').items = [made[lab][a] for a in take[k] for lab in labs[k] if a in made[lab]]
        imp[k] = [n for n, ar in enumerate(rm.sub(it, 'areas').items) if not rm.area_fields(ar)['passable']]
        items.append(it)
    stats['orphan vertices dropped'] += drop_unused_vertices(rd)
    rm.rebuild_bounds(rd)
    rd.children[1], rd.children[2] = Val(0x0c, tuple(map(float, proj.BOX_MIN))), Val(0x0c, tuple(map(float, proj.BOX_MAX)))
    rm.rebuild_connectivity(rd)
    P = rm.area_polygons(rd)
    nar = {k: len(rm.sub(items[first + n], 'areas').items) for n, k in enumerate(keys)}
    out = dict(keys=keys, first_index=first, filler_areas={k: [disp(a) for a in take[k] if a in made[k]] for k in keys},
               filler_removed=[disp(a) for a in sorted(removed)], pass_groups={str(disp(a)): p for a, p in pgs.items()}, stats=dict(stats),
               polys={k: shapely.union_all([P[(first + n) << 16 | a] for a in range(nar[k])]) for n, k in enumerate(keys)})
    kept = [wi << 16 | next(n for n, a in enumerate(rm.sub(items[wi], 'areas').items) if a is ar) for wi, ar in kept_fill]
    out['filler_kept'] = [disp((c >> 16, c & 0xFFFF)) for c in kept]
    out['region_names'] = [it[0].value for it in items]   # pathfinding: composite names with any vanilla member
    if rsplit:                                            # split_ring: the vanilla region left (pathfinding re-tags its land)
        out['split'], out['split_polys'] = {}, {}
        for k in [k for k in keys if k in rsplit]:
            ri = take[k][0][0]
            assert rm.sub(items[ri], 'areas').items, ('split_ring takes all of its region', k)
            out['split'][k] = dict(of=names[ri], index=ri)
            out['split_polys'][k] = shapely.union_all([q for c, q in P.items() if c >> 16 == ri])
    if sub or kept:
        strip = shapely.union_all([f for k, f in feats.items() if k.startswith(WELD_STRIP)]) if weld else None
        out['groups_fixed'] = fix_groups(rd, [(first + n) << 16 | a for n, k in enumerate(keys) for a in range(nar[k])
                                              if k not in rsplit] + kept, strip)
        out['impassable'] = {k: v for k, v in imp.items() if v}
        out['pass_groups'] = {f'{k}:{a}': rm.area_fields(rm.sub(items[first + n], 'areas').items[a])['pass_group']
                              for n, k in enumerate(keys) for a in range(nar[k]) if a not in imp[k]}
        out['pass_polys'] = {k: shapely.union_all([P[(first + n) << 16 | a] for a in range(nar[k]) if a not in imp[k]])
                             for n, k in enumerate(keys)}
    assert not weld or out.get('groups_fixed', {}).get('joined_vanilla_pass_groups'), 'weld: no pass group joined to vanilla'
    return out


def drop_unused_vertices(rd):
    """Vertices no ring or face uses any more go, the rest renumbered (a vanilla face blob may use vertices off its
    rings: eur_sweden 5's 3, orphaned when Gotland takes the area) -> how many.  None unused: nothing changes."""
    V = rm.verts(rd)
    ars = [ar for _, _, _, ar in rm.iter_areas(rd)]
    used = np.zeros(len(V), bool)
    for ar in ars:
        used[np.frombuffer(rm.sub(ar, 'faces').children[0].value, '<u4')] = True
        for _, r, _ in rm.rings(ar):
            used[r] = True
    if used.all():
        return 0
    mp = np.cumsum(used) - 1
    for ar in ars:
        f = rm.sub(ar, 'faces')
        f.children[0] = rm.mkarr(0x48, mp[np.frombuffer(f.children[0].value, '<u4')])
        for _, r, ol in rm.rings(ar):
            ol[3] = rm.mkarr(0x48, mp[r])
    rd.find('vertices').children[0] = rm.mkarr(0x4c, V[used])
    return int((~used).sum())


def fix_groups(rd, codes, weld=None):
    """pass_group / nonwalk_group of the new areas `codes` = the topology (regions_world id partitions): passable land
    components (a filler area's pieces may fall apart round impassable corridor-mask land) keep the most common pass
    group of their areas unless an earlier component took it (then a fresh one); an impassable new area takes the
    nonwalk group of the old non-walkable areas (sea, filler) its component touches, else a fresh one.  weld (stage
    'j'): a component joined to vanilla land takes the vanilla areas' pass group (else that asserts)."""
    items = rd.find('regions').items
    kinds = [it[1].value for it in items]
    G, its, F = rm.derive_area_groups(rd, kinds)
    idx = {ri << 16 | ai: n for n, (ri, ai, _, _) in enumerate(its)}
    mine = set(codes)
    walk = [kinds[ri] == 'land' and f['passable'] for (ri, _, _, _), f in zip(its, F)]
    nxt_pg = max(f['pass_group'] for f in F) + 1
    nxt_nw = max(f['nonwalk_group'] for f in F if f['nonwalk_group'] != 0xFFFF) + 1
    comp = collections.defaultdict(list)
    for c in codes:
        if walk[idx[c]]:
            comp[G['pass_group'][idx[c]]].append(c)
    old = {G['pass_group'][n] for n, (ri, ai, _, _) in enumerate(its) if walk[n] and ri << 16 | ai not in mine}
    names = [it[0].value for it in items]
    bad = {g_: sorted({names[ri] for n, (ri, ai, _, _) in enumerate(its) if walk[n] and G['pass_group'][n] == g_})
           for g_ in old & set(comp)}
    assert weld is not None or not bad, ('new land joins an old pass group component (vanilla land neighbour)', bad)
    taken, moved, joined = set(), 0, {}
    for g_, cc in sorted(comp.items(), key=lambda kv: kv[0] not in old):    # the vanilla-joined ones first
        if g_ in old:
            pgs = collections.Counter(F[n]['pass_group'] for n, (ri, ai, _, _) in enumerate(its)
                                      if walk[n] and G['pass_group'][n] == g_ and ri << 16 | ai not in mine)
            assert len(pgs) == 1, ('vanilla component with several pass groups', pgs)
            pg = next(iter(pgs))
            joined[pg] = bad[g_]
        else:
            pg = collections.Counter(F[idx[c]]['pass_group'] for c in cc).most_common(1)[0][0]
            if pg in taken:
                pg, nxt_pg = nxt_pg, nxt_pg + 1
        taken.add(pg)
        for c in cc:
            if F[idx[c]]['pass_group'] != pg:
                its[idx[c]][3][5] = Val(0x07, pg); moved += 1
    have = collections.defaultdict(set)
    for n, (ri, ai, _, _) in enumerate(its):
        if not walk[n] and ri << 16 | ai not in mine:
            have[G['nonwalk_group'][n]].add(F[n]['nonwalk_group'])
    fresh = {}
    for c in codes:
        n = idx[c]
        if walk[n]:
            continue
        h = have[G['nonwalk_group'][n]]
        assert len(h) <= 1, ('impassable land joins two nonwalk groups', h)
        if not h:
            if G['nonwalk_group'][n] not in fresh:
                fresh[G['nonwalk_group'][n]], nxt_nw = nxt_nw, nxt_nw + 1
            h = {fresh[G['nonwalk_group'][n]]}
        its[n][3][8] = Val(0x07, next(iter(h)))
    out = dict(pass_components=len(comp), areas_moved_to_another_pass_group=moved, fresh_nonwalk_groups=len(fresh))
    if joined:
        out['joined_vanilla_pass_groups'] = {pg: len(v) for pg, v in joined.items()}
    if weld is not None:      # the filler strip the weld (geometry: the welded strips) removed held non-walkable components together (eur_moscow_guberniya 6 / 7,
        cur = [rm.area_fields(it[3])['nonwalk_group'] for it in its]          # strip pieces): one stored id per component,
        by = collections.defaultdict(lambda: collections.defaultdict(list))   # the largest keeps the old one
        for n in range(len(its)):
            if not walk[n]:
                by[cur[n]][G['nonwalk_group'][n]].append(n)
        split = []
        for s_, cs_ in by.items():
            for t in sorted(cs_, key=lambda t: (-len(cs_[t]), t))[1:]:
                for n in cs_[t]:
                    its[n][3][8] = Val(0x07, nxt_nw)
                    split.append(its[n][0] << 16 | its[n][1])
                nxt_nw += 1
        P = rm.area_polygons(rd)
        far = [c for c in split if P[c].distance(weld) > 4 * WELD_ZONE]   # all:208 (a Moscow sliver) is 4 u off
        assert not far, ('weld: non-walk groups split away from the weld strips', [(f'{names[c >> 16]}:{c & 0xFFFF}', round(P[c].distance(weld), 2), P[c].bounds, round(P[c].area, 2)) for c in far])
        split = [f'{names[c >> 16]}:{c & 0xFFFF}' for c in split]
        out['nonwalk_groups_split'] = split
    return out


EPS = 0.05                        # u: repair radius round an invalid ring point (noding of near-parallel lines)


def collapse(rings, V, newV):
    """Repair rings made invalid by rounding new vertices to GRID: while a ring is invalid, the new vertices within EPS
    of the reported point merge into one (an old vertex nearby is kept instead), repeats and spikes are dropped; then
    the new vertices are renumbered densely (newV edited in place).  All rings of the area use the same map, so shared
    edges stay twinned; valid rings are not touched."""
    import shapely.validation  # noqa: F401
    n0 = len(V)
    xy = lambda i: tuple(map(float, V[i])) if i < n0 else newV[i - n0]
    root = {}

    def find(i):
        while root.get(i, i) != i:
            i = root[i]
        return i

    def clean(r):
        r = [find(i) for i in r]
        changed = True
        while changed and len(r) >= 3:
            changed = False
            r2 = [v for n, v in enumerate(r) if v != r[n - 1]]
            changed |= len(r2) != len(r)
            r = r2
            for n in range(len(r)):
                j = (n + 1) % len(r)
                if len(r) >= 3 and r[n - 1] == r[j]:          # spike r[n-1] -> r[n] -> r[n-1]
                    for x in sorted({n, j}, reverse=True):
                        del r[x]
                    changed = True
                    break
        return r
    fixes = 0
    while True:
        bad = None
        for k, rs in rings.items():
            for o, r in rs:
                q = Polygon([xy(i) for i in r])
                if not q.is_valid:
                    bad = shapely.validation.explain_validity(q); break
            if bad:
                break
        if bad is None:
            break
        m = re.search(r'\[([-\d.e]+) ([-\d.e]+)\]', bad)
        assert m and fixes < 200, ('cannot repair ring', k, bad)
        pt = (float(m.group(1)), float(m.group(2)))
        near = sorted({i for rs in rings.values() for _, r in rs for i in r if math.dist(xy(i), pt) <= EPS})
        olds = [i for i in near if i < n0]
        tgt = min(olds, key=lambda i: math.dist(xy(i), pt)) if olds else near[0]
        moved = [i for i in near if i >= n0 and i != tgt]
        assert moved, ('nothing to merge at', pt, k, bad)
        for i in moved:
            root[i] = tgt
        rings = {kk: [(o, c) for o, r in rs for c in [clean(r)] if len(c) >= 3] for kk, rs in rings.items()}
        fixes += 1
    keep = sorted({i for rs in rings.values() for _, r in rs for i in r if i >= n0})
    mp = {i: n0 + j for j, i in enumerate(keep)}
    newV[:] = [newV[i - n0] for i in keep]
    collapse.fixes = getattr(collapse, 'fixes', 0) + fixes
    return {k: [(o, [mp.get(i, i) for i in r]) for o, r in rs] for k, rs in rings.items()}


def footprint(tpl):
    it = clone(tpl)
    pos = rm.sub(tpl, 'settlement_and_slots').children[0].value
    lpb.place_slots(it, 'x', 'y', pos, (0.0, 0.0))
    return pos, it


def spots(Z, tpos, cap, margin):
    """Integer template offsets D whose settlement tpos + D lies in Z at least `margin` u from its edge, nearest to the
    capital first.  (land_probe_b used multiples of 10 u so the LINE_OF_SIGHT bit arrays move whole 10 u blocks; here
    the LOS moves by D rounded to 10 u, see startpos_regions, so narrow islands fit.)"""
    Zm = Z.buffer(-margin)
    if Zm.is_empty:
        return []
    x0, y0, x1, y1 = Zm.bounds
    dx, dy = np.meshgrid(np.arange(math.floor(x0 - tpos[0]), math.ceil(x1 - tpos[0]) + 1),
                         np.arange(math.floor(y0 - tpos[1]), math.ceil(y1 - tpos[1]) + 1))
    dx, dy = dx.ravel(), dy.ravel()
    ok = shapely.contains_xy(Zm, tpos[0] + dx, tpos[1] + dy)
    dx, dy = dx[ok], dy[ok]
    order = np.argsort(np.hypot(tpos[0] + dx - cap.x, tpos[1] + dy - cap.y), kind='stable')
    return [(float(dx[i]), float(dy[i])) for i in order]


def precheck(e, info, sp_):
    """A region whose polygon, shrunk by the pathfinding margins, holds no settlement spot -> Retry."""
    items = e.root.find('region_data').find('regions').items
    names = [it[0].value for it in items]
    tpos, it0 = footprint(items[names.index(TPL)])
    fp = shapely.union_all(lpb.slot_geometry(it0))
    by = {s['key']: s for s in sp_}
    for k in info['keys']:
        Rp = info.get('pass_polys', info['polys'])[k]
        shapely.prepare(Rp)
        ok = any(Rp.contains(shapely.affinity.translate(fp, dx, dy))
                 for dx, dy in spots(Rp, tpos, Point(by[k]['cap_xy']), LAND_BAND + SETTLE_MARGIN_AT.get(k, SETTLE_MARGIN)))
        if not ok:
            raise Retry(k, f'no settlement spot (land {Rp.area:.0f} u^2)')


def place_settlements(e, sp_, info, single):
    """land_probe_b.place_settlements for any region set, any integer offset, patched display box: the spot nearest
    the capital on the region's singleton land with >= SETTLE_MARGIN, footprint + slots inside the region polygon."""
    items = e.root.find('region_data').find('regions').items
    names = [it[0].value for it in items]
    tpl = items[names.index(TPL)]
    tpos = rm.sub(tpl, 'settlement_and_slots').children[0].value
    out = {}
    for s in sp_:
        k = s['key']
        if k not in info['keys']:
            continue
        Z, Rp, cap = single[k], info.get('pass_polys', info['polys'])[k], Point(s['cap_xy'])
        shapely.prepare(Rp)
        best = None
        for dx, dy in spots(Z, tpos, cap, SETTLE_MARGIN_AT.get(k, SETTLE_MARGIN)):
            p = Point(tpos[0] + dx, tpos[1] + dy)
            it = clone(tpl)
            lpb.place_slots(it, k, s['town'], (lp.f32(p.x), lp.f32(p.y)), (dx, dy))
            sg = lpb.slot_geometry(it)
            if all(Rp.contains(q) for q in sg) and lpb.in_display_box(sg, PATCHED_HALF):
                best = (p.distance(cap), (dx, dy))
                break
        if not best:
            raise Retry(k, 'no settlement spot on its pathfinding land')
        D = best[1]
        out[k] = dict(D=D, pos=(lp.f32(tpos[0] + D[0]), lp.f32(tpos[1] + D[1])), capital_distance_u=round(best[0], 1))
    return out


def regions_finish(e, sp_, info, place):
    rd = e.root.find('region_data')
    items = rd.find('regions').items
    th = e.root.find('theatres_and_region_keys').items[0][0].find('region_keys')
    by = {s['key']: s for s in sp_}
    for n, k in enumerate(info['keys']):
        it = items[info['first_index'] + n]
        assert it[0].value == k
        lpb.place_slots(it, k, by[k]['town'], place[k]['pos'], place[k]['D'])
        th.items.append([Val(0x0e, k), Val(0x0c, place[k]['pos'])])
    e.root.children[e.root.children.index(e.root.find('query_info'))] = rm.build_query_info(rd, True)


# ---------------------------------------------------------------- pathfinding.esf
def renumber_many(g, region_indices):
    """land_probe.renumber_domains for several regions in one pass: singleton domains n..n+m-1 before the sea."""
    n, m = len(g.region_indices), len(region_indices)
    assert g.passable_region_count == g.listed_region_count == n and g.path_table.index(0) == n
    g.region_indices = g.region_indices + tuple(region_indices)
    g.path_table = g.path_table[:n] + tuple(n + 1 + k for k in range(m)) + g.path_table[n:]
    g.passable_region_count = g.listed_region_count = n + m
    up = lambda t: t if t.path_id < n or t.path_id == 1023 else pm.Trait(t.kind, t.middle20, t.contact_mask, t.path_id + m)
    for c in g.cells:
        if c.uniform is not None:
            c.uniform = up(c.uniform)
        for b in c.boundaries:
            b.trait = up(b.trait)
    lp._SEA.clear(); probe_g3._SEA.clear()
    return list(range(n, n + m))


def snap_poly(p):
    q = Polygon(lp.snap_ring(list(p.exterior.coords)), [lp.snap_ring(list(h.coords)) for h in p.interiors])
    assert q.is_valid, 'snapped polygon invalid'
    return q


def band_polygon(poly_w):
    b = shapely.simplify(shapely.transform(poly_w, lambda c: c * FIX).buffer(BAND * FIX), BAND_SIMPLIFY * FIX)
    out = shapely.union_all([snap_poly(p) for p in shapely.get_parts(b)])
    assert out.is_valid
    return out


def cell_boxes(g, ks):
    ks = np.asarray(ks)
    x = g.origin_fixed[0] + ks % g.columns * S
    y = g.origin_fixed[1] + ks // g.columns * S
    return shapely.box(x, y, x + S, y + S)


def hole_cuts(g, k, holes, kept):
    """Two parallel rays per hole from its middle to a cell side, the first direction whose rays miss every kept
    (vanilla, non-off-map) polygon of the cell: they split the ring round the hole, and since they end on the cell
    side (exact on the 1-unit grid) and cross only new faces' edges, the noding never moves an edge a kept polygon
    shares (a full-height cut did: 1 cell, sea/off-map overlap)."""
    (cx0, cy0), (cx1, cy1) = g.corners(k)[0], g.corners(k)[3]
    K = shapely.union_all(kept) if kept else Polygon()
    out = []
    for h in holes:
        H = Polygon(h)
        x0, y0, x1, y1 = H.bounds
        xa, xb = (int(round(x0 + (x1 - x0) * f)) for f in (1 / 3, 2 / 3))
        ya, yb = (int(round(y0 + (y1 - y0) * f)) for f in (1 / 3, 2 / 3))
        xm, ym = int(round((x0 + x1) / 2)), int(round((y0 + y1) / 2))

        def ray(p, end, chord):
            """p -> end if it crosses the hole, else from the middle of chord's first piece through the hole (a
            skewed hole: a ray that misses it is a dangle and one ray alone never splits the ring: w2 cell 585086);
            None if the chord misses the hole too."""
            if shapely.intersection(shapely.LineString((p, end)), H).length > 0:
                return p, end
            c = shapely.intersection(shapely.LineString(chord), H)
            q = next((q for q in shapely.get_parts(c) if q.geom_type == 'LineString' and q.length > 2), None)
            return None if q is None else (tuple(int(round(v)) for v in q.interpolate(0.5, normalized=True).coords[0]), end)
        V = lambda x, cy: ray((x, ym), (x, cy), ((x, y0 - 1), (x, y1 + 1)))
        Hz = lambda y, cx: ray((xm, y), (cx, y), ((x0 - 1, y), (x1 + 1, y)))
        for rays in ([V(x, cy0) for x in (xa, xb)], [V(x, cy1) for x in (xa, xb)],
                     [Hz(y, cx0) for y in (ya, yb)], [Hz(y, cx1) for y in (ya, yb)]):
            if None in rays:
                continue
            ls = [shapely.LineString(r) for r in rays]
            if xa != xb and ya != yb and all(K.is_empty or shapely.intersection(q, K).is_empty for q in ls):
                out += ls
                break
        else:
            raise AssertionError(('no cut round a hole misses the kept polygons', k))
    return out


def cells_under(g, geom):
    """Cells whose box meets geom (fixed point)."""
    C, R = g.columns, g.rows
    ox, oy = g.origin_fixed
    x0, y0, x1, y1 = geom.bounds
    c0, c1 = max(0, int((x0 - ox) // S) - 2), min(C - 1, int((x1 - ox) // S) + 2)
    r0, r1 = max(0, int((y0 - oy) // S) - 2), min(R - 1, int((y1 - oy) // S) + 2)
    allk = np.array([r * C + c for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)])
    shapely.prepare(geom)
    return allk[shapely.intersects(geom, cell_boxes(g, allk))].tolist()


def weld_land(area, P, Ls, weld, wgeom, polys, upolys, sea):
    """Stage 'j' land in the weld cells of every WELD pair (cells within WELD_ZONE of both regions) -> (J, {weld cell:
    cell_polys}, stats).  J = the cells' off-map inside the new region's passable areas, or inside the vanilla region's
    main passable areas within WELD_DEPTH of it, less LAND_BAND round every other polygon but the welded vanilla
    regions' land (off-map, sea, river, other domains) and round the cells outside: it meets the vanilla land, never
    anything else, and never leaves the weld cells (so only they change)."""
    g = area.grid
    fx = lambda p: shapely.transform(p, lambda c: c * FIX)
    rx = {r: n for n, r in enumerate(g.region_indices)}
    vix = {v: wgeom['index'][v] for vs in weld.values() for v in vs}
    dmn = g.path_domains()
    landc = lambda t: t.kind not in (2, 3) and t.path_id != sea
    ok = lambda t: landc(t) and t.path_id != 1023 and bool(set(dmn[t.path_id]) & set(vix.values()))
    cp, J0, pairs = {}, [], {}
    lakes = fx(shapely.union_all([q for _, q in lake_polys()]))      # deep welds: the vanilla rim's lakes stay off-map
    for k, vs in weld.items():
        NR, NP = fx(polys[k]), fx(upolys[k])
        for v in vs:
            VR, VP = fx(wgeom['vanilla'][v]), fx(wgeom['vanilla_pass'][v])
            Z = NR.buffer(WELD_ZONE * FIX).intersection(VR.buffer(WELD_ZONE * FIX))
            assert Z.area > 0, ('weld pair far apart', k, v)
            depth = WELD_DEEP.get((k, v), WELD_DEPTH)
            if depth > WELD_DEPTH:
                Z = shapely.union_all([Z, VR.intersection(NR.buffer(depth * FIX))])
            ks = cells_under(g, Z)
            for c in ks:
                if c not in cp:
                    cp[c] = probe_g3.cell_polys(area, P, c)
            off = shapely.union_all([Polygon(q) for c in ks for t, q in cp[c] if t == lp.OFF], grid_size=1.0)
            # passable areas; a deep weld takes the whole vanilla region: Finland's rim north of Ladoga is its impassable
            # area 1 (the off-map wedge), so VP left a 6 u gap and no walk (2026-10-30)
            j0 = off.intersection(shapely.union_all([NP, (VR if depth > WELD_DEPTH else VP).intersection(NR.buffer(depth * FIX))]))
            J0.append(j0.difference(lakes) if depth > WELD_DEPTH else j0)
            pairs[f'{k}|{v}'] = len(ks)
    assert rx and all(r in rx for r in vix.values())
    J0 = shapely.union_all(J0)
    CB = shapely.union_all(cell_boxes(g, list(cp)))
    Lc = Ls.intersection(CB)
    X = shapely.union_all([Polygon(q) for c in cp for t, q in cp[c] if not ok(t)], grid_size=1.0)
    X = shapely.union_all([X.difference(shapely.union_all([J0, Lc])), shapely.box(*CB.buffer(2 * S).bounds).difference(CB)])
    J = shapely.set_precision(J0.difference(X.buffer(LAND_BAND * FIX, quad_segs=2)), 1.0)
    J = shapely.union_all([p for p in shapely.get_parts(J) if p.geom_type == 'Polygon' and p.area >= 0.25 * FIX * FIX])
    assert J.is_valid and J.difference(J0).area < max(1.0, J.length) and X.distance(J) > 0.5 * LAND_BAND * FIX   # rounding slack
    return J, cp, dict(pairs=pairs, cells=len(cp), J0_u2=round(J0.area / FIX / FIX, 1), J_u2=round(J.area / FIX / FIX, 1),
                       J_new_u2=round(J.difference(Lc).area / FIX / FIX, 1))


def pathfinding(path, info):
    """land_probe_b.pathfinding for every landmass of the new regions: land = (off-map ∩ ∪regions) shrunk by LAND_BAND,
    parts >= MIN_LAND kept; a land point's domain = the set of regions whose BAND-grown polygon covers it (singleton,
    or a composite allocated on first use).  Stage 'j' (info['weld']): that land is computed without the welded
    strips (as without 'j'), then weld_land joins it to the vanilla land inside the weld cells only, its domains
    from the new and the welded vanilla regions' bands (a vanilla singleton, or a composite with vanilla members).
    A split_ring split is vanilla land: no new land, split_retag re-tags its region's polygons instead."""
    keys, first, polys = info['keys'], info['first_index'], info['polys']
    rsplit = info.get('split', {})
    upolys = info.get('pass_polys', polys)              # corridor masks: land = the passable areas only
    weld, wgeom = info.get('weld'), info.get('weld_geom')
    m = pm.PathfindingModel.load(path)
    area = m.areas[0]
    g, P = area.grid, area.polygons()
    C, R = g.columns, g.rows
    doms = renumber_many(g, [first + n for n in range(len(keys))])
    sea = lp.sea_id(g)
    fx = lambda p: shapely.transform(p, lambda c: c * FIX)
    polys_j, upolys_j = polys, upolys
    if weld:                                            # the regions as cut without 'j' (the strip snapped as partition's)
        Gs = shapely.set_precision(wgeom['G'], GRID)
        polys = {k: polys[k].difference(Gs) if k in weld else polys[k] for k in keys}
        upolys = {k: upolys[k].difference(Gs) if k in weld else upolys[k] for k in keys}
    U = shapely.union_all([fx(upolys[k]) for k in keys if k not in rsplit])
    cand = cells_under(g, U)
    print(f'  pathfinding: {len(cand)} cells under the new regions', flush=True)
    cp = {k: probe_g3.cell_polys(area, P, k) for k in cand}
    offp = {k: [j for j, (t, q) in enumerate(cp[k]) if t == lp.OFF] for k in cand}
    O = shapely.union_all([Polygon(cp[k][j][1]) for k in cand for j in offp[k]], grid_size=1.0)
    L = O.intersection(U).buffer(-LAND_BAND * FIX)
    parts = [p for p in shapely.get_parts(L) if p.area >= MIN_LAND * FIX * FIX]
    dropped = L.area - sum(p.area for p in parts)
    def simp(p):                    # Douglas-Peucker can cut a corner by more than its tolerance (w8: Fiji, 0.61 u)
        tol = LAND_SIMPLIFY
        while True:
            q = shapely.make_valid(shapely.simplify(p, tol * FIX))
            if tol < 0.01 or q.within(p.buffer(0.4 * LAND_BAND * FIX)):   # keeps > 0.5 LAND_BAND off-map margin
                return q
            tol /= 2
    sm = [q for p in parts for q in shapely.get_parts(simp(p)) if q.geom_type == 'Polygon']
    Ls = shapely.union_all([snap_poly(q) for q in sm if q.area >= MIN_LAND * FIX * FIX])
    assert Ls.is_valid
    for p in shapely.get_parts(Ls):
        for r in [p.exterior] + list(p.interiors):
            cs = [tuple(map(int, c)) for c in r.coords[:-1]]
            assert all(lp.edge_in_cell(a, b) for a, b in zip(cs, cs[1:] + cs[:1]))
    assert Ls.within(O) and O.boundary.distance(Ls) > 0.5 * LAND_BAND * FIX
    print(f'  land {Ls.area / FIX / FIX:.0f} u^2 in {len(shapely.get_parts(Ls))} parts', flush=True)
    B = [Polygon() if k in rsplit else band_polygon(polys[k]) for k in keys]
    btree = shapely.STRtree(B)
    blines = [shapely.intersection(b.boundary, Ls) for b in B]    # inside the land only: never moves an off-map edge
    for b in blines:
        shapely.prepare(b)
    for b in B:
        shapely.prepare(b)
    shapely.prepare(Ls)
    pos1 = {ri: n + 1 for n, ri in enumerate(g.region_indices)}
    base = len(g.path_domains())
    ridx, rname = [first + n for n in range(len(keys))], list(keys)   # band index -> region index, key
    dom_of = {T: d for d, T in enumerate(g.path_domains()) if T}     # region-index tuple -> domain (vanilla's reused)
    dom_of.update({(first + n,): doms[n] for n in range(len(keys))})
    comps = []
    mine = set(doms)
    landc = lambda t: t.kind not in (2, 3) and t.path_id != sea       # middle20's land class
    jset, wstats, vdom = set(), None, {}
    if weld:
        J, jcp, wstats = weld_land(area, P, Ls, weld, wgeom, polys_j, upolys_j, sea)
        vks = sorted({v for vs in weld.values() for v in vs})
        for v in vks:
            vdom[v] = dom_of[(wgeom['index'][v],)] = g.path_domains().index((wgeom['index'][v],))   # path_table permutes a few
        BJ = [band_polygon(polys_j[k]) if k in weld else B[n] for n, k in enumerate(keys)]
        BJ += [band_polygon(wgeom['vanilla'][v]) for v in vks]
        ridx += [wgeom['index'][v] for v in vks]
        rname += vks
        for b in BJ:
            shapely.prepare(b)
        btJ = shapely.STRtree(BJ)
        jset = {k for k, bx in zip(jcp, cell_boxes(g, list(jcp))) if shapely.intersects(J, bx)}   # touching too: may need side vertices
        for k in jset - set(cp):
            cp[k] = jcp[k]
            offp[k] = [j for j, (t, q) in enumerate(cp[k]) if t == lp.OFF]
        near = sorted({(r + dy) * C + col + dx for k in jset for r, col in [divmod(k, C)] for dx in (-1, 0, 1) for dy in (-1, 0, 1)})
        Lw = shapely.union_all([J, Ls.intersection(shapely.union_all(cell_boxes(g, near)))], grid_size=1.0)
        shapely.prepare(Lw)
        wstats['weld cells (land added or touching)'] = len(jset)
        print(f'  weld: {wstats}', flush=True)

    van = set(dom_of)

    def label(q, jc=False):
        BB, bt = (BJ, btJ) if jc else (B, btree)
        T = tuple(sorted(ridx[int(i)] for i in bt.query(q, predicate='intersects') if BB[i].covers(q)))
        assert T, ('land point in no band', q)
        if len(T) == 3 and T not in van:              # a new triple point (~1 u^2): a pair's composite instead, so
            T = next((p for p in itertools.combinations(T, 2) if p in van and T[-1] in p), (T[0], T[-1]))   # keeps the newest region
                                                                                          # (a weld point's land); ~170 of 532 ids free
        return T

    def dom(T):                                       # composite allocated on first use by a kept polygon (a piece
        if T not in dom_of:                           # merged away in a >MAX_LAND_POLYS cell allocates nothing)
            dom_of[T] = base + len(comps); comps.append(T); mine.add(dom_of[T])
        return dom_of[T]

    verts = list(area.vertices_fixed)
    vid = {}
    for n, p in enumerate(verts):
        if n >= 4:
            vid.setdefault(p, n)
    key = key0 = max(P) + 1000
    kept = bytearray(b'\x01' * (C * R))
    stats = collections.Counter()
    vreb = set()                                      # weld cells: vanilla polygons re-keyed with vertices added

    def ids_pts(k, pts):
        corners = g.corners(k)
        out = []
        for q in pts:
            if q in corners:
                out.append(corners.index(q))
            else:
                if q not in vid:
                    vid[q] = len(verts); verts.append(q)
                out.append(vid[q])
        return tuple(out)

    def ids_of(k, p):
        p = shapely.simplify(p, 0)
        pts = [(int(a), int(b)) for a, b in p.exterior.coords[:-1]]
        assert all(float(a) == q[0] and float(b) == q[1] for (a, b), q in zip(p.exterior.coords[:-1], pts))
        if not p.exterior.is_ccw:
            pts.reverse()
        return ids_pts(k, pts)

    def weld_vertices(k, bounds, nv):
        """Weld cell: no T-junction between its polygons (middle20's same-cell bit needs a shared edge; the off-map
        rest must tile with the land exactly): a vertex of one on another's edge (<= 1 unit off a sloped edge: noding
        rounds to the unit grid; exact on an axis-parallel one, so no side moves) is inserted there.  Vanilla polygons
        (bounds[:nv]) only gain vertices (new key).  Asserts the cell's polygons still tile it exactly."""
        nonlocal key
        corners = g.corners(k)
        pt = lambda ids: tuple(corners[i] if i < 4 else verts[i] for i in ids)
        lc = range(len(bounds))
        pts = {n: pt(P[bounds[n].polygon_offset]) for n in lc}
        allv = {q for n in lc for q in pts[n]}
        for n in lc:
            have, out = set(pts[n]), []
            for p, q in zip(pts[n], pts[n][1:] + pts[n][:1]):
                out.append(p)
                dx, dy = q[0] - p[0], q[1] - p[1]
                L2 = dx * dx + dy * dy
                ins = []
                for v in allv - have:
                    t = ((v[0] - p[0]) * dx + (v[1] - p[1]) * dy) / L2
                    cr = abs((v[0] - p[0]) * dy - (v[1] - p[1]) * dx)
                    if 0 < t < 1 and (cr == 0 if dx == 0 or dy == 0 else cr <= math.sqrt(L2)):
                        ins.append((t, v))
                for _, v in sorted(ins):
                    out.append(v); have.add(v)
            if len(out) > len(pts[n]):
                assert Polygon(out).is_valid and Polygon(out).exterior.is_ccw, ('weld vertices break a polygon', k, n)
                P[key] = ids_pts(k, out)
                if n < nv:
                    vreb.add(key); stats['weld: vanilla polygons given vertices'] += 1
                else:
                    stats['weld: new polygons given vertices'] += 1
                bounds[n] = pm.Boundary(bounds[n].trait, key); key += 1
                pts[n] = tuple(out)
        tw = sum(x * qy - y * qx for n in lc for (x, y), (qx, qy) in zip(pts[n], pts[n][1:] + pts[n][:1]))
        assert tw == 2 * g.cell_size_fixed ** 2, ('weld cell does not tile', k, tw - 2 * g.cell_size_fixed ** 2)

    def merged(faces):
        u = shapely.union_all(faces, grid_size=1.0)
        ps = [p for p in shapely.get_parts(u) if p.area > 0]
        if any(p.interiors for p in ps):
            stats['unmerged (hole)'] += 1
            ps = faces
        assert not any(p.interiors for p in ps)
        return sorted(ps, key=lambda p: -p.area)

    work8 = [k for k, hit in zip(cand, shapely.intersects(Ls, cell_boxes(g, cand))) if hit and offp[k]]
    work = work8 + sorted(jset - set(work8))
    boxes = dict(zip(work, cell_boxes(g, work)))
    for n_, k in enumerate(work):
        jc = k in jset
        LL, BB, bt = (Lw, BJ, btJ) if jc else (Ls, B, btree)
        cellbox = boxes[k]
        c = g.cells[k]
        if len(cp[k]) == 1 and offp[k] == [0] and LL.contains(cellbox):
            hits = bt.query(cellbox, predicate='intersects')
            if len(hits) == 1 and BB[hits[0]].contains(cellbox):
                kept[k] = 0
                g.cells[k] = pm.Cell(c.costs8, uniform=pm.Trait(0, 0, 255, dom_of[(ridx[int(hits[0])],)])); stats['uniform land'] += 1
                continue
        if shapely.intersection(cellbox, LL).area == 0 and not jc:
            continue
        kept[k] = 0
        Of = shapely.union_all([Polygon(cp[k][j][1]) for j in offp[k]], grid_size=1.0)
        lines = [cellbox.boundary, shapely.intersection(LL.boundary, cellbox)]
        if jc:
            lines += [shapely.intersection(shapely.intersection(BJ[i].boundary, cellbox), Lw)
                      for i in btJ.query(cellbox, predicate='intersects')]
        else:
            lines += [shapely.intersection(blines[i], cellbox) for i in btree.query(cellbox, predicate='intersects')]
        lines += [Polygon(cp[k][j][1]).exterior for j in offp[k]]
        for _ in range(4):                                # a face with a hole (cell polygons have none): cut it
            net = shapely.union_all([x for x in lines if not x.is_empty], grid_size=1.0)
            faces = shapely.get_parts(shapely.polygonize(shapely.get_parts(net)))
            holes = [h for f in faces for h in f.interiors]
            if not holes:
                break
            lines += hole_cuts(g, k, holes, [Polygon(cp[k][j][1]) for j in range(len(cp[k])) if j not in offp[k]])
            stats['cells cut round a hole'] += 1
        land, off = collections.defaultdict(list), []
        for f in faces:
            q = f.representative_point()
            if not Of.covers(q):
                continue
            (land[label(q, jc)] if LL.covers(q) else off).append(f)
        tot = sum(f.area for fs in land.values() for f in fs) + sum(f.area for f in off)
        # noding on the 1-unit grid rounds crossings off the original off-map edges by < 1 unit: area slack = its perimeter
        assert abs(tot - Of.area) < max(1.0, Of.length), ('faces must tile the off-map of the cell', k, tot, Of.area)
        if len(land) == 1 and not off and abs(Of.area - S * S) < 1.0:
            T = next(iter(land))
            g.cells[k] = pm.Cell(c.costs8, uniform=pm.Trait(0, 0, 255, dom(T))); stats['uniform land'] += 1
            continue
        bounds = [b for j, b in enumerate(c.boundaries) if j not in offp[k]]
        nv = len(bounds)
        cap = MAX_LAND_POLYS - sum(landc(b.trait) for b in bounds) if jc else MAX_LAND_POLYS   # weld: middle20 has 4 bits
        pieces_ = [[T, p] for T in sorted(land, key=lambda T: (len(T), T)) for p in merged(land[T])]
        assert cap >= 1 or not pieces_, ('weld cell: 4 vanilla land polygons already', k % C, k // C)
        while len(pieces_) > cap:
            # smallest piece first, into the neighbour it shares most border with; a union with a hole (or none) tries
            # the next pair (2026-10-28: the friend-list splits gave a cell whose first pick left a hole)
            def merge():
                for smp in sorted(pieces_, key=lambda tp: tp[1].area):
                    for o in sorted((tp for tp in pieces_ if tp is not smp),
                                    key=lambda tp: -smp[1].boundary.intersection(tp[1].boundary).length):
                        u = shapely.union_all([smp[1], o[1]], grid_size=1.0)
                        if u.geom_type == 'Polygon' and not u.interiors:
                            return smp, o, u
                raise AssertionError(('cannot merge a small land piece', k))
            smp, o, u = merge()
            o[1] = u; pieces_.remove(smp)
            stats['small land pieces relabelled (>4 per cell)'] += 1
        nl = 0
        for T, p in pieces_:
            P[key] = ids_of(k, p); bounds.append(pm.Boundary(pm.Trait(0, 0, 255, dom(T)), key)); key += 1; nl += 1
        for p in merged(off) if off else []:
            P[key] = ids_of(k, p); bounds.append(pm.Boundary(lp.OFF, key)); key += 1
        if jc:
            weld_vertices(k, bounds, nv)
        g.cells[k] = pm.Cell(c.costs8, bounds)
        stats['mixed'] += 1
        stats['max land polys/cell'] = max(stats['max land polys/cell'], nl)
        stats['cells with 2+ domains'] += len(land) > 1
        if n_ % 20000 == 0:
            print(f'  cell {n_}/{len(work)}', flush=True)
    for T in comps:
        g.path_table = g.path_table + (len(T),) + tuple(pos1[r] for r in T)
    assert [g.path_domains()[dom_of[T]] for T in comps] == comps
    area.vertices_fixed = tuple(verts)
    pf_gen.weld(area, P, kept)
    mod = [k for k in range(C * R) if not kept[k]]
    isnew = lambda b: b.polygon_offset >= key0 and b.polygon_offset not in vreb
    isl = lambda b: b.trait.kind == 0 and (b.trait.path_id in mine or weld and isnew(b))
    for k in mod:
        for b in g.cells[k].boundaries:
            if isl(b):
                b.trait = pm.Trait(0, 0, pm.contact_mask(area.points(k, P[b.polygon_offset]), g.corners(k)), b.trait.path_id)
    for k in mod:
        c = g.cells[k]
        if c.uniform is not None:
            t = c.uniform
            g.cells[k] = pm.Cell(c.costs8, uniform=pm.Trait(0, probe_g3.middle20(area, P, k, area.points(k, (0, 2, 3, 1)), t),
                                                            255, t.path_id))
            continue
        for b in c.boundaries:
            if isl(b):
                t = b.trait
                b.trait = pm.Trait(0, probe_g3.middle20(area, P, k, area.points(k, P[b.polygon_offset]), t), t.contact_mask, t.path_id)
    if weld:
        def newbits(i):                                 # middle20 bits of the land polygons of cell i that are new
            cc = g.cells[i]
            if cc.uniform is not None:
                return int(not kept[i] and landc(cc.uniform))
            return sum(1 << j for j, b in enumerate([b for b in cc.boundaries if landc(b.trait)][:4]) if isnew(b))
        for k in sorted(jset):                          # vanilla land polygons of the weld cells: + their links to new land
            r, col = divmod(k, C)
            nm_ = sum(newbits((r + dy) * C + col + dx) << 4 * nib for nib, (dx, dy) in enumerate(((0, -1), (-1, 0), (0, 0), (1, 0), (0, 1)))
                      if 0 <= col + dx < C and 0 <= r + dy < R)
            c = g.cells[k]
            for b in ([] if c.uniform is not None else c.boundaries):
                if landc(b.trait) and not isnew(b):
                    t = b.trait
                    add = probe_g3.middle20(area, P, k, area.points(k, P[b.polygon_offset]), t) & nm_ & ~t.middle20
                    if add:
                        b.trait = pm.Trait(t.kind, t.middle20 | add, t.contact_mask, t.path_id)
                        stats['weld: vanilla polygons linked to new land'] += 1

        def newm(i):                                    # land_mask of the new land polygons of cell i (any domain)
            cc = g.cells[i]
            if cc.uniform is not None:
                return 255 if not kept[i] and cc.uniform.kind == 0 else 0
            mm = 0
            for b in cc.boundaries:
                if b.trait.kind == 0 and isnew(b):
                    mm |= b.trait.contact_mask
            return mm
        w8mod = {k for k in work8 if not kept[k] and (k not in jset or shapely.intersection(boxes[k], Ls).area > 0)}
    lm = newm if weld else (lambda i: lpb.land_mask(g.cells[i], mine))
    for k in mod:
        r, col = divmod(k, C)
        cs = bytearray(g.cells[k].costs8)
        mk = lm(k)
        for d, (dx, dy) in enumerate(lp.DIRS):
            j = (r + dy) * C + col + dx
            if mk >> d & 1 and lm(j) >> lp.OPP[d] & 1:
                cs[d] = lp.LAND_COST
            elif weld and k not in w8mod and j not in w8mod:
                stats['weld: steps kept at the vanilla cost'] += 1   # a weld-only cell: its other steps stay vanilla
            elif cs[d] in (0x1f, 0xff, 1):
                cs[d] = lp.BLOCKED
        c = g.cells[k]
        g.cells[k] = pm.Cell(bytes(cs), c.boundaries, c.uniform)
    nc, rstats, rsingle = len(comps), {}, {}
    for k, d in rsplit.items():                       # after the costs8 pass: re-tagged cells are vanilla, kept[] stays 1
        rstats[k], rsingle[k] = split_retag(area, P, d['index'], first + keys.index(k), polys[k], info['split_polys'][k], dom)
        for T in comps[nc:]:                          # before the next split reads path_domains (Porto, then Galiza)
            g.path_table = g.path_table + (len(T),) + tuple(pos1[r] for r in T)
        nc = len(comps)
    for T in comps[nc:]:
        g.path_table = g.path_table + (len(T),) + tuple(pos1[r] for r in T)
    assert [g.path_domains()[dom_of[T]] for T in comps] == comps
    pf_gen.compact(area, P)
    if weld:                                          # pf_gen.weld compares side vertices only: intervals too
        bad, ex = pf_check.check(area, near)
        assert not bad, ('weld cells: unwelded sides', dict(bad), ex[:2])
    assert len(g.path_domains()) <= 1023, ('path domains past the 10-bit ids', len(g.path_domains()))
    stats['modified cells'] = len(mod)
    to_w = lambda p: shapely.transform(p, lambda c: c / FIX)
    single = {}
    for n, k in enumerate(keys):
        others = [B[i] for i in btree.query(B[n], predicate='intersects') if i != n]
        single[k] = to_w(rsingle[k] if k in rsplit else
                         Ls.intersection(B[n]).difference(shapely.union_all(others)) if others else Ls.intersection(B[n]))
    rn = dict(enumerate(info['region_names']))      # a split's composites meet any vanilla neighbour (Andalusia: Portugal)
    rn.update(zip(ridx, rname))
    assert all(r in rn for T in comps for r in T), ('composite with an unnamed vanilla member', [T for T in comps if not set(T) <= set(rn)])
    pinfo = dict(domains={keys[n]: doms[n] for n in range(len(keys))}, sea=sea,
                 composites={'+'.join(rn[r] for r in T): dom_of[T] for T in comps},
                 stats=dict(stats), land_u2=round(Ls.area / FIX / FIX, 1), land_parts=len(shapely.get_parts(Ls)),
                 land_dropped_u2=round(dropped / FIX / FIX, 1))
    if weld:
        pinfo.update(vanilla_domains=vdom, vanilla_index={v: wgeom['index'][v] for v in vdom}, weld=dict(wstats, cells=sorted(jset)))
    if rsplit:                                        # the split regions' old singletons (composite names, leaf-8 flags)
        # the true singleton id: vanilla's path_table permutes a few (eur_little_tatary = 21, region_indices.index gives 22)
        pinfo.setdefault('vanilla_domains', {}).update({d['of']: g.path_domains().index((d['index'],)) for d in rsplit.values()})
        pinfo.setdefault('vanilla_index', {}).update({d['of']: d['index'] for d in rsplit.values()})
        pinfo['split'] = rstats
    vm = {r for T in comps for r in T if r < first}  # every vanilla composite member: append_composites' leaf-8 AND, check
    pinfo.setdefault('vanilla_domains', {}).update({rn[r]: g.path_domains().index((r,)) for r in vm})
    pinfo.setdefault('vanilla_index', {}).update({rn[r]: r for r in vm})
    return m, to_w(Ls), single, pinfo


def split_retag(area, P, ro, rn, new_poly, old_poly, dom):
    """split_ring: every polygon of a domain holding the old region ro whose area meets the new part's BAND-grown
    polygon gets the domain of its members minus ro, plus rn, plus ro again if it meets the old part's band too (the
    label rule of new land; dom allocates a composite on first use).  Only path ids change (the 10-bit field of the
    boundary word: same polygon words; middle20 / contact masks / costs8 depend on the land class only).
    -> (stats, the land of the new singleton domain, fixed units)."""
    g = area.grid
    doms = g.path_domains()
    BN, BO = band_polygon(new_poly), band_polygon(old_poly)
    shapely.prepare(BN); shapely.prepare(BO)
    st, land = collections.Counter(), []
    meets = lambda b, q: shapely.intersects(b, q) and shapely.intersection(b, q).area > 0
    for c in cells_under(g, BN):
        cell = g.cells[c]
        for j, (t, q) in enumerate(probe_g3.cell_polys(area, P, c)):
            if t.path_id == 1023 or ro not in doms[t.path_id]:
                continue
            Q = Polygon(q)
            if not meets(BN, Q):
                continue
            T = tuple(sorted(set(doms[t.path_id]) - {ro} | {rn} | ({ro} if meets(BO, Q) else set())))
            nt = pm.Trait(t.kind, t.middle20, t.contact_mask, dom(T))
            if cell.uniform is not None:
                cell.uniform = nt
            else:
                cell.boundaries[j].trait = nt
            st[f'{doms[t.path_id]} -> {T} kind {t.kind}'] += 1
            if t.kind == 0 and T == (rn,):
                land.append(Q)
    return dict(st), shapely.union_all(land)


# ---------------------------------------------------------------- poi.esf, trade
def zones_poi(rpath, keys):
    """world_zones.poi_zones minus the kind-6 sea node it gives every region past its NV=101 without a lattice node,
    land ones too (ours: the tail, its fallback nodes are sorted by region index) -> (bytes, nodes dropped)."""
    p = cm.read_poi(esf.loads(wz.poi_zones(rpath)))
    bad = [j for j, n in enumerate(p.nodes) if n.kind == 6 and n.region in set(keys)]
    assert bad == list(range(len(p.nodes) - len(bad), len(p.nodes))), 'stray sea nodes are the tail'
    del p.nodes[len(p.nodes) - len(bad):]
    assert all(n.id == j for j, n in enumerate(p.nodes))
    return esf.dumps(cm.write_poi(p)), len(bad)


def poi(base, e, info, place, single):
    """land_probe_b.poi for every new region (pass group = the region area holding the node)."""
    p = cm.read_poi(esf.loads(base))
    rd = e.root.find('region_data')
    items = rd.find('regions').items
    names, kinds = [it[0].value for it in items], [it[1].value for it in items]
    polys = rm.area_polygons(rd)
    nid = max(x.id for x in p.nodes) + 1
    new, nb_of, bd = [], {}, {}
    for n, k in enumerate(info['keys']):
        ri = info['first_index'] + n
        Rp = info['polys'][k]
        areas = [(rm.area_fields(ar)['pass_group'], polys[ri << 16 | a]) for a, ar in enumerate(rm.sub(items[ri], 'areas').items)]
        pg_of = lambda q: next(pg for pg, a in areas if a.covers(Point(q)))
        borders = collections.defaultdict(list)
        for code, q in polys.items():
            j = code >> 16
            if j == ri or names[j].startswith('eur_map_') or not (kinds[j] == 'sea' or rm.sub(items[j], 'settlement_and_slots')):
                continue
            if q.distance(Rp) > 0:
                continue
            ln = Rp.boundary.intersection(q.boundary)
            if ln.length > 0:
                borders[names[j]].append(ln)
        borders = bd[k] = {j: shapely.union_all(v) for j, v in borders.items()}
        nb_of[k] = sorted(borders)
        nbs = lambda q: [(j, lp.f32(borders[j].distance(Point(q)))) for j in sorted(borders)]
        mk = lambda kind, q, dist: (lambda nb, pg: cm.PoiNode(nid + len(new), kind, True, int(round(q[0] * FIX)), int(round(q[1] * FIX)), k,
                                                              pg, k, pg, lp.f32(dist), nb, min(d for _, d in nb), [], [], 0, False))(nbs(q), pg_of(q))
        pos = place[k]['pos']
        new.append(mk(4, pos, 0.0))
        Z = single[k]
        x0, y0, x1, y1 = Z.bounds
        grid = [(x, y) for x in np.arange(math.ceil(x0 / 8) * 8, x1, 8.0) for y in np.arange(math.ceil(y0 / 8) * 8, y1, 8.0)
                if Z.contains(Point(x, y)) and Z.boundary.distance(Point(x, y)) > 2.0 and Point(x, y).distance(Point(pos)) > 5.0]
        grid.sort(key=lambda q: Point(q).distance(Point(pos)))
        for q in grid[:10]:
            new.append(mk(2, (float(q[0]), float(q[1])), Point(q).distance(Point(pos))))
    nv = 0
    for k, vs in (info.get('weld') or {}).items():      # stage 'j': the welded vanilla regions' nodes list the new region
        for v in vs:
            ln = info['polys'][k].boundary.intersection(shapely.union_all(
                [q for code, q in polys.items() if names[code >> 16] == v]).boundary)
            assert ln.length > 0, ('welded pair shares no border', k, v)
            for n in p.nodes:
                if n.region == v and n.kind in (1, 2, 4, 5, 7):    # the kinds with a neighbour list (research/08)
                    n.neighbors = n.neighbors + [(k, lp.f32(ln.distance(Point(n.wx, n.wy))))]
                    n.min_dist = min(d for _, d in n.neighbors)
                    nv += 1
    for k, d in (info.get('split') or {}).items():     # split_ring: the old region's nodes in the new part become the new
        Rp, pos = info['polys'][k], Point(place[k]['pos'])   # region's (its border distances, settlement distance), the
        ln = bd[k][d['of']]                             # rest list the new region as a neighbour (as the weld above)
        apg = {rm.area_fields(ar)['pass_group'] for ar in rm.sub(items[info['first_index'] + info['keys'].index(k)], 'areas').items}
        for n in p.nodes:
            if n.region != d['of']:
                continue
            q = Point(n.wx, n.wy)
            # a node tied to an area the old region keeps stays its (France: a kind-5 node on Berry's land, pass group of a French mountain)
            if Rp.covers(q) and n.area in apg:
                assert n.kind != 4, ('split_ring: the old settlement node lies in the new part', k)
                n.region = n.region2 = k
                if n.dist:
                    n.dist = lp.f32(q.distance(pos))
                if n.kind in (1, 2, 4, 5, 7):
                    n.neighbors = [(j, lp.f32(bd[k][j].distance(q))) for j in sorted(bd[k])]
                    n.min_dist = min((x for _, x in n.neighbors), default=-1.0)
                nv += 1
            elif n.kind in (1, 2, 4, 5, 7):
                n.neighbors = n.neighbors + [(k, lp.f32(ln.distance(q)))]
                n.min_dist = min(x for _, x in n.neighbors)
                nv += 1
        reg = lambda r: shapely.union_all([q for c, q in polys.items() if names[c >> 16] == r])
        Ro = reg(d['of'])
        for t in bd[k]:                                 # a third land region the cut touches (Andalusia: Portugal): its nodes
            if t == d['of'] or t in info['keys'] or kinds[names.index(t)] == 'sea':   # list the new region, and it and
                continue                                # the old region measure their shrunk border afresh
            lo = Ro.boundary.intersection(reg(t).boundary)
            for n in p.nodes:
                if n.kind not in (1, 2, 4, 5, 7) or n.region not in (t, d['of']):
                    continue
                q, o = Point(n.wx, n.wy), d['of'] if n.region == t else t
                nb = [(j, lp.f32(lo.distance(q)) if j == o else x) for j, x in n.neighbors if j != o or lo.length > 0]
                n.neighbors = nb + [(k, lp.f32(bd[k][t].distance(q)))] * (n.region == t)
                n.min_dist = min((x for _, x in n.neighbors), default=-1.0)
                nv += 1
    p.nodes += new
    poi.vanilla_nodes_extended = nv
    return esf.dumps(cm.write_poi(p)), new, nb_of


def land_trade_routes(e, info, place, first_node, vnode):
    """(node a, node b, f32 length) per pair of settlements whose regions share a border, one of them new (land_probe_b;
    vanilla <-> new only at stage 'j' welds, elsewhere the strip keeps them apart).  vnode: {vanilla settlement: node}."""
    L = wz.shared_lengths(e)
    f, keys = info['first_index'], info['keys']
    rg = rm.extract(e)['regions']
    node = lambda i: first_node + i - f if i >= f else vnode[rg[i]['name']]
    pos = lambda i: place[keys[i - f]]['pos'] if i >= f else rg[i]['settlement']['pos']
    out = []
    for (a, b), ln in sorted(L.items()):
        if b >= f and ln > 0 and (a >= f or rg[a]['name'] in vnode):
            d = math.dist(pos(a), pos(b))
            out.append((node(a), node(b), struct.unpack('<f', struct.pack('<f', d))[0]))
    return out


# ---------------------------------------------------------------- startpos
REBELS = {'britain': lp.REBEL_KEY, 'spain': 'spanish_rebels', 'france': 'french_rebels', 'russia': 'slavic_rebels',
          'netherlands': 'united_netherlands',                      # = eur_holland's (afr_cape_colony)
          'portugal': 'portugal',                                   # = eur_portugal's (no portuguese rebels faction)
          'ottomans': 'ottomans'}                                   # = eur_rumelia's


def owner_info(sp, owners, e, g):
    """{vanilla owner: game handle, FACTION, GOVERNORSHIP (most regions), CAI faction id, PATHFINDING_GRID leaf-8 flag of
    most of its vanilla regions' domains}."""
    fa = next(cm._iter_recs(sp.root, 'FACTION_ARRAY'))
    F = {lpb.fkey(it[0]): it[0] for it in fa.items}
    ra = next(cm._iter_recs(sp.root, 'REGIONS_ARRAY'))
    w = next(cm._iter_recs(sp.root, 'CAI_WORLD'))
    cfa = {it[-1].children[6].value: it[2].value for it in w.find('CAI_WORLD_FACTIONS').items}
    b8 = next(cm._iter_recs(sp.root, 'PATHFINDING_GRID')).items[0][8].value
    names = [it[0].value for it in e.root.find('region_data').find('regions').items]
    pd = g.path_domains()
    out = {}
    for o in owners:
        h = lpb.fhandle(F[o])
        gov = max(cm._iter_recs(F[o], 'GOVERNORSHIP'), key=lambda x: len(x.children[2].array()))
        regs = [r[0].children[0].value for r in ra.items if r[0].children[20].value == h]
        flags = collections.Counter(b8[pd.index((names.index(r),))] for r in regs)   # not owner-pure (eur_wales 0)
        assert regs, o
        rebels = {r[0].children[24].value for r in ra.items}
        reb = REBELS.get(o) or collections.Counter(r[0].children[24].value for r in ra.items
                                                   if r[0].children[20].value == h).most_common(1)[0][0]   # sweden: Gotland
        assert reb in rebels, (o, reb)
        out[o] = dict(handle=h, gov=gov.children[1].value, cai=cfa[h], flag=flags.most_common(1)[0][0], flags=dict(flags),
                      rebels=reb)
    return out


def startpos_regions(sp, sp_, info, place, pinfo, P, S0):
    """land_probe.startpos per region (Britain-owned eur_ireland clone, trade-registered), its LINE_OF_SIGHT moved by
    the template offset rounded to 10 u (whole bit-array blocks)."""
    saved = (lp.KEY, lp.TOWN, lp.LOC_SUFFIX, lp.REBEL_NAME, lp.shift_los)
    by = {s['key']: s for s in sp_}
    shift = lp.shift_los
    out = {}
    used = lp.all_ints(sp.root)                          # once: startpos adds its own 6 handles to it
    try:
        lp.shift_los = lambda los, D: shift(los, (round(D[0] / 10) * 10, round(D[1] / 10) * 10))
        for n, k in enumerate(info['keys']):
            s = by[k]
            lp.KEY, lp.TOWN, lp.LOC_SUFFIX, lp.REBEL_NAME = k, s['town'], s['loc_suffix'], s['rebel']
            pg = cm.first_rec(sp.root, 'PATHFINDING_GRID').items[0]
            out[k] = lp.startpos(sp, place[k]['D'], place[k]['pos'], 'trade',
                                 dict(dom=pinfo['domains'][k], domains_before=len(pg[8].value), P=P, S=S0 + n, used=used))
    finally:
        lp.KEY, lp.TOWN, lp.LOC_SUFFIX, lp.REBEL_NAME, lp.shift_los = saved
    return out


def hand_over(sp, k, region_handle, owner, oi):
    """REGION k (Britain's after land_probe.startpos) -> vanilla faction owner: REGION_OWNERSHIPS, governorship lists,
    owner / governorship handles and owner strings in the REGION (as land_probe_b.faction_new), rebels."""
    fa = cm.first_rec(sp.root, 'FACTION_ARRAY')
    F = {lpb.fkey(it[0]): it[0] for it in fa.items}
    bh = lpb.fhandle(F[lp.OWNER])
    bgov = cm.first_rec(F[lp.OWNER], 'GOVERNORSHIP', lp.GOV, lambda x: x.children[1].value == lp.GOV)
    ngov = cm.first_rec(F[owner], 'GOVERNORSHIP', oi['gov'], lambda x: x.children[1].value == oi['gov'])
    rest = [h for h in bgov.children[2].array() if h != region_handle]
    assert len(rest) == len(bgov.children[2].array()) - 1
    bgov.children[2] = Val(0x48, struct.pack(f'<{len(rest)}I', *rest))
    ngov.children[2] = Val(0x48, ngov.children[2].value + struct.pack('<I', region_handle))
    own = cm.first_rec(sp.root, 'REGION_OWNERSHIPS_BY_THEATRE').items[0][1]
    hit = [it for it in own.items if it[0].value == k]
    assert len(hit) == 1
    hit[0][1] = Val(0x0e, owner)
    reg = next(r[0] for r in cm.first_rec(sp.root, 'REGIONS_ARRAY').items if r[0].children[0].value == k)
    cnt = collections.Counter()

    def fix(kids, j, v):
        if v.tag in (0x04, 0x08) and v.value == bh:
            kids[j] = Val(v.tag, oi['handle']); cnt['owner handles'] += 1
        elif v.tag in (0x04, 0x08) and v.value == lp.GOV:
            kids[j] = Val(v.tag, oi['gov']); cnt['governorship handles'] += 1
        elif v.tag == 0x0e and v.value == lp.OWNER:
            kids[j] = Val(0x0e, owner); cnt['owner strings'] += 1
    lp.walk_vals(reg, fix)
    reg.children[24] = Val(0x0e, oi['rebels'])
    assert reg.children[20].value == oi['handle'] and reg.children[22].value == oi['gov']
    return dict(cnt)


def domain_flags(sp, pinfo, flag_of, like=None):
    """Leaf 8 of the new singletons = flag_of; like {key: vanilla domain} (splits): leaves 8 and 11 copied from it."""
    pg = next(cm._iter_recs(sp.root, 'PATHFINDING_GRID')).items[0]
    b8 = bytearray(pg[8].value)
    f11 = list(struct.unpack(f'<{len(b8)}f', pg[11].value))
    like = like or {}
    for k, d in pinfo['domains'].items():
        b8[d] = b8[like[k]] if k in like else flag_of[k]
        f11[d] = f11[like[k]] if k in like else f11[d]
    pg[8] = Val(0x41, bytes(b8))
    pg[11] = Val(0x4a, struct.pack(f'<{len(f11)}f', *f11))


def split_slots(e, info):
    """split_ring, regions.esf: the old region's slot descriptions whose building lies in the new region move to it
    (keys kept: db, loc, trade_routes.esf and the startpos name them) -> {key: dict(of, slots [(slot key, dock xy)])}."""
    items = e.root.find('region_data').find('regions').items
    names = [it[0].value for it in items]
    out = {}
    for k, d in (info.get('split') or {}).items():
        R = info['polys'][k]
        ss = rm.sub(items[d['index']], 'settlement_and_slots')
        assert not R.covers(Point(ss.children[0].value)), ('split_ring: the old settlement lies in the new part', k)
        src = ss.find('slot_descriptions')
        dst = rm.sub(items[names.index(k)], 'settlement_and_slots').find('slot_descriptions')
        mv = [s for s in src.items if R.contains(Point(s[2].value[0], s[2].value[2]))]
        assert not any(s[1].value in lp.KEEP_SLOTS for s in mv), ('split_ring: an old settlement slot in the new part', k)
        src.items = [s for s in src.items if not any(s is x for x in mv)]
        dst.items += mv
        out[k] = dict(of=d['of'], slots=[(s[0].value, tuple(map(float, s[3].value))) for s in mv])
    return out


def split_trade(items, tr, moved, keys, place):
    """A port moved by split_slots: its route to the old settlement goes to the new one (spline-less, straight from the
    dock, as port_probe's).  items: trade_routes.esf ROUTES or startpos TRADE_ROUTES (same layout); tr: the vanilla
    trade_routes (new settlements = P + S + their key index) -> routes repointed."""
    P, S = len(tr.ports), len(tr.settlements)
    tpl = next(it[2] for it in items if not it[2].array())
    n = 0
    for k, d in moved.items():
        old, new = P + tr.settlements.index(d['of']), P + S + keys.index(k)
        for slot, dock in d['slots']:
            if not slot.startswith('port:'):
                continue
            pi = tr.ports.index(slot)
            hit = [it for it in items if {it[0].value, it[1].value} == {pi, old}]
            assert hit, ('split: no route from the moved port to its old settlement', slot)
            for it in hit:
                j = 1 if it[1].value == old else 0
                it[j], it[2] = Val(it[j].tag, new), copy.deepcopy(tpl)
                it[3] = Val(it[3].tag, lp.f32(math.dist(dock, place[k]['pos'])))
                n += 1
    return n


def split_startpos(sp, e, moved):
    """split_slots in the startpos: the REGION_SLOTs move to the new REGION's slot array; their CAI_REGION_SLOT (owner
    link, building CAI_SITUATED region + its CAI_REGION [0] list, as port_probe.Cai.add) and the CAI_REGION slot lists
    follow (CAI ids kept: the beliefs naming them stay valid).  The new REGION takes the old one's rebels (Crimea:
    crimean_khanate).  Run after cai_regions -> {key: dict(rebels, cai_region_slots)}."""
    reg = {it[0].children[0].value: it[0] for it in cm.first_rec(sp.root, 'REGIONS_ARRAY').items}
    w = cm.first_rec(sp.root, 'CAI_WORLD')
    R, RS, BS = (w.find(n) for n in ('CAI_WORLD_REGIONS', 'CAI_WORLD_REGION_SLOTS', 'CAI_WORLD_BUILDING_SLOTS'))
    names = [it[0].value for it in e.root.find('region_data').find('regions').items]
    skey = lambda rs: next(v.value for v in rs.children if isinstance(v, Val) and v.tag == 0x0e)
    out = {}
    for k, d in moved.items():
        o = d['of']
        assert reg[k].children[20].value == reg[o].children[20].value, ('split to another owner: slots not handed over', k)
        reg[k].children[24] = Val(0x0e, reg[o].children[24].value)
        src, dst = (reg[x].find('REGION_SLOT_MANAGER').find('REGION_SLOT_ARRAY') for x in (o, k))
        ro, rn = R.items[names.index(o)], R.items[names.index(k)]
        cai = []
        for slot, _ in d['slots']:
            (it,) = [x for x in src.items if skey(x[0]) == slot]
            src.items = [x for x in src.items if x is not it]
            dst.items.append(it)
            (bs,) = [b for b in BS.items if b[-1].children[0].value == it[0].children[2].value]
            rsid = bs[-1].children[2].value
            (rsl,) = [x for x in RS.items if x[3].value == rsid]
            assert rsl[0].children[0].value == rsl[1].children[2].value == ro[2].value, ('CAI slot not the old region\'s', slot)
            rsl[0].children[0] = Val(0x08, rn[2].value)
            rsl[1].children[2], rsl[1].children[3] = Val(0x08, rn[2].value), wz.u32a(rn[-1].children[0].array())
            ro[-1].children[3] = wz.u32a([i for i in ro[-1].children[3].array() if i != rsid])
            rn[-1].children[3] = wz.u32a(rn[-1].children[3].array() + [rsid])
            cai.append(rsid)
        out[k] = dict(rebels=reg[k].children[24].value, cai_region_slots=cai)
    return out


def refresh_filler_hlcis(H, R, regs, P, rid, wi, new_hlci):
    """eur_map_west's HLCIs after the carve: area lists re-indexed, the HLCI of a pass group whose last filler area was
    used up removed, a point no longer on its group moved to an interior point; a new filler pass group (carve's kept
    filler pieces) gets a new HLCI from new_hlci(pass group, area list, polys) -> id."""
    hl = {it[1].value: it for it in H.items}
    c = R.items[wi][-1].children
    gr = wz.groups(regs, P, wi)
    have = {hl[h][-1].children[1].value: h for h in c[1].array()}
    added = [new_hlci(pg, *gr[pg]) for pg in sorted(set(gr) - set(have))]
    keep, removed, moved, reidx = [], [], [], 0
    for h in c[1].array():
        hc = hl[h][-1].children
        pg = hc[1].value
        if pg not in gr:
            removed.append(h); continue
        al, polys = gr[pg]
        if hc[2].array() != al:
            hc[2] = wz.u32a(al); reidx += 1
        if not any(q.covers(Point(hc[3].value / FIX, hc[4].value / FIX)) for q in polys):
            hc[3].value, hc[4].value = wz.interior_point(polys); moved.append(pg)
        keep.append(h)
    c[1] = wz.u32a(keep + added)
    H.items[:] = [it for it in H.items if it[1].value not in set(removed)]
    return dict(removed=removed, reindexed=reidx, moved_points=moved, added=len(added))


def east_carved(info):
    """Did carve cut eur_map_east (W3+: Africa, Malta; stress dummies)?"""
    return any(str(a).startswith(STRESS_FILLER) for v in info['filler_areas'].values() for a in v) or 'stress_carve' in info


def cai_regions(sp, e, keys, own, hm, fac, stages, oinfo, east=False, weld=()):
    """land_probe_b.cai_regions for the W1 region set on the zones startpos (CAI regions 0..138 exist; new = 139+):
      CAI_REGION + CAI_SETTLEMENT (+ 3 building slots) + HLCIs per region (eur_ireland templates), owner = the owner's
      CAI faction (new factions: pre-allocated, cai_faction.clone_cai_faction completes them), CAI_GOVERNORSHIP =
      the owner's (new factions: Britain's until clone_cai_faction hands them over);
      eur_map_west HLCIs refreshed (refresh_filler_hlcis);
      CAI_REGION_BOUNDARY for every new land pair, and with stage 'l' every new land <-> sea pair, with 'j' every
      welded new <-> vanilla land pair;
      groups: vanilla owners' regions join an existing group of the owner (Britain: eur_ireland's, the b1 recipe;
      others: their largest land group), each new faction gets its own (land_probe_b.usa_group); groups list the
      regions bordering their new members as neighbours, both ways; the region-group analyser map; THEATRE list;
      land_beliefs (22 per region, NV = 139)."""
    rd = e.root.find('region_data')
    regs, P = rm.extract(e)['regions'], rm.area_polygons(rd)
    w = next(cm._iter_recs(sp.root, 'CAI_WORLD'))
    central = next(cm._iter_recs(sp.root, 'CAI_CENTRAL_BDI_POOL'))
    nxt = central.children[0].value
    R, H, B = (w.find(n) for n in ('CAI_WORLD_REGIONS', 'CAI_WORLD_REGION_HLCIS', 'CAI_WORLD_REGION_BOUNDARIES'))
    names = [r['name'] for r in regs]
    first = len(R.items)
    assert [it[-1].children[10].value for it in R.items] == names[:first] and names[first:] == keys and first == 139
    blank = copy.deepcopy(H.items[0][:-1])

    def new_id():
        nonlocal nxt
        nxt += 1
        return nxt - 1

    def top(i):
        t = copy.deepcopy(blank); t[1] = Val(0x08, i); return t
    tmpl = R.items[names.index(TPL)]
    ST, BS = w.find('CAI_WORLD_SETTLEMENTS'), w.find('CAI_WORLD_BUILDING_SLOTS')
    stmpl = next(it for it in ST.items if it[3].value == tmpl[-1].children[2].value)
    btmpl = [it for it in BS.items if it[-1].children[2].value == stmpl[3].value]
    assert len(stmpl) == len(blank) + 5 and stmpl[-1].name == 'CAI_SETTLEMENT' and len(btmpl) == 3
    brit = stmpl[0].children[0].value
    assert brit == oinfo[lp.OWNER]['cai']
    cgov = {it[-1].children[0].value: it for it in w.find('CAI_WORLD_GOVERNORSHIPS').items}
    fac = fac or {}
    UF = {f: new_id() for f in fac}
    cai_owner = lambda k: UF[own[k]] if own[k] in fac else oinfo[own[k]]['cai']
    for i in range(first, len(regs)):
        k = names[i]
        assert regs[i]['kind'] == 'land' and regs[i]['settlement'], k
        rec = copy.deepcopy(tmpl[-1]); c = rec.children
        c[1], c[3], c[6], c[7], c[9], c[13] = (wz.u32a([]) for _ in range(6))
        sx, sy = regs[i]['settlement']['pos']
        c[4].value, c[5].value = float(np.float32(sx)), float(np.float32(sy))
        c[10].value = k
        oi = copy.deepcopy(tmpl[0])
        R.items.append([oi] + top(new_id()) + [rec])
        m = hm[k]
        sid = new_id()
        st = copy.deepcopy(stmpl)
        st[0].children[0].value = cai_owner(k)
        sit = st[1].children
        sit[0].value, sit[1].value, sit[2].value = round(sx * wz.FIX), round(sy * wz.FIX), R.items[i][2].value
        spt = Point(sx, sy)                              # pass group of the area at the settlement (vanilla rule)
        sit[4].value = min(wz.groups(regs, P, i).items(), key=lambda kv: min(q.distance(spt) for q in kv[1][1]))[0]
        st[2:2 + len(blank)] = top(sid)
        cs = st[-1].children
        bids = []
        for b in btmpl:
            bid = new_id(); bc = copy.deepcopy(b[-1]); bc.children[0].value = m[bc.children[0].value]
            bc.children[2].value = sid
            BS.items.append(top(bid) + [bc]); bids.append(bid)
        cs[0] = wz.u32a(bids); cs[2].value = m[cs[2].value]
        g0 = st[len(blank) + 2].children; g0[0].value = 0; g0[2], g0[3] = wz.u32a([]), wz.u32a([])
        ST.items.append(st)
        oi.children[0].value = c[2].value = sid
        c[11].value = m[tmpl[-1].children[11].value]
        gv = cgov[lp.GOV if own[k] in fac else oinfo[own[k]]['gov']]
        c[12].value = gv[1].value
        gv[-1].children[3] = wz.u32a(gv[-1].children[3].array() + [R.items[i][2].value])
        for pg, (al, polys) in wz.groups(regs, P, i).items():
            spt = Point(sx, sy)
            x, y = ((round(sx * wz.FIX), round(sy * wz.FIX)) if any(q.covers(spt) for q in polys)
                    else wz.interior_point(polys))
            h = new_id()
            H.items.append(top(h) + [Rec('CAI_REGION_HLCI', 0, [Val(0x08, R.items[i][2].value), Val(0x08, pg), wz.u32a(al),
                                                                 Val(0x04, x), Val(0x04, y)])])
            c[1] = wz.u32a(c[1].array() + [h])
    rid = [it[2].value for it in R.items]

    def filler_hlcis(wi):
        def new_hlci(pg, al, polys):
            h, (x, y) = new_id(), wz.interior_point(polys)
            H.items.append(top(h) + [Rec('CAI_REGION_HLCI', 0, [Val(0x08, R.items[wi][2].value), Val(0x08, pg), wz.u32a(al),
                                                                 Val(0x04, x), Val(0x04, y)])])
            return h
        return refresh_filler_hlcis(H, R, regs, P, rid, wi, new_hlci)
    filler = filler_hlcis(names.index('eur_map_west'))
    if east:                                             # Africa / stress dummies carved out of STRESS_FILLER too
        filler = dict(west=filler, east=filler_hlcis(names.index(STRESS_FILLER)))
    for v in sorted(set(split_of(keys).values())):       # a split's vanilla region: its areas re-indexed (Gotland: Sweden 6 -> 5)
        filler = dict(filler if 'west' in filler else dict(west=filler), **{v: filler_hlcis(names.index(v))})
    CR = lambda i: R.items[i][-1].children
    valid = [CR(i)[8].value for i in range(len(R.items))]
    bnd, lsb = [], []
    L = wz.shared_lengths(e)
    adj = [(a, b) for (a, b), ln in sorted(L.items()) if ln > 0]
    for (a, b), ln in sorted(L.items()):
        if ln <= 0 or max(a, b) < first:
            continue
        both = min(a, b) >= first
        vland = frozenset((names[a], names[b])) in weld   # stage 'j': a welded vanilla land region <-> new region
        if not (valid[a] and valid[b] or vland):         # [8] (coastal) is off on inland Moscow, which has boundaries
            continue
        if not both:
            assert regs[min(a, b)]['kind'] == 'sea' or vland, (names[a], names[b])   # vland: weld ('j' only) or split
            if not vland and 'l' not in stages:
                continue
        h = new_id()
        B.items.append(top(h) + [Rec('CAI_REGION_BOUNDARY', 0, [Val(0x08, rid[a]), Val(0x08, rid[b]),
                                                                 Val(0x0a, float(np.float32(2 * ln))), Val(0x08, 0)])])
        for r in (a, b):
            CR(r)[7] = wz.u32a(CR(r)[7].array() + [h])
        (bnd if both or vland else lsb).append((names[a], names[b], round(ln, 1)))
    assert weld <= {frozenset(x[:2]) for x in bnd}, ('welded pair without a CAI boundary', weld)
    vsb = []                                             # stage v: zones' parked vanilla sea <-> wld sea pairs
    if 'v' in stages:
        assert 's' in stages, "v needs the wld sea beliefs (else 0xD6D9E0 from the vanilla-sea end)"
        have = {frozenset((it[-1].children[0].value, it[-1].children[1].value)) for it in B.items}
        for (a, b), ln in sorted(L.items()):
            if ln > 0 and a < wz.NV <= b < first and valid[a] and valid[b] and frozenset((rid[a], rid[b])) not in have:
                assert regs[a]['kind'] == regs[b]['kind'] == 'sea', (names[a], names[b])
                h = new_id()
                B.items.append(top(h) + [Rec('CAI_REGION_BOUNDARY', 0, [Val(0x08, rid[a]), Val(0x08, rid[b]),
                                                                         Val(0x0a, float(np.float32(2 * ln))), Val(0x08, 0)])])
                for r in (a, b):
                    CR(r)[7] = wz.u32a(CR(r)[7].array() + [h])
                vsb.append((names[a], names[b], round(ln, 1)))
    comps = wz.cai_components(sp)
    grp = {r: (k_, j) for k_, j in comps if isinstance(k_[-1], Rec) and k_[-1].name == 'CAI_BASIC_REGION_GROUP_ANALYSIS'
           for r in k_[-1].children[0].array()}
    gids = {k_[j + 1].value for k_, j in grp.values()}
    gby = {k_[j + 1].value: (k_, j) for k_, j in grp.values()}
    gak = [(k_, j) for k_, j in comps if isinstance(k_[-1], Rec) and k_[-1].name == 'CAI_ANALYSER'
           and isinstance(k_[-1].children[0], Val) and k_[-1].children[0].tag == 0x48 and set(k_[-1].children[0].array()) == gids]
    assert len(gak) == 1, 'one region group analyser'
    ga = gak[0][0][-1].children
    gmap = ga[1].array()
    amap = dict(zip(gmap[::2], gmap[1::2]))
    assert all(grp[r][0][grp[r][1] + 1].value == G for r, G in amap.items()), 'analyser map entries = membership'
    unmapped = sorted(r for r in grp if r not in amap)    # zones base: the 38 wld seas (world_zones joins them to 3789, not to the map)
    if 'm' in stages:                                    # stage m: map them (map = membership, as for every other region)
        gmap += [v for r in unmapped for v in (r, grp[r][0][grp[r][1] + 1].value)]
    G0 = grp[rid[names.index(TPL)]][0][grp[rid[names.index(TPL)]][1] + 1].value
    gown = {}
    for o in sorted({own[k] for k in keys if own[k] not in fac}):
        if o == lp.OWNER:
            gown[o] = G0
        else:
            cand = [(len(gby[x][0][-1].children[0].array()), -x, x) for x in gby
                    if gby[x][0][-1].children[3].value == oinfo[o]['cai'] and gby[x][0][-1].children[4].value == 0]
            gown[o] = max(cand)[2]
    extra, ugs = {}, {}
    for i in range(first, len(regs)):
        o = own[names[i]]
        if o not in fac and o != lp.OWNER:
            extra[i] = {G0: gown[o], brit: oinfo[o]['cai']}
    for f in fac:
        ugs[f], ex = lpb.usa_group(sp, gak[0], grp[rid[names.index(TPL)]], UF[f], brit,
                                   sorted(i for i in range(first, len(regs)) if own[names[i]] == f), rid, adj, regs, P, new_id)
        extra.update(ex)
    gby = {k_[j + 1].value: (k_, j) for k_, j in wz.cai_components(sp)}
    joined, newmem = {}, collections.defaultdict(set)
    for i in range(first, len(regs)):
        o = own[names[i]]
        k_, j = ugs[o] if o in fac else gby[gown[o]]
        gc = k_[-1].children
        assert gc[3].value == cai_owner(names[i]), 'group owner = the region\'s CAI owner'
        assert k_[j + 19].array() == gc[0].array() + gc[1].array(), 'group header = members + neighbours'
        gc[0] = wz.u32a(gc[0].array() + [rid[i]])
        k_[j + 19] = wz.u32a(gc[0].array() + gc[1].array())
        R.items[i][21] = wz.u32a([k_[j + 1].value] + R.items[i][21].array())
        gmap += [rid[i], k_[j + 1].value]
        joined[names[i]] = k_[j + 1].value
        if o not in fac:
            newmem[k_[j + 1].value].add(rid[i])
    ga[1] = wz.u32a(gmap)
    ar = {(rid[a], rid[b]) for a, b in adj} | {(rid[b], rid[a]) for a, b in adj}
    fwd = 0
    for G, mem in newmem.items():                       # existing groups: their new members' neighbours
        k_, j = gby[G]
        gc = k_[-1].children
        have = set(gc[0].array() + gc[1].array())
        add = sorted({y for x, y in ar if x in mem and y not in have})
        if add:
            gc[1] = wz.u32a(gc[1].array() + add)
            k_[j + 19] = wz.u32a(gc[0].array() + gc[1].array())
            for r in add:
                rk, rj = gby[r]
                rk[rj + 20] = wz.u32a(rk[rj + 20].array() + [G])
            fwd += len(add)
    nbs = lpb.group_neighbours(sp, rid[first:], adj, rid)
    th = w.find('CAI_WORLD_THEATRES').items[0][-1].children
    assert th[3].array() == rid[:first]
    th[3] = wz.u32a(rid)
    beliefs = lpb.land_beliefs(sp, R, ST, first, rid, new_id, extra)
    seas = sea_beliefs(sp, R, rid, new_id, first, stages)
    gen = {}
    if fac:
        fa = next(cm._iter_recs(sp.root, 'FACTION_ARRAY'))
        gh = {lpb.fkey(it[0]): lpb.fhandle(it[0]) for it in fa.items}
        for f, d in fac.items():
            ri = [i for i in range(first, len(regs)) if own[names[i]] == f]
            ri.sort(key=lambda i: names[i] != d['capital'])
            sx, sy = regs[ri[0]]['settlement']['pos']
            gen[f] = cf.clone_cai_faction(sp, gh[lpb.FAC_TPL], d['faction_handle'], d['hm'], [rid[i] for i in ri], new_id, U=UF[f],
                                          proxy_handle=gh[lpb.CAI_PROXY], cap_xy=(round(sx * wz.FIX), round(sy * wz.FIX)))
            gen[f].update(group=ugs[f][0][ugs[f][1] + 1].value, group_neighbours=ugs[f][0][-1].children[1].array())
    central.children[0].value = nxt
    return dict(regions=names[first:], hlcis=len(H.items), filler_hlcis=filler, land_boundaries=bnd, land_sea_boundaries=lsb, vanilla_wld_sea_boundaries=vsb,
                groups=joined, owner_groups=gown, base_unmapped_group_members=unmapped, forward_group_neighbours=fwd, groups_bordering=nbs, beliefs=beliefs, sea_beliefs=seas,
                next_id=nxt, factions=gen)


# ---------------------------------------------------------------- db, loc, lookup
FLAGS = os.path.join(ROOT, 'work/mods/flags/ui/flags')    # flags.py output (gn_<key>/, 24 files each; main overlays it)
OLD_FLAG = 'data\\ui\\flags\\' + lpb.FAC_TPL
flag_path = lambda key: 'data\\ui\\flags\\gn_' + key
PALETTE = 252                     # lookup colours besides black (lookup_tga.palettise asserts <= 252: + white, black)
REG_T = 'db/regions_tables/regions'
SET_T = 'db/campaign_map_settlements_tables/campaign_map_settlements'
COL_T = 'db/faction_uniform_colours_tables/faction_uniform_colours'


def split_of(keys):
    """{new key: the vanilla region it is split from} for keys (regions.json split_of)."""
    return {r['key']: r['split_of'] for r in json.load(open(os.path.join(DATA, 'regions.json'))) if r['key'] in keys and r.get('split_of')}


BORDER_H, BORDER_STEP = 0.00028, 0.3     # vanilla display/borders splines: height, point spacing (u; median 0.28)


def border_splines(e, ov, first):
    """display/borders/<region>_<n>.rigid_spline, as vanilla's 77: one open spline per land neighbour, under each side
    (Spain-Portugal = eur_spain_3 + eur_portugal_1).  Every land border with a region >= first, numbered after the
    region's vanilla files (world_m1's).  -> files written."""
    d = os.path.join(ov, MAPDIR, 'display', 'borders')
    os.makedirs(d, exist_ok=True)
    n_of = collections.Counter(f[:-len('.rigid_spline')].rsplit('_', 1)[0] for f in os.listdir(os.path.join(ROOT, 'work/mods/world_m1', MAPDIR, 'display', 'borders')))
    it = e.root.find('region_data').find('regions').items
    nm, kd = [x[0].value for x in it], [x[1].value for x in it]
    R = collections.defaultdict(list)
    for c, q in rm.area_polygons(e.root.find('region_data')).items():
        R[c >> 16].append(q)
    R = {i: shapely.union_all(v) for i, v in R.items()}
    nf = 0
    for (a, b), ln in sorted(wz.shared_lengths(e).items()):
        if ln <= 0 or max(a, b) < first or not kd[a] == kd[b] == 'land' or nm[a].startswith('eur_map_') or nm[b].startswith('eur_map_'):
            continue
        for g in shapely.get_parts(shapely.line_merge(shapely.intersection(R[a].boundary, R[b].boundary))):
            if g.geom_type != 'LineString' or g.length < 2 * BORDER_STEP:
                continue
            xy = np.array(shapely.segmentize(g, BORDER_STEP).coords)
            for r in (a, b):
                n_of[nm[r]] += 1
                open(os.path.join(d, f'{nm[r]}_{n_of[nm[r]]}.rigid_spline'), 'wb').write(
                    display.write_spline([display.spline_from_world(f'border:{nm[r]}:{n_of[nm[r]]}', xy, BORDER_H)]))
                nf += 1
    return nf


def split_pairs(e, keys):
    """{(vanilla land region, split key)} sharing a regions.esf edge: a split's land boundaries (CAI, check), its old
    region and any other neighbour its cut part touches (Andalusia: Portugal), never the eur_map_ fillers."""
    sk = set(split_of(keys))
    it = e.root.find('region_data').find('regions').items
    nm, kd = [x[0].value for x in it], [x[1].value for x in it]
    return {(nm[a], nm[b]) if nm[b] in sk else (nm[b], nm[a]) for (a, b), ln in wz.shared_lengths(e).items()
            if ln > 0 and (nm[a] in sk) != (nm[b] in sk) and kd[a] == kd[b] == 'land'
            and not (nm[a] if nm[b] in sk else nm[b]).startswith('eur_map_')}


def wave_of(key):
    keys = [r['key'] for r in json.load(open(os.path.join(DATA, 'regions.json')))]
    return next(w for w, (f, l, ex) in WAVES.items() if keys.index(f) <= keys.index(key) <= keys.index(l) and key not in ex)


def new_factions(sp_, built):
    """{key: factions.json entry + adj, desc} of the owners of built regions that are no vanilla faction (w1)."""
    F = {f['key']: f for f in json.load(open(os.path.join(DATA, 'factions.json')))}
    own = [s['owner'] for s in sp_ if s['key'] in built]
    out = {}
    for o in dict.fromkeys(own):
        if o not in F or F[o].get('vanilla'):          # not in factions.json: a vanilla faction it skips (sweden: Gotland)
            continue
        cap = F[o]['capital_region']
        if cap not in built:                             # oman: mea_oman comes later; its first built region until then
            cap = next(s['key'] for s in sp_ if s['key'] in built and s['owner'] == o)
        out[o] = dict(name=F[o]['name'], adj=ADJ[o], desc=f'start_pos_factions_description_{o}', prefix=o.upper() + '_',
                      blurb=f"{F[o]['name']} ({wave_of(cap).upper()} faction).", capital=cap, colours=(F[o]['colour_primary'], F[o]['colour_secondary']))
    return out


def db_tables(sp_, built, facs):
    """regions + campaign_map_settlements rows per region (data.pack tables), faction tables via land_probe_b.db_tables
    (its trio / palette left out) with factions.json colours."""
    with tempfile.TemporaryDirectory() as t:
        for pat in (REG_T, SET_T):
            assert packtool.extract(geo.GAME + '/data.pack', t, pat) == 1, pat
        reg, st = dbtable.load(os.path.join(t, REG_T)), dbtable.load(os.path.join(t, SET_T))
        out, added = {}, {}
        if facs:
            saved = lpb.REGIONS, lpb.new_factions
            try:
                lpb.REGIONS, lpb.new_factions = [], lambda v: list(facs.items())
                out, added = lpb.db_tables(os.path.join(t, 'db'), 'w1')
            finally:
                lpb.REGIONS, lpb.new_factions = saved
            del out[REG_T], out[SET_T]
            rel = 'db/factions_tables/factions'              # own flag set (republican_flag_path stays empty)
            tb = dbtable.parse(out[rel], 'factions')
            names = [f for f, _ in dbtable.fields_for('factions', tb['version'])]
            fi = names.index('flags_path')
            for r in tb['rows']:
                if r[0] in facs:
                    assert r[fi] == OLD_FLAG, r[fi]
                    r[fi] = flag_path(r[0])
                    for c, v in fac_db_colours(facs[r[0]]).items():   # the minimap reads these (oldenburg's 113,10,10 before)
                        r[names.index(c)] = v
            out[rel] = dbtable.build(tb)
            for n, col in (('warscape_rigid', 0), ('warscape_rigid_lod', 3)):   # data.pack already has agent_ID_united_states
                rel = f'db/{n}_tables/{n}'
                van = dbtable.load(os.path.join(t, rel)) if packtool.extract(geo.GAME + '/data.pack', t, rel) == 1 else None
                tb = dbtable.parse(out[rel], n)
                vk = {r[col] for r in van['rows']}
                nv = len(van['rows'])
                drop = [r for r in tb['rows'][nv:] if r[col] in vk]
                assert tb['rows'][:nv] == van['rows']
                tb['rows'] = tb['rows'][:nv] + [r for r in tb['rows'][nv:] if r[col] not in vk]
                out[rel] = dbtable.build(tb)
                added[n + ' (vanilla row kept)'] = [r[col] for r in drop]
    used = {tuple(x[2:5]) for x in reg['rows']}
    for s in sp_:
        if s['key'] not in built:
            continue
        assert tuple(s['rgb']) not in used | {lookup_tga.SEA, lookup_tga.BLACK, lookup_tga.WHITE} and s['key'] not in {x[0] for x in reg['rows']}
        used.add(tuple(s['rgb']))
        reg['rows'].append([s['key'], 'cont_europe', *s['rgb'], s['name']])
        st['rows'].append([f"settlement:{s['key']}:{s['town']}", s['key'], s['town_name'], 1, 'settlement'])
    out[REG_T], out[SET_T] = dbtable.build(reg), dbtable.build(st)
    return out, added


def fac_rgb9(d):
    """FACTION_FLAG_AND_COLOURS colours of a new faction: primary, secondary, primary (factions.json has two)."""
    return [*d['colours'][0], *d['colours'][1], *d['colours'][0]]


def fac_db_colours(d):
    """factions table colour columns of a new faction = the FACTION_FLAG_AND_COLOURS trios, alt_* = the same
    (britain: primary 222,0,0 = trio 1, secondary = trio 2, uniform = trio 3)."""
    c = fac_rgb9(d)
    return {f'{alt}{n}_colour_{ch}': float(c[3 * t + i]) for t, n in enumerate(('primary', 'secondary', 'uniform'))
            for alt in ('', 'alt_') for i, ch in enumerate('rgb')}


def faction_colours(path, facs):
    tb = dbtable.load(path)
    for r in tb['rows']:
        if r[0] in facs:
            (r[1], r[2], r[3]), (r[4], r[5], r[6]) = facs[r[0]]['colours']
    open(path, 'wb').write(dbtable.build(tb))


def lookup(rpath, table, keys, place, dummies=(), parent=None, area=None):
    """lookup_tga.build, then a new region left without a pixel of its colour (all its pixels are outline at 605x300:
    the small islands) gets its outline-free pixels back, or at least the pixel under its settlement.  The palette
    holds PALETTE colours (G4a: the engine reads the palette; regions loader 0xA43400 maps a region's rgb to a palette
    index or -1, and handles -1).  parent {child: region}: minimap_parent children are painted in the parent's colour
    (no entry of their own).  Past the palette, regions go black (= no region, no minimap colour): dummies (stress
    keys, last first), then real regions smallest area first.  -> (tga bytes, repaired pixels, regions without a colour)."""
    e = esf.load(rpath)
    col = lookup_tga.colours(table)
    parent, dummies = parent or {}, list(dummies)
    own = [k for k in keys if k not in parent and k not in set(dummies)]
    order = sorted(own, key=lambda k: -area[k]) + dummies
    col0 = {**col, **{k: lookup_tga.BLACK for k in keys}}
    has0 = {tuple(c) for c in lookup_tga.render(e, col0, lookup_tga.WORLD_BOX).reshape(-1, 3).tolist()} - {lookup_tga.BLACK}
    nocol = order[max(0, PALETTE - len(has0)):]
    col.update({k: lookup_tga.BLACK for k in nocol})
    col.update({k: col[p] for k, p in parent.items()})
    rgb = lookup_tga.render(e, col, lookup_tga.WORLD_BOX)
    has = {tuple(c) for c in rgb.reshape(-1, 3).tolist()}
    miss = [k for k in keys if col[k] not in has and k not in nocol and k not in parent]
    fixed = {}
    if miss:
        flat = lookup_tga.render(e, col, lookup_tga.WORLD_BOX, border=False)
        x0, yt, sx, sy = lookup_tga.WORLD_BOX
        for k in miss:
            m = (flat == col[k]).all(2)
            if not m.any():
                px, py = place[k]['pos']
                m[int((yt - py) / sy), int((px - x0) / sx)] = True
            rgb[m] = col[k]
            fixed[k] = int(m.sum())
    return lookup_tga.tga_bytes(*lookup_tga.palettise(rgb)), fixed, nocol


def loc_rows(sp_, built, facs):
    import world_build
    rows = world_build.loc_rows()
    for s in sp_:
        if s['key'] not in built:
            continue
        k, t = s['key'], s['town']
        rows += [('regions_onscreen_' + k, s['name'], 0), ('regions_battle_name_' + k, s['name'], 0),
                 (f"start_pos_settlements_onscreen_name_settlement:{k}:{t}{s['loc_suffix']}", s['town_name'], 0),
                 (f'start_pos_regions_rebel_faction_name_{k}mp_eur_napoleon', s['rebel'], 0)]
    for key, d in facs.items():
        rows += [(f'factions_screen_name_{key}', d['name'], 0), (f'factions_screen_adjective_{key}', d['adj'], 0),
                 (f'factions_attack_desc_{key}', lpb.attack_desc(d['adj']), 0),
                 (f'factions_defend_desc_{key}', f"You are defending against a force of {d['adj']} attackers.", 0),
                 (d['desc'], d['blurb'], 0), (f'names_royalty_name_{key}Wilhelm', 'Wilhelm', 0)]
    return rows


# ---------------------------------------------------------------- stage cache (--reuse)
# Two entries, each keyed on (args, code, python / numpy / shapely versions) and validated against every input file the
# stage read when it was stored (content sha256, or size + mtime for files > 256 MB; directory listings and existence
# tests too):
#   geometry  geometry()'s result (carve + pathfinding + settlements, ~15 min): regions.esf / pathfinding.esf as bytes,
#             the rest pickled.  Its code = geometry() and everything it can reach in tools/.
#   pre       the output dir as build() leaves it before stage 'p' (zip).  Code = build_pre() and its reach.
# The code key is the bytecode of every tools/ function reachable by name from the stage's root function (globals, module
# attributes, class methods, closures, lazy imports), plus the value of every global they name: editing carve() or a
# helper it calls misses; editing add_ports(), cai_regions() or check() does not miss `geometry` (cai_regions misses
# `pre`).  Not covered: a function reached only through getattr / a string name, data read without open() (np.fromfile),
# files written by an earlier stage and read here (they are inputs and are hashed).  Anything doubtful: delete CACHE_DIR.
CACHE_DIR = os.path.join(ROOT, 'work/cache/stages')
CACHE_KEEP = 1                    # entries kept per stage and variant; the older ones are deleted when a new one is stored
TOOLS = os.path.dirname(os.path.abspath(__file__))


def _mine(mod):
    f = getattr(mod, '__file__', None)
    return bool(f) and os.path.dirname(os.path.abspath(f)) == TOOLS


def _uses(co):
    """-> (global names read, (module, attr) pairs read as MODULE.attr).  Lazy `import m` / `from m import a` inside the code
    count as module reads; a local alias of a lazily imported module is followed."""
    gl, pairs, alias, prev, last = set(), set(), {}, None, None
    todo = [co]
    while todo:
        c = todo.pop()
        todo += [k for k in c.co_consts if isinstance(k, types.CodeType)]
        for i in dis.get_instructions(c):
            op = i.opname
            if op in ('LOAD_GLOBAL', 'LOAD_NAME'):
                gl.add(i.argval)
            elif op == 'IMPORT_NAME':
                last = i.argval
            elif op in ('STORE_FAST', 'STORE_DEREF', 'STORE_NAME', 'STORE_GLOBAL') and prev is not None and prev.opname == 'IMPORT_NAME':
                alias[i.argval] = last
            elif op == 'IMPORT_FROM':
                pairs.add((last, i.argval))
            elif op == 'LOAD_ATTR' and prev is not None:
                if prev.opname in ('LOAD_GLOBAL', 'LOAD_NAME'):
                    pairs.add((prev.argval, i.argval))
                elif prev.opname.startswith('LOAD_FAST') or prev.opname == 'LOAD_DEREF':
                    for v in {prev.argval} if isinstance(prev.argval, str) else prev.argval:
                        if v in alias:
                            pairs.add((alias[v], i.argval))
            prev = i
    return gl, pairs


def _const_repr(c):
    if isinstance(c, types.CodeType):
        return _code_repr(c)
    if isinstance(c, (tuple, list)):
        return repr([_const_repr(x) for x in c])
    if isinstance(c, (set, frozenset)):                  # iteration order follows PYTHONHASHSEED
        return repr(sorted(_const_repr(x) for x in c))
    return repr(c)


def _code_repr(co):
    return repr((co.co_name, co.co_code, co.co_names, co.co_varnames, co.co_freevars, co.co_flags,
                 [_const_repr(c) for c in co.co_consts]))


def code_digest(*roots):
    """sha256 over the bytecode of the tools/ functions reachable from roots and the values of the globals they name."""
    items, seen, todo, live = {}, set(), list(roots), set()

    def value(v, name):                                   # a global's value: hashed, functions in it reached
        if isinstance(v, (types.FunctionType, type, types.ModuleType)):
            if id(v) not in seen:
                seen.add(id(v)); todo.append(v)
            return None
        if id(v) in live:                                 # a cycle
            return repr(type(v))
        live.add(id(v))
        try:
            return value_(v, name)
        finally:
            live.discard(id(v))

    def value_(v, name):
        if isinstance(v, (bool, int, float, complex, str, bytes, type(None))):
            return repr(v)
        if isinstance(v, (list, tuple)):
            return repr([value(x, name) for x in v])
        if isinstance(v, (set, frozenset)):
            return repr(sorted(repr(value(x, name)) for x in v))
        if isinstance(v, dict):
            return repr([(repr(value(k, name)), value(x, name)) for k, x in v.items()])
        if isinstance(v, np.ndarray):
            return hashlib.sha256(v.tobytes()).hexdigest() + repr((v.dtype, v.shape))
        if isinstance(v, shapely.geometry.base.BaseGeometry):
            return v.wkb_hex
        if isinstance(v, (struct.Struct, re.Pattern)):
            return repr((type(v), getattr(v, 'format', None) or v.pattern))
        r = repr(v)
        return repr(type(v)) if ' at 0x' in r else r

    def reach(f):
        mod = sys.modules.get(f.__module__)              # None under runpy: judge by the code's file instead
        mine = _mine(mod) if mod is not None else os.path.dirname(os.path.abspath(f.__code__.co_filename)) == TOOLS
        if not mine or f.__code__.co_filename.startswith('<'):       # dataclass & co. generated methods: '<string>'
            for c in f.__closure__ or ():                  # a wrapper (decorator, profiler): reach what it wraps
                try:
                    if isinstance(c.cell_contents, types.FunctionType):
                        value(c.cell_contents, f.__qualname__)
                except ValueError:
                    pass
            return
        co, g = f.__code__, f.__globals__
        h = _code_repr(co) + repr(value(f.__defaults__ or (), f.__qualname__)) + repr(value(f.__kwdefaults__ or {}, f.__qualname__))
        for c in f.__closure__ or ():
            try:
                h += repr(value(c.cell_contents, f.__qualname__))
            except ValueError:
                pass
        items[f'{f.__module__}.{f.__qualname__}'] = h
        gl, pairs = _uses(co)
        for n in sorted(gl):
            if n in g and not isinstance(g[n], types.ModuleType):
                r = value(g[n], n)
                if r is not None:
                    items[f'{f.__module__}:{n}'] = r
        for mn, a in sorted(pairs, key=repr):
            m = g.get(mn) if mn in g else sys.modules.get(mn)
            if isinstance(m, types.ModuleType) and _mine(m) and hasattr(m, a):
                r = value(getattr(m, a), a)
                if r is not None:
                    items[f'{m.__name__}.{a}'] = r

    while todo:
        o = todo.pop()
        if isinstance(o, types.FunctionType):
            reach(o)
        elif isinstance(o, type) and _mine(sys.modules.get(o.__module__)):
            for k, x in vars(o).items():
                if isinstance(x, (staticmethod, classmethod)):
                    x = x.__func__
                elif isinstance(x, property):
                    x = x.fget
                if isinstance(x, types.FunctionType):
                    todo.append(x)
                elif not k.startswith('__') or k == '__annotations__':
                    items[f'{o.__module__}.{o.__qualname__}.{k}'] = repr(value(x, k))
            for f in getattr(o, '__dataclass_fields__', {}).values():
                items[f'{o.__module__}.{o.__qualname__}.field.{f.name}'] = repr((f.type, *('MISSING' if x is dataclasses.MISSING else _code_repr(x.__code__) if isinstance(x, types.FunctionType) else x
                                                        for x in (f.default, f.default_factory))))
    return hashlib.sha256(repr(sorted(items.items())).encode()).hexdigest()


_NOT_INPUTS = (os.path.abspath(tempfile.gettempdir()) + os.sep, os.path.abspath(CACHE_DIR) + os.sep)


class Inputs:
    """What a stage read: open() for reading, os.path.exists / isfile / isdir, os.listdir.  skip: dirs the stage writes.  -> deps list."""
    def __init__(self, skip=()):
        self.seen, self.saved, self.skip = {}, {}, tuple(os.path.abspath(x) + os.sep for x in skip)

    ACTIVE = []                   # the Inputs being recorded (stages nest: pre > geometry)

    def __enter__(self):
        t = self
        Inputs.ACTIVE.append(self)
        real_open, real_exists, real_isfile, real_isdir, real_listdir = io.open, os.path.exists, os.path.isfile, os.path.isdir, os.listdir

        def op(file, mode='r', *a, **k):
            if isinstance(file, (str, bytes, os.PathLike)) and not set(str(mode)) & set('wax+'):
                t.add('file', os.fsdecode(file))
            return real_open(file, mode, *a, **k)

        def test(kind, f):
            def g(p):
                r = f(p)
                t.add(kind, os.fsdecode(p), r)
                return r
            return g
        self.saved = dict(open=builtins.open, iopen=io.open, exists=os.path.exists, isfile=os.path.isfile, isdir=os.path.isdir,
                          listdir=os.listdir)
        builtins.open = io.open = op
        os.path.exists, os.path.isfile, os.path.isdir = test('exists', real_exists), test('isfile', real_isfile), test('isdir', real_isdir)

        def ld(p='.'):
            r = real_listdir(p)
            t.add('listdir', os.fsdecode(p), sorted(r))
            return r
        os.listdir = ld
        return self

    def __exit__(self, *x):
        Inputs.ACTIVE.remove(self)
        s = self.saved
        builtins.open, io.open, os.path.exists, os.path.isfile, os.path.isdir, os.listdir = (
            s['open'], s['iopen'], s['exists'], s['isfile'], s['isdir'], s['listdir'])

    def add(self, kind, path, result=None):
        path = os.path.abspath(path)
        if path.startswith(self.skip) or (path + os.sep).startswith(self.skip):   # the stage's own products
            return
        if (kind, path) in self.seen or path.startswith(_NOT_INPUTS):     # tmp / cache dirs: the stages' own scratch
            return
        self.seen[(kind, path)] = None                         # placeholder: probe() opens the file itself
        self.seen[(kind, path)] = probe(kind, path) if kind == 'file' else result    # state at first sight, not at store()

    @staticmethod
    def adopt(deps):
        """A stage restored from the cache read these: every recording stage depends on them too."""
        for i in Inputs.ACTIVE:
            for k, p, v in deps: i.seen.setdefault((k, p), v)

    def deps(self):
        return [[k, p, self.seen[(k, p)]] for (k, p) in sorted(self.seen)]


def probe(kind, path):
    """The current state of one dependency, as a JSON-able value."""
    if kind == 'file':
        try:
            st = os.stat(path)
        except OSError:
            return None
        if st.st_size > 256 << 20:
            return ['stat', st.st_size, st.st_mtime_ns]
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for c in iter(lambda: f.read(1 << 22), b''):
                h.update(c)
        return h.hexdigest()
    if kind == 'exists':
        return os.path.exists(path)
    if kind == 'isfile':
        return os.path.isfile(path)
    if kind == 'isdir':
        return os.path.isdir(path)
    return sorted(os.listdir(path)) if os.path.isdir(path) else None


def _probe_quiet(kind, path):
    return json.loads(json.dumps(probe(kind, path)))


class Stage:
    """One cache family: entries CACHE_DIR/<name>/<family>/<key>/ (meta.json + payload files)."""
    def __init__(self, name, family, args, *roots):
        self.name, self.dir = name, os.path.join(CACHE_DIR, name, family)
        import scipy, PIL
        env = [platform.python_version(), np.__version__, shapely.__version__, shapely.geos_version_string, scipy.__version__, PIL.__version__]
        self.key = hashlib.sha256(json.dumps([name, args, env, code_digest(*roots)], default=str).encode()).hexdigest()[:24]
        self.path = os.path.join(self.dir, self.key)

    def hit(self):
        """meta of the stored entry when every recorded input still reads the same, else None."""
        try:
            meta = json.load(open(os.path.join(self.path, 'meta.json')))
        except OSError:
            return None
        for kind, path, want in meta['deps']:
            if _probe_quiet(kind, path) != want:
                print(f'  reuse {self.name}: input changed ({kind} {path})', flush=True)
                return None
        return meta

    def store(self, deps, writer, **meta):
        tmp = self.path + '.tmp'
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        writer(tmp)
        json.dump(dict(meta, deps=deps, stored=time.time()), open(os.path.join(tmp, 'meta.json'), 'w'))
        shutil.rmtree(self.path, ignore_errors=True)
        os.rename(tmp, self.path)
        old = sorted((d for d in os.listdir(self.dir) if d != self.key and not d.endswith('.tmp')),
                     key=lambda d: os.path.getmtime(os.path.join(self.dir, d)), reverse=True)
        for d in old[CACHE_KEEP - 1:]:
            shutil.rmtree(os.path.join(self.dir, d), ignore_errors=True)


def _plain_geometry(o, path='state'):
    """Pickle keeps geometry as WKB, which drops a fixed precision model: refuse to cache any geometry that has one."""
    if isinstance(o, shapely.geometry.base.BaseGeometry):
        assert shapely.get_precision(o) == 0, ('cached geometry with a precision model', path)
    elif isinstance(o, dict):
        for k, v in o.items():
            _plain_geometry(v, f'{path}[{k!r}]')
    elif isinstance(o, (list, tuple, set)):
        for i, v in enumerate(o):
            _plain_geometry(v, f'{path}[{i}]')


def geometry_cached(sp_, stress, weld, reuse):
    if not reuse:
        return geometry(sp_, stress, weld)
    st = Stage('geometry', f"{len(sp_)}-{hashlib.sha256(json.dumps(sp_, default=str).encode()).hexdigest()[:12]}-{stress}-{int(weld)}",
               [sp_, stress, weld], geometry)
    meta = st.hit()
    if meta:
        t0 = time.time()
        z = lambda n: zlib.decompress(open(os.path.join(st.path, n), 'rb').read())
        e = esf.loads(z('regions.z'))
        m = pm.PathfindingModel.decode(esf.loads(z('pf.z')))
        state = pickle.loads(z('state.z'))
        sp_[:] = state.pop('sp_')
        collapse.fixes = state.pop('fixes')
        Inputs.adopt(meta['deps'])
        print(f'  reuse geometry: {st.key} ({time.time() - t0:.0f}s)', flush=True)
        return (e, state['info'], m, state['single'], state['pinfo'], state['place'], state['deferred'], state['skipped'])
    with Inputs() as inp:
        r = geometry(sp_, stress, weld)
    e, info, m, single, pinfo, place, deferred, skipped = r
    state = dict(info=info, single=single, pinfo=pinfo, place=place, deferred=deferred, skipped=skipped, sp_=list(sp_),
                 fixes=getattr(collapse, 'fixes', 0))
    _plain_geometry(state)

    def write(d):
        w = lambda n, b: open(os.path.join(d, n), 'wb').write(zlib.compress(b, 1))
        w('regions.z', esf.dumps(e)); w('pf.z', m.encode()); w('state.z', pickle.dumps(state, 5))
    st.store(inp.deps(), write, stage='geometry')
    print(f'  reuse geometry: stored {st.key}', flush=True)
    return r


# ---------------------------------------------------------------- build
def geometry(sp_, stress=0, weld=False):
    """carve -> pathfinding -> settlements, a region that fails any step deferred and everything redone.  stress = N:
    then the first dummies of stress_pool not deferred, as many as make N land regions, carved out of STRESS_FILLER
    after the real ones (sp_ extended in place).  weld: stage 'j' (WELD)."""
    deferred = {}
    real = list(sp_)
    while True:
        am = [s for s in real if is_america(s['key'])]
        ea = [s for s in real if not is_america(s['key']) and 'split_of' not in s]
        feats = features(am, deferred) if am else {}
        if ea:
            ek = {s['key'] for s in ea}                 # America's own pieces win (the east window clips them at AMERICA_X)
            feats.update({k: v for k, v in features(ea, deferred, east=True).items() if k not in feats or k in ek})
        e = esf.load(ZREGIONS)
        gap, wgeom = vanilla_gap(e, feats, [s['key'] for s in real], WELD if weld else None) if ea else (None, None)
        take, skipped = pieces(e, [s for s in real if 'split_of' not in s], feats, deferred)
        sub, cstats = {}, {}
        if ea:
            sub, lab, cstats = corridors(feats, [s for s in ea if s['key'] in take])
            feats.update(lab)
        llab, lstats = lake_cut(feats, [s for s in real if s['key'] in take], sub)
        feats.update(llab)
        split_pieces(e, real, feats, take, deferred)
        dum = []
        if stress:
            kinds = [it[1].value for it in e.root.find('region_data').find('regions').items]
            need = stress - kinds.count('land') - sum(s['key'] in take for s in real)
            dum = [d for d in stress_pool(e, len(real)) if d['key'] not in deferred][:need]
            assert len(dum) == need >= 0, ('stress: not enough dummy squares', need, len(dum))
        try:
            info = carve(e, real, feats, take, sub, weld)
            if cstats:
                info['corridors'] = cstats
            if lstats:
                info['lakes'] = lstats
            if gap:
                info['vanilla_gap'] = gap
            if wgeom:
                info['weld'] = {k: list(vs) for k, vs in gap['welded'].items() if k in info['keys']}
                info['weld_geom'] = wgeom
            if dum:
                fi = [it[0].value for it in e.root.find('region_data').find('regions').items].index(STRESS_FILLER)
                i2 = carve(e, dum, {d['key']: d['poly'] for d in dum}, {d['key']: [(fi, d['area'])] for d in dum})
                assert i2['first_index'] == info['first_index'] + len(info['keys']) and i2['keys'] == [d['key'] for d in dum]
                info['keys'] += i2['keys']
                if 'pass_polys' in info:
                    info['pass_polys'].update(i2['polys'])
                info['polys'].update(i2.pop('polys'))
                info['stress_carve'] = i2
                stress_pass_groups(e, dum, i2)
            sp_[:] = real + dum
            precheck(e, info, sp_)
            _F.clear()                                  # attempts are over unless the pathfinding defers one (then recomputed)
            m, Ls, single, pinfo = pathfinding(ZPF, info)
            place = place_settlements(e, sp_, info, single)
        except Retry as x:
            print('  deferred', x.args, flush=True)
            deferred[x.args[0]] = x.args[1]
            continue
        return e, info, m, single, pinfo, place, deferred, skipped


def build_pre(variant, stages, compact, stress, out, reuse=False):
    """Everything up to build_info.json, i.e. the output dir as stage p finds it."""
    ov = os.path.join(out, 'overlay')
    os.makedirs(os.path.join(ov, MAPDIR))
    sp_ = specs(variant, compact)
    e, info, m, single, pinfo, place, deferred, skipped = geometry_cached(sp_, stress, 'j' in stages, reuse)
    by = {s['key']: s for s in sp_}
    keys = info['keys']
    dummies = [k for k in keys if 'poly' in by[k]]
    regions_finish(e, sp_, info, place)
    moved = split_slots(e, info)
    rpath = os.path.join(ov, MAPDIR, 'regions.esf')
    open(rpath, 'wb').write(esf.dumps(e))
    info['border_splines'] = border_splines(e, ov, info['first_index'])
    assert len(m.areas[0].polygon_words) < PF_WORDS_MAX, ('pathfinding polygon words past 2^21', len(m.areas[0].polygon_words))
    open(os.path.join(ov, MAPDIR, 'pathfinding.esf'), 'wb').write(m.encode())
    pz, stray = zones_poi(rpath, keys)
    pb, nodes, nbs = poi(pz, e, info, place, single)
    open(os.path.join(ov, MAPDIR, 'poi.esf'), 'wb').write(pb)
    open(os.path.join(ov, MAPDIR, 'sea_grids.esf'), 'wb').write(wz.sea_grid_zones(rpath, pz))   # sea nodes only
    te = esf.load(SRC + '/trade_routes.esf')
    tr = cm.read_trade_routes(te)
    te = esf.load(SRC + '/trade_routes.esf')
    for k in keys:
        te.root.find('SETTLEMENTS').items.append([Val(0x0e, k)])
    troutes = land_trade_routes(e, info, place, len(tr.ports) + len(tr.settlements),
                                {k: len(tr.ports) + i for i, k in enumerate(tr.settlements)})
    lpb.add_trade_routes(te.root.find('ROUTES').items, troutes)
    split_trade(te.root.find('ROUTES').items, tr, moved, keys, place)
    open(os.path.join(ov, MAPDIR, 'trade_routes.esf'), 'wb').write(esf.dumps(te))
    facs = {} if variant.endswith('a') else new_factions(sp_, keys)
    tables, added = db_tables(sp_, keys, facs)
    for rel, data in tables.items():
        os.makedirs(os.path.dirname(os.path.join(ov, rel)), exist_ok=True)
        open(os.path.join(ov, rel), 'wb').write(data)
    if facs:
        faction_colours(os.path.join(ov, COL_T), facs)
    mparent = {k: by[k]['minimap_parent'] for k in keys if by[k].get('minimap_parent')}
    tga, lfix, nocol = lookup(rpath, os.path.join(ov, REG_T), keys, place, dummies, mparent,
                              {k: info['polys'][k].area for k in keys if k not in dummies})
    open(os.path.join(ov, MAPDIR, 'europe_lookup.tga'), 'wb').write(tga)
    rows = loc_rows(sp_, keys, facs)
    open(os.path.join(out, 'loc_rows.tsv'), 'w', encoding='utf-8', newline='').write(loc.to_tsv(rows))
    # ---- startpos
    sp = esf.load(ZSP)
    vown = sorted({by[k]['owner'] for k in keys} - set(facs))
    oinfo = owner_info(sp, vown + ([lp.OWNER] if lp.OWNER not in vown else []), e, m.areas[0].grid)
    sinfo = startpos_regions(sp, sp_, info, place, pinfo, len(tr.ports), len(tr.settlements))
    lpb.add_trade_routes(next(cm._iter_recs(sp.root, 'CAMPAIGN_TRADE_MANAGER')).find('TRADE_ROUTES').items, troutes)
    rerouted = split_trade(next(cm._iter_recs(sp.root, 'CAMPAIGN_TRADE_MANAGER')).find('TRADE_ROUTES').items, tr, moved, keys, place)
    handed = {k: hand_over(sp, k, sinfo[k]['handles']['region'], by[k]['owner'], oinfo[by[k]['owner']])
              for k in keys if by[k]['owner'] in vown and by[k]['owner'] != lp.OWNER}
    own = {k: by[k]['owner'] for k in keys}
    fac = {}
    for key, d in facs.items():
        ks = sorted((k for k in keys if own[k] == key), key=lambda k: k != d['capital'])
        info_, ghm, fresh = lpb.faction_new(sp, key, d['name'], d['desc'], [(k, sinfo[k]['handles']['region']) for k in ks],
                                            place[ks[0]]['pos'])
        fac[key] = dict(info_, fresh_handles=fresh, regions=ks, hm=ghm)
    for it in next(cm._iter_recs(sp.root, 'FACTION_ARRAY')).items:  # FACTION_FLAG_AND_COLOURS paths -> its gn_ set
        if lpb.fkey(it[0]) in facs:
            hit = []

            def fx(kids, j, v, k=lpb.fkey(it[0])):
                if v.tag in (0x0e, 0x0f) and v.value == OLD_FLAG:
                    kids[j] = Val(v.tag, flag_path(k)); hit.append(j)
                    # then 3 u8 rgb trios: the campaign / minimap faction colour (oldenburg's 113,10,10 painted every new
                    # faction brown-red); vanilla's third trio is a shade of the first (britain 192,22,16)
                    assert [x.tag for x in kids[j + 1:j + 10]] == [0x06] * 9, kids[j + 1:j + 10]
                    kids[j + 1:j + 10] = [Val(0x06, int(c)) for c in fac_rgb9(facs[k])]
            lp.walk_vals(it[0], fx)
            assert len(hit) == 2, hit
    domain_flags(sp, pinfo, {k: 0 if own[k] in facs else oinfo[own[k]]['flag'] for k in keys},
                 {k: pinfo['vanilla_domains'][d['of']] for k, d in info.get('split', {}).items()})
    lpb.append_composites(sp, pinfo, sinfo[keys[0]]['domain_array_value'])
    hm = {k: {sinfo[k]['template_handles'][n]: h for n, h in sinfo[k]['handles'].items()} for k in keys}
    weld = {frozenset((v, k)) for k, vs in info.get('weld', {}).items() for v in vs} if 'j' in stages else set()
    weld |= {frozenset(p_) for p_ in split_pairs(e, keys)}     # split_ring: land boundaries to the old region and its neighbours
    cai = cai_regions(sp, e, keys, own, hm, fac, stages, oinfo, east=bool(dummies) or east_carved(info), weld=weld)
    split = split_startpos(sp, e, moved)
    for k, v in split.items():
        v.update(moved[k], trade_routes_repointed=rerouted)
    for v in fac.values():
        v.pop('hm')
    fk = {lpb.fkey(x[0]) for x in next(cm._iter_recs(sp.root, 'FACTION_ARRAY')).items}
    prot = protectorates.apply(sp, [pc for pc in protectorates.PAIRS if set(pc) <= fk])
    rel = religion.apply(sp, *religion.targets(keys))     # new factions / regions: own religion, not the templates'
    gov = religion.government(sp)                        # gov_republic for the United States
    caches = cf.fix_caches(sp)                           # CAI caches by the row type, or saves stop loading (research/18)
    open(os.path.join(out, 'startpos.esf'), 'wb').write(esf.dumps(sp))
    cm._FIRST.clear()                                    # first_rec holds the sp tree
    nreg = len(e.root.find('region_data').find('regions').items)
    bi = dict(variant=variant, stages=stages, compact=compact, base=dict(regions=ZREGIONS, pathfinding=ZPF, startpos=ZSP),
              regions=keys, region_count=nreg, region_ceiling=REGION_CEILING, border_splines=info['border_splines'],
              owner=own, data_owner={k: by[k]['data_owner'] for k in keys}, owner_info=oinfo, handed_over=handed,
              region_indices={k: info['first_index'] + n for n, k in enumerate(keys)},
              excluded=excluded(variant), deferred=deferred, skipped_pieces=skipped,
              ports_deferred=None if 'p' in stages else "no PORT / port slots without stage 'p'",
              flags='new factions: own flag set data\\ui\\flags\\gn_<key> (flags.py, factions flags_path + startpos '
                    'FACTION_FLAG_AND_COLOURS); icons / uniforms oldenburg\'s',
              cai_faction_regions='vanilla owners\' CAI_FACTION body[0] region lists not extended (b1 recipe)',
              carve={k: v for k, v in info.items() if k not in ('polys', 'pass_polys', 'weld_geom', 'split_polys')},
              area_u2={k: round(p.area, 1) for k, p in info['polys'].items()},
              settlements={k: dict(v, town=by[k]['town_name'], lonlat=tuple(round(float(x), 3) for x in proj.to_lonlat(*v['pos'])))
                           for k, v in place.items()},
              pathfinding=pinfo, poi_nodes=[(n.id, n.kind, n.region, n.area, n.wx, n.wy) for n in nodes], poi_neighbours=nbs,
              startpos={k: dict(handles=v['handles'], trade=v.get('trade')) for k, v in sinfo.items()},
              land_trade_routes=troutes, cai=cai, cai_caches_fixed=caches, faction=fac or None, protectorates=prot, religion=rel, government=gov,
              faction_skipped=lpb.FACTION_SKIPPED_B3 if fac else None, db_rows_added=added,
              collapse_fixes=getattr(collapse, 'fixes', 0), poi_stray_sea_nodes_dropped=stray,
              poi_vanilla_nodes_extended=getattr(poi, 'vanilla_nodes_extended', 0),
              lookup_outline_only_regions_repainted=lfix)
    bi.update({k: v for k, v in (('minimap_parent', mparent), ('lookup_no_colour', [k for k in nocol if k not in dummies]),
                                 ('split', split)) if v})
    if stress:
        kinds = [it[1].value for it in e.root.find('region_data').find('regions').items]
        bi['stress'] = dict(land=stress, dummies=dummies, owner=STRESS_OWNER, filler=STRESS_FILLER, no_lookup_colour=nocol,
                            regions_esf=dict(collections.Counter(kinds), total=len(kinds)))
    json.dump(bi, open(os.path.join(out, 'build_info.json'), 'w'), indent=1, default=str)
    return {k: bi[k] for k in ('variant', 'stages', 'region_count', 'deferred', 'owner')}


def _zip_dir(zpath, d):
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for r, _, fs in os.walk(d):
            for f in sorted(fs):
                z.write(os.path.join(r, f), os.path.relpath(os.path.join(r, f), d))


def restore(st, meta, out):
    t0 = time.time()
    shutil.rmtree(out, ignore_errors=True)
    with zipfile.ZipFile(os.path.join(st.path, 'out.zip')) as z:
        z.extractall(out)
    Inputs.adopt(meta['deps'])
    print(f'  reuse {st.name}: {st.key} ({time.time() - t0:.0f}s)', flush=True)


def snapshot(st, out, run):
    """run() leaves `out`; with a Stage the dir is restored from / stored as a zip when the stage's key and inputs match."""
    meta = st and st.hit()
    if meta:
        restore(st, meta, out)
        return meta['short']
    with Inputs(skip=(out,)) as inp:
        short = run()
    if st:
        st.store(inp.deps(), lambda d: _zip_dir(os.path.join(d, 'out.zip'), out), stage=st.name, short=short)
        print(f'  reuse {st.name}: stored {st.key}', flush=True)
    return short


def build(variant='w1a', stages=STAGES, compact=False, stress=0, reuse=False):
    out = out_dir(variant, stages, compact, stress)
    if os.path.exists(out):
        shutil.rmtree(out)
    pre = ports = None
    if reuse:                                            # every key before anything runs (the build patches some module globals)
        args = [variant, stages, compact, stress]
        fam = '-'.join(map(str, args))
        pre = Stage('pre', fam, args, build_pre)
        if 'p' in stages:
            import port_probe
            ports = Stage('ports', fam, [args, pre.key], port_probe.add_ports)
            om = pre.hit() and ports.hit()               # both stored and valid: restore the final dir only
            if om:
                restore(ports, om, out)
                print(json.dumps(json.load(open(os.path.join(pre.path, 'meta.json')))['short'], indent=1, default=str))
                return out
    short = snapshot(pre, out, lambda: build_pre(variant, stages, compact, stress, out, reuse))
    if 'p' in stages:                                    # stage p: a port for every new region with a regions.json port
        import port_probe
        snapshot(ports, out, lambda: port_probe.add_ports(out))
    print(json.dumps(short, indent=1, default=str))
    return out


MS, OCC = 'CAI_REGION_MILITARY_STRENGTH', 'CAI_REGION_OCCUPANCY_ANALYSIS'


def sea_beliefs(sp, R, rid, new_id, first, stages, template='eur_norwegian_sea'):
    """Stage 's': wz.region_beliefs (zones stage h) for the wld seas wz.NV..first-1 only (a view on R without the new
    land, which land_beliefs covers).  Stage 'm': the template's 7 military strengths + occupancy analysis per wld sea, cloned the
    land_beliefs way (cai_faction.clone_beliefs: owned by the template's manager under the sea's key, faction list
    emptied, subjects / referenced-by = the sea, its sibling clones and the theatre strengths) + the sea's owner links."""
    assert not ('s' in stages and 'm' in stages), stages
    if 's' in stages:
        rep = {}
        wz.region_beliefs(sp, type('RegionsView', (), {'items': R.items[:first]})(), rid[:first], new_id, rep, template)
        return dict(stage='s', seas=first - wz.NV, report=rep['region_beliefs'])
    if 'm' not in stages:
        return None
    by, parent = cf.cai_index(sp)
    names = [it[-1].children[10].value for it in R.items]
    TR = R.items[names.index(template)]
    T = TR[2].value
    # the MS beliefs' subject is the region's occupancy analysis (template: [7951]); without it the managers never index
    # them (w1a_m with MS only crashed as before), so clone the pair the land recipe clones too
    ana = [a for a in cf.keyed_analysers(by, ({T},), (T,)) if [cf.cai_kind(by, b) for _, b in a[4]] in ([MS], [OCC])]
    assert sorted(cf.cai_kind(by, a[4][0][1]) for a in ana) == [MS] * 7 + [OCC], len(ana)
    tids = cf.check_owners(by, ana)
    pairs = lambda a: list(zip(a[0::2], a[1::2]))
    for i in range(wz.NV, first):
        N = rid[i]
        assert not R.items[i][-1].children[2].value and not R.items[i][1 + 9].array(), names[i]
        m = {T: N, **{b: new_id() for b in tids}}
        mine = set(m.values())
        cf.clone_beliefs(by, parent, ana, m, (N,), lambda x: x in mine or cf.cai_kind(by, x) in cf.BELIEF_SHARED, lpb.land_fix)
        it, tj = R.items[i], 1
        it[tj + 9] = wz.u32a([v for b, x in pairs(TR[tj + 9].array()) if b in m for v in (m[b], x)])
        it[tj + 11].value = len(it[tj + 9].array()) // 2
        it[tj + 13] = wz.u32a([v for b, x in pairs(TR[tj + 13].array()) if b in m for v in (m[b], x)])
        for nb in (m[b] for b in tids):                 # each clone's subjects resolve to the sea or a sibling clone
            assert all(x == N or x in mine for x in by[nb][0][by[nb][1] + 19].array()), (names[i], nb)
    return dict(stage='m', seas=first - wz.NV, per_sea=len(tids), group_map='cai_regions maps the wld seas (stage m)')


# ---------------------------------------------------------------- check
def corridor_check(rep, info, g, area, P, mine, polys, ri, impa, start, comp_of, adj):
    """Corridor masks: no new-domain pathfinding land inside the impassable areas (1 u in from their edge: LAND_BAND);
    corridor width in pathfinding cells (perpendicular cuts through the walkable land where impassable land lies on
    both sides); the routes' ends and the corridor regions' settlements on one walkable landmass."""
    CU = S / FIX                                        # u per pathfinding cell (2)
    IMP = shapely.union_all([polys[ri[k] << 16 | a] for k, a in impa])
    shapely.prepare(IMP)
    land = {}                                           # cell -> [(j, polygon in u)] of new-domain land

    def lpolys(c):
        if c not in land:
            land[c] = [(j, Polygon(np.array(q) / FIX)) for j, (t, q) in enumerate(probe_g3.cell_polys(area, P, c))
                       if t.kind == 0 and t.path_id in mine]
        return land[c]
    x0, y0, x1, y1 = IMP.bounds
    cells = {lp.cell_of(g, x, y) for x in np.arange(x0, x1 + CU, CU) for y in np.arange(y0, y1 + CU, CU)}
    inner = IMP.buffer(-LAND_BAND)
    leak = sum(q.intersection(inner).area for c in cells for _, q in lpolys(c) if q.intersects(inner))
    J = json.load(open(ROUTES))
    widths, ends, comps = {}, {}, set()

    def node(x, y):
        c = lp.cell_of(g, x, y)
        return next(((c, j) for j, q in lpolys(c) if q.covers(Point(x, y))), None)
    for r in J['routes']:
        L = lonlat_geom(shapely.LineString(r['path']))
        ws, nn = [], []
        for d in np.arange(0, L.length, 2.0):
            p, q = L.interpolate(d), L.interpolate(min(d + 0.5, L.length))
            if q.distance(p) == 0:
                continue
            ux, uy = (q.x - p.x) / q.distance(p), (q.y - p.y) / q.distance(p)
            cut = shapely.LineString([(p.x - uy * 20, p.y + ux * 20), (p.x + uy * 20, p.y - ux * 20)])
            sides = [shapely.LineString([(p.x, p.y), cut.coords[i]]) for i in (0, 1)]
            if not all(IMP.intersects(sd) for sd in sides):
                continue
            bx0, by0, bx1, by1 = cut.bounds                # every cell of the cut's box (a sampled cut misses clipped corners)
            ls = [lpolys(c) for c in {lp.cell_of(g, xx, yy) for xx in np.arange(bx0 - CU, bx1 + CU, CU)
                                      for yy in np.arange(by0 - CU, by1 + CU, CU)}]
            W = shapely.union_all([q for l_ in ls for _, q in l_]).buffer(0.02).intersection(cut)   # seam slivers between cells
            piece = next((x for x in shapely.get_parts(W) if x.distance(p) < 0.05), None)
            ws.append((piece.length if piece is not None else 0.0, round(p.x, 1), round(p.y, 1)))
        for d in np.arange(0, L.length, 1.0):
            n_ = node(*L.interpolate(d).coords[0])
            if n_ is not None:
                nn.append(n_)
        widths[r['key']] = ws
        ends[r['key']] = (nn[0], nn[-1]) if nn else (None, None)
        comps |= {comp_of.get(n_) for n_ in ends[r['key']]}
    cor = sorted(info['carve'].get('corridors', {}))
    routed = {r['mask'] for r in J['routes']}             # a mask without routes (arctic, australia) joins no road net:
    alone = [k for k in cor if info['carve']['corridors'][k]['mask'] not in routed]    # its regions need only walkable land
    comps |= {comp_of.get(start[k]) for k in cor if k not in alone}
    allw = [w for ws in widths.values() for w, _, _ in ws]
    rep('corridor masks: no new-domain pathfinding land inside the impassable areas (1 u in)', leak < 0.5,
        f'{leak:.2f} u^2 leaked; {len(impa)} impassable areas, {IMP.area:.0f} u^2')
    rep(f'corridor width >= 2 pathfinding cells ({CU:g} u) where impassable land flanks both sides',
        allw and min(allw) >= 2 * CU, f'narrowest {sorted(w for ws in widths.values() for w in ws)[:6]}; '   # first: rep cuts at 700
        + ', '.join(f'{k} {len(v)} cuts min {min(v)[0] / CU:.1f} at {min(v)[1:]} median '
                    f'{np.median([w for w, _, _ in v]) / CU:.1f} cells' for k, v in widths.items() if v))
    rep('route ends + corridor-region settlements on one walkable landmass (regions of masks without routes: on any)',
        len(comps) == 1 and None not in comps and all(comp_of.get(start[k]) is not None for k in alone),
        f'{len(comps)} components; ends {[k for k, v in ends.items() if None in v or any(comp_of.get(n_) is None for n_ in v)]} '
        f'unreached; regions {[k for k in cor if k not in alone]}; without routes {alone}')


def weld_walk(area, P, a, b, margin=30.0):
    """BFS over land polygons (middle20's land class) from world point a to b inside their box grown by margin: a link
    = a middle20 bit (same cell, or a side with costs8 open both ways) -> polygons on the path, None if b is not
    reached."""
    g = area.grid
    C = g.columns
    sea = lp.sea_id(g)
    cache = {}

    def lpolys(k):
        if k not in cache:
            cache[k] = [(t, q) for t, q in probe_g3.cell_polys(area, P, k) if t.kind not in (2, 3) and t.path_id != sea]
        return cache[k]

    def at(pt):
        k = lp.cell_of(g, *pt)
        return next(((k, j) for j, (t, q) in enumerate(lpolys(k)) if Polygon(q).covers(Point(pt[0] * FIX, pt[1] * FIX))), None)
    lo = [lp.cell_of(g, min(a[0], b[0]) - margin, min(a[1], b[1]) - margin)]
    hi = [lp.cell_of(g, max(a[0], b[0]) + margin, max(a[1], b[1]) + margin)]
    (r0, c0), (r1, c1) = divmod(lo[0], C), divmod(hi[0], C)
    s0, s1 = at(a), at(b)
    if s0 is None or s1 is None:
        return None
    prev = {s0: None}
    todo = collections.deque([s0])
    step = {(1, 0): 0, (0, 1): 2, (0, -1): 5, (-1, 0): 7}
    while todo and s1 not in prev:
        k, j = u = todo.popleft()
        r, col = divmod(k, C)
        t = lpolys(k)[j][0]
        for nib, (dx, dy) in enumerate(((0, -1), (-1, 0), (0, 0), (1, 0), (0, 1))):
            bits = t.middle20 >> 4 * nib & 15
            if not bits or not (r0 <= r + dy <= r1 and c0 <= col + dx <= c1):
                continue
            kn = (r + dy) * C + col + dx
            if (dx or dy) and lp.BLOCKED in (g.cells[k].costs8[step[(dx, dy)]], g.cells[kn].costs8[lp.OPP[step[(dx, dy)]]]):
                continue
            for j2 in range(min(4, len(lpolys(kn)))):
                if bits >> j2 & 1 and (kn, j2) not in prev:
                    prev[(kn, j2)] = u; todo.append((kn, j2))
    if s1 not in prev:
        return None
    n, u = 0, s1
    while u is not None:
        n, u = n + 1, prev[u]
    return n


def check(variant='w1a', stages=STAGES, compact=False, stress=0):
    out = out_dir(variant, stages, compact, stress)
    ov = os.path.join(out, 'overlay', MAPDIR)
    info = json.load(open(os.path.join(out, 'build_info.json')))
    KEYS, ri, pi, S_ = info['regions'], info['region_indices'], info['pathfinding'], info['settlements']
    first = min(ri.values())
    ok = True

    def rep(name, cond, detail='', warn=False):
        nonlocal ok
        ok &= bool(cond) or warn
        print(f"  {'ok  ' if cond else 'warn' if warn else 'FAIL'} {name}" + (f': {str(detail)[:700]}' if detail != '' else ''))

    print(f'== check {os.path.relpath(out, ROOT)}: {len(KEYS)} new regions, {info["region_count"]} in all (ceiling {REGION_CEILING})')
    # ---- pathfinding
    area = pm.PathfindingModel.load(ov + '/pathfinding.esf').areas[0]
    g = area.grid
    nw = len(area.polygon_words)
    rep(f'pathfinding polygon words < 2^21 (static offsets are 21-bit, bit 21 = dynamic polygon)', nw < PF_WORDS_MAX,
        f'{nw} words, {PF_WORDS_MAX - nw} spare')
    pm.rebuild_spatial_grid(area)
    rep('pathfinding rebuild_spatial_grid (CCW, in-cell, tile area, contact masks)', True)
    bad, ex = pf_check.check(area)
    rep('pf_check unwelded sides', not bad, f'{sum(bad.values())} {dict(bad)} {ex[:2]}')
    doms = g.path_domains()
    want = {pi['domains'][k]: (ri[k],) for k in KEYS}
    rix = {**ri, **pi.get('vanilla_index', {})}         # stage 'j': composites with welded vanilla members
    want.update({d: tuple(rix[k] for k in name.split('+')) for name, d in pi['composites'].items()})
    nsing = len(g.region_indices)
    rep('path domains: new singletons before the sea, composites appended', all(doms[d] == m for d, m in want.items())
        and doms.index(()) == pi['sea'] == nsing and sorted(pi['domains'].values()) == list(range(nsing - len(KEYS), nsing))
        and len(doms) <= DOMAIN_IDS,
        f'{len(doms)} domains (<= {DOMAIN_IDS}: 10-bit ids, 1023 = none), {nsing} singletons, sea {doms.index(())}, '
        f'{len(pi["composites"])} composites')
    rep('region counts', g.passable_region_count == g.listed_region_count == nsing)
    P = area.polygons()
    mine = set(want)
    spl = info.get('split') or {}                       # split_ring: re-tagged vanilla land (vanilla middle20 / costs8), so
    mgen = {d for d in mine if not set(doms[d]) & {ri[k] for k in spl}}   # the generated-land checks skip its domains
    tally = collections.Counter()
    for c in g.cells:
        for t in ([c.uniform] if c.uniform else [b.trait for b in c.boundaries]):
            if t.kind == 0 and t.path_id in mine:
                tally[t.path_id] += 1
    rep('every new domain carries land polygons', all(tally[d] for d in mine), f'{len(tally)}/{len(mine)}')
    per = [sum(1 for b in c.boundaries if b.trait.kind == 0 and b.trait.path_id in mgen) for c in g.cells]
    rep('<= 4 land polygons per cell (middle20)', max(per) <= 4, f'max {max(per)}')
    C = g.columns
    lc = [i for i, c in enumerate(g.cells) if lpb.land_mask(c, mgen)]
    asym = sum(1 for i in lc for d, (dx, dy) in enumerate(lp.DIRS)
               if (g.cells[i].costs8[d] == lp.LAND_COST) != (g.cells[(i // C + dy) * C + i % C + dx].costs8[lp.OPP[d]] == lp.LAND_COST)
               and (lpb.land_mask(g.cells[i], mgen) >> d & 1))
    rep('land cost symmetry', asym == 0, f'{len(lc)} cells carry the new domains, {asym} asymmetric land steps')
    start, sbad = {}, {}
    for k in KEYS:
        x, y = S_[k]['pos']
        cell = lp.cell_of(g, x, y)
        hit = [(cell, j) for j, (t, q) in enumerate(probe_g3.cell_polys(area, P, cell)) if Polygon(q).covers(Point(x * FIX, y * FIX))]
        tr_ = [probe_g3.cell_polys(area, P, c)[j][0] for c, j in hit]
        if not (hit and all(t.kind == 0 and t.path_id == pi['domains'][k] for t in tr_)):
            sbad[k] = [(t.kind, t.path_id) for t in tr_]
        start[k] = hit[0] if hit else None
    rep('every settlement on its singleton land domain', not sbad, sbad)
    nodes, adj, miss = lpb.land_graph(area, P, mgen)
    rep('middle20 bit set for every geometric land link across a side', miss == 0, f'{miss} missing; {len(nodes)} land polygons')
    comp_of = {}                                        # walkable landmasses (BFS over land polygons, cost-open steps)
    for k in KEYS:
        if start[k] in comp_of:
            continue
        todo = collections.deque([start[k]])
        comp_of[start[k]] = k
        while todo:
            u = todo.popleft()
            for v in adj[u]:
                if v not in comp_of:
                    comp_of[v] = k; todo.append(v)
    lm = collections.defaultdict(list)
    for k in KEYS:
        lm[comp_of[start[k]]].append(k[4:])
    rep('army walks: settlements by walkable landmass', True, f'{len(lm)} landmasses: ' + '; '.join('+'.join(v) for v in lm.values())
        + f'; {len(comp_of)}/{len(nodes)} land polygons reachable from a settlement')
    # ---- regions.esf
    import regions_world
    out_r, spots_ = regions_world.check(ov + '/regions.esf')
    hard = [k2 for k2 in ('invalid_polygons', 'bad_ring_orientation', 'untwinned_edges', 'bad_face_blobs', 'unused_vertices',
                          'duplicate_vertices', 'connectivity_asymmetric') if out_r[k2]]
    hard += [k2 for k2 in ('connectivity_rebuild_identical', 'id_partitions_ok', 'region_keys_ok', 'quadtree_header_formula',
                           'groundtypes_area_ok', 'theatre_rasters_ok') if not out_r[k2]]
    hard += [k2 for k2 in ('quadtree_mismatch', 'groundtypes_quadtree_mismatch', 'water_ge1_not_sea', 'water_ge1_query_not_sea')
             if not out_r[k2].startswith('0/')]
    hard += [s2[0] for s2 in spots_ if s2[-1] != 'ok' and s2[3] not in KEYS]   # a 'filler' spot we carved (inland Brazil)
    carved = [f'{s2[0]} -> {s2[3]}' for s2 in spots_ if s2[-1] != 'ok' and s2[3] in KEYS]
    rep('regions_world.check', not hard, f"failed {hard}; regions {out_r['regions']} areas {out_r['areas']}; vanilla areas changed "
        f"{len(out_r['vanilla_areas_changed']) if out_r['vanilla_areas_changed'] else 0} (eur_map_west carved)"
        + (f"; filler spots now new regions: {carved}" if carved else ''))
    e = esf.load(ov + '/regions.esf')
    rd = e.root.find('region_data')
    items = rd.find('regions').items
    names = [it[0].value for it in items]
    rep('region indices: new regions appended after the 139 zones regions', [names.index(k) for k in KEYS] == [ri[k] for k in KEYS]
        == list(range(139, 139 + len(KEYS))) and len(items) == info['region_count'] <= (1 << 16 if stress else REGION_CEILING), len(items))
    st_ = info.get('stress') or {}
    east = east_carved(info['carve'])
    carved = ('eur_map_west',) + ((STRESS_FILLER,) if east else ()) + tuple(sorted(set(split_of(KEYS).values())))
    changed = [n for n in (out_r['vanilla_areas_changed'] or []) if not str(n).startswith(carved)]
    rep(f"only {' + '.join(carved)} of the base regions changed", not changed, changed[:5], warn=True)
    if stress:
        kc = collections.Counter(it[1].value for it in items)
        rep(f'stress: {stress} land regions in regions.esf ({len(st_["dummies"])} dummies, {STRESS_OWNER})',
            kc['land'] == stress and st_['regions_esf'] == dict(kc, total=len(items)), f'{dict(kc)}, total {len(items)}')
    polys = rm.area_polygons(rd)
    fl = [(k, rm.area_fields(ar)) for k in KEYS for ar in rm.sub(items[ri[k]], 'areas').items]
    impa = {(k, a) for k, v in info['carve'].get('impassable', {}).items() for a in v}
    spk = set(split_of(KEYS))                           # splits keep their vanilla areas' flags (regions_world: id partitions)
    fl = [(k, a, f) for k in KEYS if k not in spk for a, ar in enumerate(rm.sub(items[ri[k]], 'areas').items) for f in [rm.area_fields(ar)]]
    pgc = collections.Counter(rm.area_fields(a)['pass_group'] for _, _, _, a in rm.iter_areas(rd))
    rep('new areas: passable land with the new pass groups; corridor-mask areas impassable, a singleton pass group each',
        all(f['passable'] != ((k, a) in impa) for k, a, f in fl)
        and {f['pass_group'] for k, a, f in fl if (k, a) not in impa} == {v for x, v in info['carve']['pass_groups'].items()
                                                                          if x.split(':')[0] not in spk}
        | set(info['carve'].get('stress_carve', {}).get('pass_groups', {}).values())
        and all(pgc[f['pass_group']] == 1 for k, a, f in fl if (k, a) in impa), f'{len(fl)} areas, {len(impa)} impassable')
    if impa:
        corridor_check(rep, info, g, area, P, mine, polys, ri, impa, start, comp_of, adj)
    Rp = {k: shapely.union_all([polys[ri[k] << 16 | a] for a in range(len(rm.sub(items[ri[k]], 'areas').items))]) for k in KEYS}
    mvd = {sl for v in spl.values() for sl, _ in v['slots']}   # split_ring: moved slots keep vanilla geometry (building checked)
    inside = [Rp[k].contains(q) for k in KEYS for q in lpb.slot_geometry(items[ri[k]], land=True, skip=mvd)]
    rep('settlements, footprints and slot geometry inside their region polygons', all(inside), f'{sum(inside)}/{len(inside)}')
    out_p = [it2[0].value for it2 in items if rm.sub(it2, 'settlement_and_slots') is not None
             and not lpb.in_display_box(lpb.slot_geometry(it2), PATCHED_HALF)]
    out_v = [it2[0].value for it2 in items if rm.sub(it2, 'settlement_and_slots') is not None
             and not lpb.in_display_box(lpb.slot_geometry(it2))]
    rep(f'every settlement + slot >= {DISPLAY_MARGIN:g} u inside the patched building-display box |x|,|y| <= {PATCHED_HALF:g}', not out_p, out_p)
    rep(f'(vanilla exe box +-{lpb.DISPLAY_HALF:g}: patched Napoleon.exe required)', not out_v, f'{len(out_v)} outside', warn=True)
    th = {k2[0].value for k2 in e.root.find('theatres_and_region_keys').items[0][0].find('region_keys').items}
    settled = {it2[0].value for it2 in items if rm.sub(it2, 'settlement_and_slots') is not None}
    # ---- startpos / CAI
    sp = esf.load(os.path.join(out, 'startpos.esf'))
    rgl, Pr = rm.extract(e)['regions'], polys
    rnames = [r['name'] for r in rgl]
    cw = next(cm._iter_recs(sp.root, 'CAI_WORLD'))
    CRg, CH, CB = (cw.find(n) for n in ('CAI_WORLD_REGIONS', 'CAI_WORLD_REGION_HLCIS', 'CAI_WORLD_REGION_BOUNDARIES'))
    crid = [it[2].value for it in CRg.items]
    hl = {it[1].value: it[-1].children for it in CH.items}
    if stress:
        ra_ = next(cm._iter_recs(sp.root, 'REGIONS_ARRAY')).items
        ro_ = next(cm._iter_recs(sp.root, 'REGION_OWNERSHIPS_BY_THEATRE')).items[0][1].items
        ckind = collections.Counter('sea' if rgl[i]['kind'] == 'sea' else rgl[i]['kind'] for i in range(len(CRg.items)))
        rep('stress counts: regions.esf = CAI_WORLD_REGIONS; startpos REGIONS_ARRAY / REGION_OWNERSHIPS (land with a '
            'settlement); pathfinding domains', len(CRg.items) == len(items),
            f'regions.esf {len(items)} {dict(collections.Counter(it[1].value for it in items))}; CAI_REGION {len(CRg.items)} '
            f'{dict(ckind)}; REGIONS_ARRAY {len(ra_)}; REGION_OWNERSHIPS {len(ro_)}; theatre keys {len(th)}; '
            f'pathfinding regions {nsing}, domains {len(doms)} (10-bit ids, 1023 = none)')
    cids = wz.cai_ids(sp)
    cnext = next(cm._iter_recs(sp.root, 'CAI_CENTRAL_BDI_POOL')).children[0].value
    hbad = [rnames[i] for i in [0] + ([rnames.index(STRESS_FILLER)] if east else []) + list(range(first, len(rgl)))
            if {hl[h][1].value: hl[h][2].array() for h in CRg.items[i][-1].children[1].array()}
            != {pg: al for pg, (al, _) in wz.groups(rgl, Pr, i).items()}
            or not all(hl[h][0].value == crid[i] for h in CRg.items[i][-1].children[1].array())]
    href = collections.Counter(h for it in CRg.items for h in it[-1].children[1].array())
    rep(f"HLCIs = pass groups ({' + '.join(carved)} + new regions), every HLCI listed by exactly one CAI_REGION", not hbad
        and set(href) == set(hl) and set(href.values()) == {1}, f'bad {hbad}; {len(hl)} HLCIs')
    bl = {it[1].value: it[-1].children for it in CB.items}
    bok = all(all(crid[i] in (bl[b][0].value, bl[b][1].value) for b in CRg.items[i][-1].children[7].array()) for i in range(len(rgl)))
    nb = {frozenset((x[0].value, x[1].value)) for x in bl.values()}
    L = wz.shared_lengths(e)
    vn = [(rnames[a], rnames[b]) for (a, b), ln in L.items() if ln > 0 and 1 < a < first <= b and rgl[a]['kind'] == 'land']
    wp = {(v, k) for k, vs in (info['carve'].get('weld') or {}).items() for v in vs}
    spp = {(v, k) for k, v in split_of(KEYS).items()} | split_pairs(e, KEYS)   # a split and its vanilla land neighbours
    rep('split_ring regions share an edge with their old region', {(v['of'], k) for k, v in spl.items()} <= set(vn),
        sorted(spp & set(vn)))
    vn = [p_ for p_ in vn if p_ not in spp]
    if 'j' in stages:
        rep(f"stage 'j': new regions share edges with exactly the welded vanilla land regions (elsewhere the {VANILLA_GAP:g} u strip)",
            set(vn) == wp == {(v, k) for k, vs in WELD.items() if k in KEYS for v in vs},
            f"{sorted((a, b, round(L[(rnames.index(a), rnames.index(b))], 1)) for a, b in vn)}; missing "
            f"{sorted(wp - set(vn))}; WELD pairs {len(wp)}")
    else:
        rep(f'no new region shares an edge with vanilla land (filler strip {VANILLA_GAP:g} u: pathfinding does not weld to vanilla land)',
            not vn, f"{vn}; strip: {info['carve'].get('vanilla_gap')}")
    ll = [(a, b) for (a, b), ln in L.items() if a >= first and b >= first and ln > 0]
    ls = [(a, b) for (a, b), ln in L.items() if ln > 0 and max(a, b) >= first and min(a, b) < first and rgl[min(a, b)]['kind'] == 'sea'
          and CRg.items[min(a, b)][-1].children[8].value]
    ls_in = [p_ for p_ in ls if frozenset((crid[p_[0]], crid[p_[1]])) in nb]
    rep('CAI_REGION per region in regions.esf order; boundaries listed by both ends; every new land pair has one',
        [it[-1].children[10].value for it in CRg.items] == rnames and bok and all(frozenset((crid[a], crid[b])) in nb for a, b in ll),
        f'{len(CRg.items)} regions, {len(ll)} land-land boundaries')
    crix = {c: i for i, c in enumerate(crid)}
    wfz = ({frozenset(p_) for p_ in wp} if 'j' in stages else set()) | {frozenset(p_) for p_ in spp}
    rep('a CAI_REGION_BOUNDARY between each split_ring region and its old region',
        all(frozenset((crid[ri[k]], crid[rnames.index(v['of'])])) in nb for k, v in spl.items()), len(spl))
    xb = [(rnames[a], rnames[b]) for a, b in (sorted(crix[c] for c in q) for q in nb)
          if b >= first and a < first and rgl[a]['kind'] != 'sea' and frozenset((rnames[a], rnames[b])) not in wfz]
    rep('no CAI_REGION_BOUNDARY from a new region to the filler or an unwelded vanilla land region', not xb, xb[:8])
    if 'j' in stages:
        vb = [(a, b) for a, b in vn if frozenset((crid[rnames.index(a)], crid[rnames.index(b)])) in nb]
        rep("stage 'j': a CAI_REGION_BOUNDARY per welded pair", len(vb) == len(vn) == len(wp), f'{len(vb)}/{len(vn)}')
        po = cm.read_poi(esf.load(ov + '/poi.esf')).nodes
        pw = {(v, k): sum(1 for n in po if n.region == v and n.kind in (1, 2, 4, 5, 7) and k in [x for x, _ in n.neighbors])
              for v, k in wp}
        pk = {(v, k): any(v in [x for x, _ in n.neighbors] for n in po if n.region == k) for v, k in wp}
        rep("stage 'j': poi nodes list the welded neighbour both ways", all(pw.values()) and all(pk.values()), pw)
        spos = {**{k: S_[k]['pos'] for k in KEYS}, **{r['name']: r['settlement']['pos'] for r in rgl if r['settlement']}}
        walks = [(v, k) for v, k in sorted(wp)] + [('eur_moscow_guberniya', 'asi_volga_urals')]
        res = {f'{a} -> {b}': weld_walk(area, P, spos[a], spos[b]) for a, b in walks}
        rep("stage 'j': army walks (middle20 + costs8 links) from each welded vanilla settlement to its new neighbour's, "
            "Moscow to Kazan", all(v is not None for v in res.values()), res)
    vw = [(a, b) for (a, b), ln in L.items() if ln > 0 and a < wz.NV <= b < first and CRg.items[a][-1].children[8].value
          and CRg.items[b][-1].children[8].value]
    vw_in = [p_ for p_ in vw if frozenset((crid[p_[0]], crid[p_[1]])) in nb]
    rep(f"stage 'v' {'on' if 'v' in stages else 'off'}: vanilla sea <-> wld sea boundaries", len(vw_in) == (len(vw) if 'v' in stages else 0),
        f'{len(vw_in)}/{len(vw)}: {[(rnames[a], rnames[b]) for a, b in vw_in]}')
    rep(f"stage 'l' {'on' if 'l' in stages else 'off'}: land-sea boundaries", len(ls_in) == (len(ls) if 'l' in stages else 0),
        f'{len(ls_in)}/{len(ls)} new-land <-> sea pairs have a boundary')
    comps_all = wz.cai_components(sp)                    # sp is only read from here on
    gk = {k[j + 1].value: (k, j) for k, j in comps_all
          if isinstance(k[-1], Rec) and k[-1].name == 'CAI_BASIC_REGION_GROUP_ANALYSIS'}
    gam = [k[-1].children[1].array() for k, j in comps_all if isinstance(k[-1], Rec) and k[-1].name == 'CAI_ANALYSER'
           and isinstance(k[-1].children[0], Val) and k[-1].children[0].tag == 0x48 and set(k[-1].children[0].array()) == set(gk)]
    member = {r: G for G, (k, j) in gk.items() for r in k[-1].children[0].array()}
    cown = {it[3].value: it[0].children[0].value for it in cw.find('CAI_WORLD_SETTLEMENTS').items}
    amap = dict(zip(gam[0][::2], gam[0][1::2])) if len(gam) == 1 else {}
    gbad = [rnames[i] for i in range(first, len(rgl)) if amap.get(crid[i]) != member.get(crid[i])
            or gk[member[crid[i]]][0][-1].children[3].value != cown[CRg.items[i][0].children[0].value]
            or CRg.items[i][21].array()[:1] != [member[crid[i]]]]
    rep('every CAI region in one group; new regions in the analyser map, group owner = their CAI owner, region lists its group',
        len(gam) == 1 and sorted(member) == sorted(crid) and all(member[r] == G for r, G in amap.items()) and not gbad,
        f'bad {gbad}; {len(member) - len(amap)} base members unmapped (zones wld seas)')
    hdr = [G for G, (k, j) in gk.items() if k[j + 19].array() != k[-1].children[0].array() + k[-1].children[1].array()]
    cby = {k[j + 1].value: (k, j) for k, j in comps_all}
    nsym = [(G, r) for G, (k, j) in gk.items() for r in k[-1].children[1].array() if G not in cby[r][0][cby[r][1] + 20].array()]
    gadj = {(crid[a], crid[b]) for (a, b), ln in L.items() if ln > 0} | {(crid[b], crid[a]) for (a, b), ln in L.items() if ln > 0}
    nmiss = [(G, y) for G, (k, j) in gk.items() for x in k[-1].children[0].array() for y in [y for x2, y in gadj if x2 == x]
             if (crid.index(x) >= first or crid.index(y) >= first) and y not in k[-1].children[0].array() + k[-1].children[1].array()]
    rep('group headers = members + neighbours, neighbours list the group back, every region bordering a member is a member or '
        'neighbour (new borders)', not hdr and not nsym and not nmiss, f'hdr {hdr[:4]} sym {nsym[:4]} missing {nmiss[:6]}')
    ckind = lambda x: cby[x][0][-1].name if x in cby and isinstance(cby[x][0][-1], Rec) else None
    lan = lpb.land_analysers(cby, CRg, first, crid[rnames.index(TPL)])
    bad_b, nbel = [], []
    for k, j, a, abo, tp in lan:
        p_, own_ = a.children[1].array(), a.children[0].array()
        kb = collections.defaultdict(list)
        for y, b in zip(p_[0::2], p_[1::2]): kb[y].append(b)
        for i in range(first, len(rgl)):
            for y, b in tp:
                key = crid[i] if y in crid else CRg.items[i][-1].children[2].value
                got = [x for x in kb.get(key, []) if ckind(x) == ckind(b)]
                if not (len(got) == 1 and got[0] in own_ and cby[got[0]][0][-1].children[0].value == key
                        and cby[got[0]][0][cby[got[0]][1] + 9].array() == [k[j + 1].value, own_.index(got[0])]):
                    bad_b.append((k[j + 1].value, rnames[i], ckind(b), got))
                nbel += got
    asy = [x for x in nbel if not (all(x in cby[s2][0][cby[s2][1] + 20].array() for s2 in cby[x][0][cby[x][1] + 19].array())
                                   and all(x in cby[r][0][cby[r][1] + 19].array() for r in cby[x][0][cby[x][1] + 20].array()))]
    rep('world region/settlement analysers key every new region/settlement with an owned belief; subjects <-> referenced-by symmetric',
        not bad_b and not asy and lan, f'{len(lan)} analysers, {len(nbel)} new beliefs, bad {bad_b[:4]}, asym {asy[:4]}')
    msk, msb = [], []                                   # 0xD6B5B0: both ends of a boundary need a strength per manager
    for k, j in comps_all:
        a = next((c for c in k if isinstance(c, Rec) and c.name == 'CAI_ANALYSER'), None)
        if a is not None and isinstance(a.children[1], Val) and a.children[1].tag == 0x48:
            p_ = a.children[1].array()
            K = {y for y, b in zip(p_[0::2], p_[1::2]) if ckind(b) == MS}
            if K >= set(crid[:wz.NV]):                  # the 7 world managers (faction-level ones key a few regions)
                msk.append(K)
                msb += [(y, b) for y, b in zip(p_[0::2], p_[1::2]) if ckind(b) == MS]
    half = sorted({rnames[crid.index(r)] for K in msk for x in bl.values() for r, o in ((x[0].value, x[1].value), (x[1].value, x[0].value))
                   if r not in K and o in K})
    rep(f"military strength managers ({len(msk)}) key both ends of every boundary (else 0xD6D9E0 at load)",
        len(msk) == 7 and not half, f'{len(half)} regions missing: {half}')
    nosub = sorted({rnames[crid.index(y)] for y, b in msb if not any(
        ckind(x) == OCC and cby[x][0][-1].children[0].value == y for x in cby[b][0][cby[b][1] + 19].array())})
    rep('every world military strength has its region\'s occupancy analysis as subject (w1a_m v1 had none)', not nosub, nosub)
    wrow = []                                           # zones stage h bug: clones kept the template's row
    for x, (k, j) in cby.items():
        v = k[j + 9]
        if isinstance(v, Val) and v.tag == 0x48 and len(v.array()) == 2 and v.array()[0] in cby:
            an, r = v.array()
            bo = next((q for q in cby[an][0] if isinstance(q, Rec) and q.name == cf.OWNS), None)
            if bo is None or r >= len(bo.items) or bo.items[r][0].value != x:
                wrow.append(x)
    rep("every CAI component's owner link [analyser, row] is its own BLOCK_OWNS row", not wrow,
        f'{len(wrow)} wrong: {collections.Counter(ckind(x) for x in wrow)}')
    sg = cm.read_sea_grids(esf.load(ov + '/sea_grids.esf'))   # w1_s v1: 12 cloned cells, index = CAI id -> 0x6A3110
    cidx = sorted(cby[x][0][-1].children[0].value for x in cby if ckind(x) == 'CAI_SEA_GRID_CELL')
    rep('CAI_SEA_GRID_CELL indices = the sea_grids.esf cells 0..n-1, once each', cidx == list(range(sg.cols * sg.rows)),
        f'{len(cidx)} cells for {sg.cols * sg.rows}, {sum(i >= sg.cols * sg.rows for i in cidx)} out of range')
    if set('sm') & set(stages):
        rep("stage s/m: every CAI region in the region-group analyser map", len(member) == len(amap), f'{len(member) - len(amap)} unmapped')
    rep('CAI ids unique, pool counter above them, THEATRE region list = CAI_WORLD_REGIONS',
        len(cids) == len(set(cids)) and cnext > max(cids) and cw.find('CAI_WORLD_THEATRES').items[0][-1].children[3].array() == crid,
        f'next id {cnext}')
    owner = info['owner']
    fac = info.get('faction') or {}
    oi = info['owner_info']
    fa = next(cm._iter_recs(sp.root, 'FACTION_ARRAY'))
    fac_of = {lpb.fkey(x[0]): x[0] for x in fa.items}
    cfh = {it[-1].children[6].value: it[2].value for it in cw.find('CAI_WORLD_FACTIONS').items}
    cgov = {x[1].value: x[-1].children for x in cw.find('CAI_WORLD_GOVERNORSHIPS').items}
    gov_h = lambda k: fac[owner[k]]['governorship_handle'] if owner[k] in fac else oi[owner[k]]['gov']
    cst = {it[3].value: it for it in cw.find('CAI_WORLD_SETTLEMENTS').items}
    cbs = {it[1].value: it[-1].children for it in cw.find('CAI_WORLD_BUILDING_SLOTS').items}
    ra = next(cm._iter_recs(sp.root, 'REGIONS_ARRAY'))
    rh = {x[0].children[0].value: x[0] for x in ra.items}
    sbad = []
    for i in range(first, len(rgl)):
        k = rnames[i]
        it = CRg.items[i]; sid = it[0].children[0].value; st = cst.get(sid)
        cg = cgov.get(it[-1].children[12].value)
        ui = lp.all_ints(rh[k])
        if not (st is not None and it[-1].children[2].value == sid and st[1].children[2].value == crid[i]
                and it[-1].children[11].value in ui and cg is not None and cg[0].value == gov_h(k) and crid[i] in cg[3].array()
                and st[0].children[0].value == cfh[lpb.fhandle(fac_of[owner[k]])]
                and st[-1].children[2].value in ui and len(st[-1].children[0].array()) == 3
                and all(cbs[b][2].value == sid and cbs[b][0].value in ui for b in st[-1].children[0].array())
                and st[1].children[4].value == min(wz.groups(rgl, Pr, i).items(), key=lambda kv: min(
                    q.distance(Point(st[1].children[0].value / FIX, st[1].children[1].value / FIX)) for q in kv[1][1]))[0]):
            sbad.append(k)
    rep('new CAI_REGIONs: game REGION handle, the owner\'s CAI_GOVERNORSHIP (lists the region), CAI_SETTLEMENT owned by the '
        'owner\'s CAI faction (region, game settlement + 3 slot handles, pass group of its area)', not sbad, sbad)
    spk = [x[0].children[0].value for x in ra.items]
    ownl = next(cm._iter_recs(sp.root, 'REGION_OWNERSHIPS_BY_THEATRE')).items[0][1].items
    own_s = {x[0].value: x[1].value for x in ownl}
    pfk = {names[i] for i in g.region_indices}
    rep('region lists agree (regions.esf settlements = theatre keys = pathfinding region_indices = REGIONS_ARRAY = REGION_OWNERSHIPS)',
        settled == th == pfk == set(spk) == set(own_s) and len(spk) == len(ownl) == nsing and set(KEYS) <= th,
        f'{len(settled)} {len(th)} {len(pfk)} {len(spk)} {len(ownl)}')
    obad = {}
    for o in dict.fromkeys(owner.values()):
        F = fac_of[o]
        govs = list(cm._iter_recs(F, 'GOVERNORSHIP'))
        for k in (k for k in KEYS if owner[k] == o):
            r = rh[k]
            if not (own_s[k] == o and r.children[20].value == lpb.fhandle(F) and r.children[22].value == gov_h(k)
                    and any(info['startpos'][k]['handles']['region'] in x.children[2].array() and x.children[1].value == gov_h(k) for x in govs)
                    and r.children[24].value == (spl[k]['rebels'] if k in spl else o if o in fac else oi[o]['rebels'])):
                obad[k] = (own_s[k], r.children[20].value, r.children[22].value, r.children[24].value)
    others = [k for k in KEYS if owner[k] != lp.OWNER]
    bg = list(cm._iter_recs(fac_of[lp.OWNER], 'GOVERNORSHIP'))
    left = [k for k in others if any(info['startpos'][k]['handles']['region'] in x.children[2].array() for x in bg)]
    left += [k for k in others if lp.all_ints(rh[k]) & {lpb.fhandle(fac_of[lp.OWNER]), lp.GOV}]
    rep('owners: REGION_OWNERSHIPS, REGION[20] faction / [22] governorship / [24] rebels, the governorship lists the region; '
        'handed-over regions keep no Britain handle and are off Britain\'s governorships', not obad and not left,
        dict(obad=obad, left=left, owners=dict(collections.Counter(owner.values()))))
    pg = next(cm._iter_recs(sp.root, 'PATHFINDING_GRID')).items[0]
    b8, f11 = pg[8].value, struct.unpack(f'<{len(pg[11].value) // 4}f', pg[11].value)
    vd = pi.get('vanilla_domains', {})
    flag = lambda k: b8[vd[spl[k]['of']]] if k in spl else 0 if owner[k] in fac else oi[owner[k]]['flag']
    rep('PATHFINDING_GRID leaves 8/11 = domain count; new singletons = owner flag (split_ring: the old singleton\'s 8 + 11), '
        'composites = AND of members',
        len(b8) == len(f11) == len(doms) and all(b8[pi['domains'][k]] == flag(k) for k in KEYS)
        and all(f11[pi['domains'][k]] == f11[vd[spl[k]['of']]] for k in spl)
        and all(b8[d] == int(all(b8[{**pi['domains'], **pi.get('vanilla_domains', {})}[k]] for k in n.split('+')))
                for n, d in pi['composites'].items()),
        (len(b8), len(f11), len(doms)))
    allh = [h for k in KEYS for h in info['startpos'][k]['handles'].values()]
    base = lp.all_ints(esf.load(ZSP).root)
    counts = collections.Counter()
    allhs = set(allh)
    lp.walk_vals(sp.root, lambda kids, j, v: counts.update([v.value]) if v.tag in (0x04, 0x08) and v.value in allhs else
                 counts.update(x for x in struct.unpack(f'<{len(v.value) // 4}I', v.value) if x in allhs) if v.tag in (0x44, 0x48) and v.value else None)
    wantc = dict(region=3, settlement=3, rrm=1, settlement_1_slot=3, settlement_road=3, settlement_fortification=3)
    caps = [v['capital'] for v in fac.values()]
    bad_h = {k: {n: counts[h] for n, h in info['startpos'][k]['handles'].items()
                 if counts[h] != wantc[n] + (n == 'region' and k in caps) * 2} for k in KEYS}
    rep('new REGION handles unique, absent from the base, used only by their records + CAI shadows (+ capital refs)',
        len(set(allh)) == len(allh) and not set(allh) & base and not any(bad_h.values()), {k: v for k, v in bad_h.items() if v})
    pos_ok = [k for k in KEYS if not (abs(rh[k].find('SETTLEMENT').children[0].children[10].value / FIX - S_[k]['pos'][0]) < 1e-4
                                      and abs(rh[k].find('SETTLEMENT').children[0].children[11].value / FIX - S_[k]['pos'][1]) < 1e-4)]
    rep('startpos settlement positions = regions.esf settlements', not pos_ok, pos_ok)
    los = {}
    for k in KEYS:
        t = rh[k].find('SETTLEMENT').children[0]
        for L2 in lp.recs(rh[k], 'LINE_OF_SIGHT'):
            if L2.children[0].value:
                (x0, y0), (x1, y1) = L2.children[1].value, L2.children[2].value
                los.setdefault(k, []).append(x0 <= t.children[10].value / FIX <= x1 and y0 <= t.children[11].value / FIX <= y1)
    rep('settlement LINE_OF_SIGHT boxes (moved by D rounded to 10 u) contain the settlement', all(all(v) and len(v) == 2 for v in los.values())
        and len(los) == len(KEYS), {k: v for k, v in los.items() if not all(v)})
    # ---- trade
    tr = cm.read_trade_routes(esf.load(ov + '/trade_routes.esf'))
    tm = next(cm._iter_recs(sp.root, 'CAMPAIGN_TRADE_MANAGER'))
    Pn, Sn = len(tr.ports), len(tr.settlements)
    pix = {x[0].value: x[1].value for x in tm.find('PORT_INDICES').items}
    six = {x[0].value: x[1].value for x in tm.find('SETTLEMENT_INDICES').items}
    tnodes = sorted(x[1].value for x in tm.find('TRADE_NODES').items)
    routes = [(x[0].value, x[1].value, tuple(x[2].array()), x[3].value) for x in tm.find('TRADE_ROUTES').items]
    esr = {(a, b, tuple(ids), ln) for a, b, ids, ln in tr.routes}
    node_of = {int(n.rsplit('_', 1)[1]): rs for n, rs in tr.node_routes}
    nr = {(a, Pn + Sn + k2, tuple(ids), ln) for k2, rs in node_of.items() for a, ids, ln in rs}
    dom_nodes = [r[0].children[6].value for fac_ in tm.find('DOMESTIC_TRADE_ROUTES').items for r in fac_[1].items]
    rep('trade indices consistent (trade_routes.esf <-> startpos), the new settlements registered',
        pix == {p_: i for i, p_ in enumerate(tr.ports)} and six == {s2: Pn + i for i, s2 in enumerate(tr.settlements)}
        and tnodes == list(range(Pn + Sn, Pn + Sn + len(tr.node_routes))) and set(routes) == esr | nr and len(routes) == len(esr) + len(nr)
        and all(Pn + Sn <= v < Pn + Sn + len(tnodes) for v in dom_nodes) and all(k in six for k in KEYS),
        f'P={Pn} S={Sn} routes {len(routes)}')
    allp = tr.ports + tr.settlements
    rset = {frozenset((a, b)) for a, b, *_ in routes}
    nor = [(names[a], names[b]) for (a, b), ln in L.items() if ln > 0 and names[a] in allp and names[b] in allp
           and frozenset((allp.index(names[a]), allp.index(names[b]))) not in rset]
    rep('a trade route between every two settlements whose regions border', not nor, nor)
    # ---- poi
    p = cm.read_poi(esf.load(ov + '/poi.esf'))
    ids = [n.id for n in p.nodes]
    pbad, pgen = {}, {x[0] for x in info['poi_nodes']}
    for k in KEYS:
        mn = [n for n in p.nodes if n.region == k]
        k4 = [n for n in mn if n.kind == 4]
        apg = {rm.area_fields(ar)['pass_group'] for ar in rm.sub(items[ri[k]], 'areas').items}
        good = (len(k4) == 1 and k4[0].x == int(round(S_[k]['pos'][0] * FIX)) and all(Rp[k].contains(Point(n.wx, n.wy)) for n in mn)
                and all(n.area == n.area2 and n.area in apg for n in mn)
                and all(k in spl and n.id not in pgen         # split_ring: relabelled vanilla nodes keep their vanilla spot
                        or any((t.kind == 0 and t.path_id == pi['domains'][k] or k in spl and t.kind in (0, 6, 7)
                                and t.path_id != 1023 and ri[k] in doms[t.path_id]) and Polygon(q).covers(Point(n.x, n.y))
                               for t, q in probe_g3.cell_polys(area, P, lp.cell_of(g, n.wx, n.wy))) for n in mn))
        if not good:
            pbad[k] = len(mn)
    rep('poi: ids unique, one kind-4 node at each settlement, nodes on the region singleton land, pass group of their area '
        '(split_ring: its old region\'s nodes there on land of a domain holding it)', len(set(ids)) == len(ids) and not pbad, pbad)
    if spl:                                             # split_ring: the moved slots belong to the new region everywhere
        sk_ = lambda rs: next(v.value for v in rs.children if isinstance(v, Val) and v.tag == 0x0e)
        RSs = {it[3].value: it for it in cw.find('CAI_WORLD_REGION_SLOTS').items}
        sdesc = lambda k: {s2[0].value for s2 in rm.sub(items[names.index(k)], 'settlement_and_slots').find('slot_descriptions').items}
        rslots = lambda k: {sk_(x[0]) for x in rh[k].find('REGION_SLOT_MANAGER').find('REGION_SLOT_ARRAY').items}
        mbad = {}
        for k, v in spl.items():
            o, ck, co = v['of'], CRg.items[ri[k]][-1].children, CRg.items[rnames.index(v['of'])][-1].children
            for (sl, dock), rsid in zip(v['slots'], v['cai_region_slots']):
                rs_ = RSs[rsid]
                pr = [(a, b) for a, b, *_ in routes if pix[sl] in (a, b)] if sl.startswith('port:') else []
                good = (sl in sdesc(k) and sl not in sdesc(o) and sl in rslots(k) and sl not in rslots(o)
                        and rs_[0].children[0].value == rs_[1].children[2].value == crid[ri[k]]
                        and rsid in ck[3].array() and rsid not in co[3].array()
                        and (not sl.startswith('port:') or six[k] in {x for p_ in pr for x in p_} and six[o] not in {x for p_ in pr for x in p_}))
                if not good:
                    mbad[sl] = k
        rep('split_ring slots moved: regions.esf slot list, startpos REGION_SLOT_ARRAY, CAI_REGION_SLOT owner + situated region, '
            'CAI_REGION slot lists, a port\'s trade route to the new settlement', not mbad,
            mbad or {k: [sl for sl, _ in v['slots']] for k, v in spl.items()})
    # ---- db, loc, lookup
    dbp = os.path.join(out, 'overlay/db')
    reg_t = dbtable.load(dbp + '/regions_tables/regions')
    st_t = dbtable.load(dbp + '/campaign_map_settlements_tables/campaign_map_settlements')
    rgbs = [tuple(r[2:5]) for r in reg_t['rows']]
    rows = loc.from_tsv(open(os.path.join(out, 'loc_rows.tsv'), encoding='utf-8').read())
    lk = {r[0] for r in rows}
    sloc = [rh[k].find('SETTLEMENT').find('CAMPAIGN_LOCALISATION').children[0].value for k in KEYS]
    rloc = [rh[k].children[41].children[0].value for k in KEYS]
    rep('db rows + loc keys (regions, settlements, rebels)', all(sum(r[0] == k for r in reg_t['rows']) == 1 for k in KEYS)
        and len(set(rgbs)) == len(rgbs) and all(sum(r[1] == k for r in st_t['rows']) == 1 for k in KEYS)
        and set(sloc + rloc) <= lk and len(lk) == len(rows), f'{len(reg_t["rows"])} regions rows, loc {len(rows)} rows')
    li, lpal = lookup_tga.read_tga(open(ov + '/europe_lookup.tga', 'rb').read())
    pix_c = collections.Counter(map(tuple, lpal[li].reshape(-1, 3).tolist()))
    col = lookup_tga.colours(dbp + '/regions_tables/regions')
    nocol = set(st_.get('no_lookup_colour', [])) | set(info.get('lookup_no_colour', []))
    mp = info.get('minimap_parent', {})
    nopix = [k for k in KEYS if k not in mp and (pix_c[col[k]] == 0) != (k in nocol)]
    real = [k for k in KEYS if k not in mp and k not in set(st_.get('dummies', []))]
    au = info['area_u2']
    rep(f'lookup palette: {len(pix_c)} colours in use (<= {PALETTE} + black), {len(nocol & set(real))} real regions past it '
        f'(smallest first), {len(mp)} minimap_parent children', len(set(map(tuple, lpal.tolist()))) <= 254 and len(pix_c) <= PALETTE + 1
        and max([au[k] for k in real if k in nocol], default=0) <= min([au[k] for k in real if k not in nocol], default=1e18)
        and all(m in col and m not in mp for m in mp.values()), sorted(nocol & set(real))[:5])
    rep('minimap_parent children: no pixels of their own colour, the parent colour has pixels',
        all(pix_c[col[k]] == 0 and (pix_c[col[m]] > 0 or m in nocol) for k, m in mp.items()), mp)
    if stress:
        rep(f'stress lookup: {len(pix_c)} palette colours in use (<= 252 + black), {len(nocol)} dummies without one (no pixels)',
            len(set(map(tuple, lpal.tolist()))) <= 254 and len(pix_c) <= 253, sorted(nocol)[:3])
    rep('europe_lookup.tga: 605x300, every new region (not a child, not past the palette) has pixels of its regions_tables colour', li.shape == (300, 605) and not nopix,
        f'missing {nopix}; {len(pix_c)} colours; ' + ', '.join(f'{k[4:]} {pix_c[col[k]]}' for k in KEYS[:6]) + ' ...')
    if fac:
        cx = cf.Cai(sp)
        gh = {lpb.fkey(it[0]): lpb.fhandle(it[0]) for it in fa.items}
        cfh2 = cx.factions()
        for k, g_ in info['cai']['factions'].items():
            U, T = g_['cai_faction'], g_['template']
            fr = [crid[ri[r]] for r in fac[k]['regions']]
            for name, c, d in cf.check_faction(sp, U, T, regions=fr, cx=cx):
                rep(f'{k}: {name}', c, d)
            ugk = [x for x, (kk, j) in gk.items() if kk[-1].children[3].value == U]
            rep(f'{k}: FACTION handle -> CAI faction {U}; one {k}-owned land group = its regions (region index order; the '
                f'faction lists its capital first: oman)', cfh2.get(gh[k]) == U and ugk == [g_['group']]
                and gk[ugk[0]][0][-1].children[0].array() == sorted(fr, key=crid.index), (ugk, gk[ugk[0]][0][-1].children[0].array() if ugk else None, fr))
        NF = len(fa.items)
        n_ = {}
        for name in ('FACTION_ARRAY', 'PLAYERS_ARRAY', 'FACTION_INFOS', 'SPYING_ARRAY', 'DOMESTIC_TRADE_ROUTES', 'INTERNATIONAL_TRADE_ROUTES'):
            for m_, arr in enumerate(cm._iter_recs(sp.root, name)):
                n_[f'{name}#{m_}'] = len(arr.items)
        rep(f'faction lists: {NF} entries ({len(fac)} new)', set(n_.values()) == {NF} and NF == 41 + len(fac), n_)
        fh = {lpb.fhandle(x[0]): lpb.fkey(x[0]) for x in fa.items}
        dip = {lpb.fkey(x[0]): sorted(e2[0].children[0].value for e2 in x[0].find('DIPLOMACY_MANAGER').find('DIPLOMACY_RELATIONSHIPS_ARRAY').items)
               for x in fa.items}
        rep('diplomacy complete', all(v == sorted(h for h in fh if fh[h] != k) for k, v in dip.items()))
        for name, c, d in protectorates.check(sp, [pc for pc in protectorates.PAIRS if set(pc) <= set(fh.values())]):
            rep(name, c, d)
        tabs = {n: dbtable.load(f'{dbp}/{n}_tables/{n}') for n in lpb.FACTION_TABLES}
        nm_ = lambda k: {k, f'agent_ID_{k}', f'campaign_euro_general2_{k}'}
        cnt_ = lambda k, n, t: sum(bool(nm_(k) & set(r)) and not (n == 'factions' and r[0] != k) for r in t['rows'])
        miss = {(k, n): (cnt_(lpb.FAC_TPL, n, t), cnt_(k, n, t)) for k in fac for n, t in tabs.items()
                if cnt_(k, n, t) != cnt_(lpb.FAC_TPL, n, t) or not cnt_(k, n, t)}
        for k in fac:                                   # a vanilla agent_ID_<key> rigid (united_states) kept instead of a clone
            if k in info['db_rows_added'].get('warscape_rigid (vanilla row kept)', []) or f'agent_ID_{k}' in info['db_rows_added'].get(
                    'warscape_rigid (vanilla row kept)', []):
                for n in ('warscape_rigid', 'warscape_rigid_lod'):
                    if miss.get((k, n), (0, 0))[1] >= 1:
                        miss.pop((k, n), None)
        wk = [r[0] for r in tabs['warscape_rigid']['rows']]
        if len(set(wk)) != len(wk):
            miss['warscape_rigid duplicate keys'] = [x for x, c in collections.Counter(wk).items() if c > 1]
        fuc = {r[0]: r[1:7] for r in dbtable.load(os.path.join(out, 'overlay', COL_T))['rows']}
        rep('faction db tables: one row per oldenburg row for every new faction; uniform colours from factions.json', not miss
            and all(fuc[k] == [*d['colours'][0], *d['colours'][1]] for k, d in new_factions(specs(variant, compact), KEYS).items()), miss)
        fi = [f for f, _ in dbtable.fields_for('factions', tabs['factions']['version'])].index('flags_path')
        frow = {r[0]: r[fi] for r in tabs['factions']['rows']}
        fstr, frgb = collections.defaultdict(list), collections.defaultdict(list)
        for x in fa.items:
            lp.walk_vals(x[0], lambda kids, j, v, k=lpb.fkey(x[0]): (fstr[k].append(v.value), frgb[k].append([c.value for c in kids[j + 1:j + 10]]))
                         if v.tag in (0x0e, 0x0f) and str(v.value).startswith('data\\ui\\flags\\') else None)
        nf = new_factions(specs(variant, compact), KEYS)
        cbad = {k: frgb[k] for k in fac if frgb[k] != [fac_rgb9(nf[k])] * 2}
        rep('campaign map colours: both FACTION_FLAG_AND_COLOURS of every new faction carry its factions.json colours '
            '(primary, secondary, primary)', not cbad, cbad)
        fnames = [f for f, _ in dbtable.fields_for('factions', tabs['factions']['version'])]
        frows = {r[0]: dict(zip(fnames, r)) for r in tabs['factions']['rows']}
        dbad = {k: {c: frows[k][c] for c in want if frows[k][c] != want[c]} for k in fac
                for want in [fac_db_colours(nf[k])] if any(frows[k][c] != want[c] for c in want)}
        abad = {k: frows[k]['attack_desc'] for k in fac if frows[k]['attack_desc'] != lpb.attack_desc(nf[k]['adj'])}
        rep('factions table: the 18 primary/secondary/uniform (+ alt_) colour columns of every new faction = factions.json '
            '(= its FACTION_FLAG_AND_COLOURS trios); attack_desc a/an by the adjective', not dbad and not abad, (dbad, abad))
        fbad = {k: (frow.get(k), fstr[k], len(os.listdir(os.path.join(FLAGS, 'gn_' + k))) if os.path.isdir(os.path.join(FLAGS, 'gn_' + k)) else None)
                for k in fac}
        fbad = {k: v for k, v in fbad.items() if v != (flag_path(k), [flag_path(k)] * 2, 24)}
        rep(f'flags: every new faction -> {flag_path("<key>")} (factions flags_path, 2 startpos FACTION strings), '
            f'work/mods/flags dir with 24 files; {lpb.FAC_TPL} keeps its own', not fbad and frow[lpb.FAC_TPL] == OLD_FLAG
            and fstr[lpb.FAC_TPL] == [OLD_FLAG] * 2, fbad)
        need = {x for k in fac for x in (f'factions_screen_name_{k}', f'factions_screen_adjective_{k}', f'start_pos_factions_description_{k}')}
        rep('faction loc keys', need <= lk, sorted(need - lk))
    if 'p' in stages:
        import port_probe
        ok &= port_probe.check(out)
    print('  PASS' if ok else '  FAIL')
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('cmd', nargs='?', default='build', choices=('build', 'check'))
    ap.add_argument('--variant', default='w1a', choices=VARIANTS)
    ap.add_argument('--wave', choices=list(WAVES), help='= --variant <wave> (generated factions)')
    ap.add_argument('--no-land-sea', action='store_true', help="stage 'l' off: no land <-> sea CAI_REGION_BOUNDARYs")
    ap.add_argument('--compact', action='store_true', help='full_only regions merged into their merge_into region')
    ap.add_argument('--stages', help="stage letters, overrides --no-land-sea: l land-sea boundaries, s / m wld sea beliefs")
    ap.add_argument('--stress-land', type=int, default=0, metavar='N',
                    help='G4b: dummy regions (stress_NNN, Britain) out of eur_map_east until regions.esf has N land regions')
    ap.add_argument('--reuse', action='store_true',
                    help='stage cache (work/cache/stages): restore geometry / pre-ports / ports results whose code, args and inputs are unchanged; stores new ones')
    a = ap.parse_args()
    stages = a.stages if a.stages is not None else STAGES.replace('l', '') if a.no_land_sea else STAGES
    a.variant = a.wave or a.variant
    if a.cmd == 'build':
        build(a.variant, stages, a.compact, a.stress_land, a.reuse)
    ok = check(a.variant, stages, a.compact, a.stress_land)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
