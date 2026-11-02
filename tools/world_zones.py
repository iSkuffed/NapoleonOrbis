#!/usr/bin/env python3
"""Startpos, poi.esf and sea_grids.esf for the zones variant of the world regions file (work/world/regions/regions.esf:
139 regions, 0..100 vanilla in vanilla order, 101..138 new wld_* seas).

  .venv/bin/python tools/world_zones.py          # build work/world/zones/{startpos,poi,sea_grids}.esf, then check
  .venv/bin/python tools/world_zones.py check    # self-check the existing outputs only
  .venv/bin/python tools/world_zones.py stages [name..]   # crash bisection: sp_<name>.esf variants (see VARIANTS)

Startpos base = world_build.startpos() (vanilla Coalition, renamed map, regridded visibility, box rect, no obstacles).
startpos_zones() then edits CAI_INTERFACE/CAI_WORLD (vanilla record shapes, verified on mp_eur_napoleon):
  CAI_REGION        new sea: blank BDI component header (as every vanilla HLCI/boundary carries) + OWNED_INDIRECT +
                    CAI_REGION copied from eur_gulf_of_bothnia: [theatre id], [hlci ids], 0, [], f32 x, y (= the
                    pass-group HLCI point, as vanilla), [], [boundary ids], True, [mobiles], key, 0, 0, [].
  CAI_REGION_HLCI   one per (region, pass_group): region id, pass_group, u32[] area indices, i32 fixed x, y.
                    Point = group centroid if inside the group, else a point on the largest part (vanilla's own rule
                    is not derivable: land main groups use the settlement, other points are just interior points).
  CAI_REGION_BOUNDARY  every pair of CAI-valid regions (field 8 True: not eur_map_*/all) sharing outline edges:
                    region a id, region b id, f32 2 x shared length (vanilla median ratio 2.0), u32 0. Region field 7
                    lists every boundary of the region.
  CAI_SEA_GRID_CELL one per sea_grids.esf cell (world grid 51x22); the 66 vanilla objects keep their ids (fleet
                    analyses reference them) and get the world cell index; the rest are new.
  THEATRE           region id list and sea-grid-cell id list; CAI_CENTRAL_BDI_POOL[0] = next free CAI id.
  Refreshed vanilla: eur_map_west/east HLCIs (one per new filler area), grown seas (#25 Black Sea kept: area change
  < KEEP_REL; #98/#99 HLCI + centroid recomputed), boundary lists/lengths touching grown or new seas.
poi_zones(): vanilla poi + kind-6 sea nodes on a 37.5 u lattice (4 per sea-grid cell) in every new sea and in the
  grown parts of vanilla seas outside the vanilla theatre; each links to its nearest land POI (kinds 1,2,3,5,8).
sea_grid_zones(): world_build.sea_grid() + region lists from polygons (cells with sea list every intersecting region,
  index order; cells without sea list nothing, the vanilla rule), POI lists = new kind-6 nodes in the cell, edges for
  every pair of sea cells (vanilla pairs keep vanilla cost, others = 8-neighbour sea-cell path length, 0.0 = none).
"""
import copy, os, struct, sys
from collections import defaultdict

import numpy as np
import shapely
from shapely.geometry import box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import esf, geo, proj, campaign_misc as cm, regions_model as rm, world_build  # noqa: E402
from esf import Rec, Val  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGIONS = os.path.join(ROOT, 'work/world/regions/regions.esf')
OUT = os.path.join(ROOT, 'work/world/zones')
VAN = geo.GAME + '/campaign_maps/nap_europe'
FIX = 1 << 20
NV = 101                       # vanilla regions
CHANGED = (0, 1, 25, 98, 99)   # vanilla regions whose geometry differs in the zones file
KEEP_REL = 0.01                # keep a vanilla HLCI point when its group area changed less than this (and it is inside)
STEP = 37.5                    # kind-6 lattice spacing (half a sea-grid cell)
LAND_KINDS = (1, 2, 3, 5, 8)   # vanilla kind-6 link targets
VT = box(*proj.VT_MIN, *proj.VT_MAX)
u32a = lambda a: rm.mkarr(0x48, np.asarray(a, np.uint32))


def sig(x):
    if isinstance(x, list): return tuple(sig(c) for c in x)
    if isinstance(x, Rec): return (x.name, x.version, sig(x.children), None if x.items is None else tuple(sig(i) for i in x.items))
    return (x.tag, x.value)


def model(path):
    e = esf.load(path)
    return rm.extract(e)['regions'], rm.area_polygons(e.root.find('region_data')), e


def groups(regs, P, i):
    """pass_group -> (area indices, area polygons) of region i."""
    g = defaultdict(list)
    for a, ar in enumerate(regs[i]['areas']): g[ar['pass_group']].append(a)
    return {pg: (al, [P[i << 16 | a] for a in al]) for pg, al in sorted(g.items())}


def interior_point(polys):
    u = shapely.union_all(polys)
    c = u.centroid
    if not u.contains(c):   # ponytail: point-on-surface, not a pole of inaccessibility
        c = max(shapely.get_parts(u), key=lambda p: p.area).point_on_surface()
    return round(c.x * FIX), round(c.y * FIX)


def shared_lengths(e):
    """{(ra, rb) ra < rb: shared outline length} from the directed edge owners."""
    rd = e.root.find('region_data'); V = rm.verts(rd).astype(np.float64); own = rm.edge_owner(rd)
    L = defaultdict(float)
    pairs = [(a, b, code >> 16, t >> 16) for (a, b), code in own.items()
             for t in [own.get((b, a))] if t is not None and code >> 16 < t >> 16]
    if pairs:
        a, b, ra, rb = zip(*pairs)
        a, b = np.array(a), np.array(b)
        for r, ln in zip(zip(ra, rb), np.hypot(V[a, 0] - V[b, 0], V[a, 1] - V[b, 1]).tolist()):
            L[r] += ln                                   # in edge order, as the per-edge sum was
    return L


def cell_map():
    """vanilla sea cell index -> world grid index (same rule as world_build.sea_grid)."""
    vs = cm.read_sea_grids(esf.load(VAN + '/sea_grids.esf'))
    cols = cm.sea_grid_dims(proj.THEATRE_MIN, proj.THEATRE_MAX, vs.cell)[0]
    dx, dy = int((proj.VT_MIN[0] - proj.THEATRE_MIN[0]) // vs.cell), int((proj.VT_MIN[1] - proj.THEATRE_MIN[1]) // vs.cell)
    return vs, [(i // vs.cols + dy) * cols + i % vs.cols + dx for i in range(vs.cols * vs.rows)]


# ---------------------------------------------------------------- startpos
BELIEF_KINDS = ('CAI_BASIC_BORDER_ANALYSIS_REGION', 'CAI_REGION_MILITARY_STRENGTH', 'CAI_REGION_OCCUPANCY_ANALYSIS',
                'CAI_BORDER_PATROL_ANALYSIS')


def region_beliefs(sp, R, rid, new_id, rep, template='eur_norwegian_sea'):
    """Stage h: give every new region (R.items[NV:]) the per-region beliefs a vanilla sea has, cloned from template's:
    1 CAI_BASIC_BORDER_ANALYSIS_REGION (no group/faction border entries: new seas only border seas of their own
    group), 7 CAI_REGION_MILITARY_STRENGTH (one per manager, empty faction list as the template), 1
    CAI_REGION_OCCUPANCY_ANALYSIS, 1 CAI_BORDER_PATROL_ANALYSIS (no patrol areas; 5 vanilla ones have none). Each
    clone goes into the template's pool; every CAI_ANALYSER whose inner (subject, belief) pair list mentions the
    template region gets the same pairs for the new region (this includes analyser 5's region -> group map), owns
    its new beliefs (inner owned list, BLOCK_OWNS row, header j+16 count) and watches what the template's are watched
    for (header j+18: the beliefs, plus the region for border analysis / military strength); CAI_THEATRE_RELATIVE_MILITARY_STRENGTHS and CAI_FACTION_SEA_GRID_ANALYSIS
    lists get the new ids; the region header gets the template's belief links."""
    comps, parent = [], {}
    def walk(r):
        for kids in ([r.children] if r.items is None else r.items):
            for j, c in enumerate(kids):
                if isinstance(c, Rec):
                    if c.name == 'CAI_BDI_COMPONENT_PROPERTY_SET' and j + 1 < len(kids) and isinstance(kids[j + 1], Val):
                        comps.append((kids, j)); parent[id(kids)] = r
                    walk(c)
    walk(next(cm._iter_recs(sp.root, 'CAI_INTERFACE')))
    kind = lambda k: k[-1].name if isinstance(k[-1], Rec) else None
    sub = lambda k, n: next(c for c in k if isinstance(c, Rec) and c.name == n)
    names = [it[-1].children[10].value for it in R.items]
    ti = names.index(template); T = rid[ti]; TR = R.items[ti]
    tmpl = [(k, j) for k, j in comps if kind(k) in BELIEF_KINDS and k[-1].children[0].value == T]
    assert sorted(kind(k) for k, _ in tmpl) == sorted(BELIEF_KINDS + ('CAI_REGION_MILITARY_STRENGTH',) * 6), tmpl
    tids = [k[j + 1].value for k, j in tmpl]
    ana = []
    for k, j in comps:
        a = next((c for c in k if isinstance(c, Rec) and c.name == 'CAI_ANALYSER'), None)
        if a is not None and T in a.children[1].array():
            bo = sub(k, 'CAI_BDI_COMPONENT_BLOCK_OWNS')
            assert k[j + 16].value == len(a.children[0].array()) == len(bo.items)
            ana.append((k, j, a, bo))
    theatre_ms = [(k, j) for k, j in comps if kind(k) == 'CAI_THEATRE_RELATIVE_MILITARY_STRENGTHS'
                  and set(tids) & set(k[j + 19].array())]
    theatre_ids = {k[j + 1].value for k, j in theatre_ms}
    sea_grid = [(k, j) for k, j in comps if kind(k) == 'CAI_FACTION_SEA_GRID_ANALYSIS' and T in k[j + 19].array()]
    group = [k[j + 1].value for k, j in comps if kind(k) == 'CAI_BASIC_REGION_GROUP_ANALYSIS'
             and T in k[-1].children[0].array()]

    def subst(x, m):
        if isinstance(x, list):
            for c in x: subst(c, m)
        elif isinstance(x, Rec):
            for kids in ([x.children] if x.items is None else x.items): subst(kids, m)
        elif x.tag == 0x08 and x.value in m: x.value = m[x.value]
        elif x.tag == 0x48 and set(x.array()) & set(m):
            x.value = u32a([m.get(v, v) for v in x.array()]).value

    pairs = lambda a: list(zip(a[0::2], a[1::2]))
    for i in range(NV, len(R.items)):
        N = rid[i]; m = {T: N}; clones = {}
        for b in tids: m[b] = new_id()
        for (k, j), b in zip(tmpl, tids):
            c = copy.deepcopy(k); subst(c, m); clones[m[b]] = (c, j)
            if kind(c) == 'CAI_BASIC_BORDER_ANALYSIS_REGION':
                base = sub(c, 'CAI_BASIC_BORDER_ANALYSIS_BASE')
                for r in base.children[:2]: r.items = []
                c[j + 19] = u32a([N])
            elif kind(c) == 'CAI_BORDER_PATROL_ANALYSIS':
                c[-1].children[1].items = []
            # referenced-by: keep the clones and the theatre strengths updated below; drop region-specific watchers
            # (e.g. a faction's CAI_REGION_DEFENCE_STRENGTH_ANALYSIS of the template region)
            c[j + 20] = u32a([x for x in c[j + 20].array() if x in m.values() or x in theatre_ids])
            parent[id(k)].items.append(c)
        owned = defaultdict(int)
        for k, j, a, bo in ana:
            new = [(m.get(x, x), m.get(y, y)) for x, y in pairs(a.children[1].array()) if T in (x, y)]
            for x, y in new:
                other = y if x == N else x
                assert other in m.values() or other in group, (k[j + 1].value, x, y)
            a.children[1] = u32a(a.children[1].array() + [v for p in new for v in p])
            k[j + 18] = u32a(k[j + 18].array() + [m[x] for x in k[j + 18].array() if x in m])   # watch list
            mine = [v for p in new for v in p if v in m.values() and v != N]
            for v in mine:
                b = next(t for t, n in m.items() if n == v)
                row = copy.deepcopy(next(it for it in bo.items if it[0].value == b)); row[0].value = v
                bo.items.append(row); owned[v] += 1
                c, cj = clones[v]; c[cj + 9] = u32a([k[j + 1].value, len(bo.items) - 1])   # owner link -> its own row
            a.children[0] = u32a(a.children[0].array() + mine)
            k[j + 16].value = len(a.children[0].array())
        assert sorted(owned) == sorted(m[b] for b in tids) and set(owned.values()) == {1}, 'one owning analyser each'
        for k, j in theatre_ms:
            k[j + 19] = u32a(k[j + 19].array() + [m[b] for b in tids if b in k[j + 19].array()])
        for k, j in sea_grid:
            k[j + 19] = u32a(k[j + 19].array() + [N])
        it, tj = R.items[i], 1
        for off in (9, 13):
            it[tj + off] = u32a([v for b, x in pairs(TR[tj + off].array()) if b in m for v in (m[b], x)])
        it[tj + 11].value = len(it[tj + 9].array()) // 2
        it[tj + 20] = u32a(it[tj + 20].array() + [m[b] for b in TR[tj + 20].array() if b in m]
                           + [k[j + 1].value for k, j in sea_grid])
    rep['region_beliefs'] = (template, len(tmpl), len(ana), len(theatre_ms), len(sea_grid))


def cai_components(sp):
    """(item list, index of its CAI_BDI_COMPONENT_PROPERTY_SET) for every CAI BDI component under CAI_INTERFACE.
    Header fields relative to j: j+1 id, j+19 subject ids, j+20 ids of the components that reference this one."""
    out = []
    def walk(r):
        for kids in ([r.children] if r.items is None else r.items):
            for j, c in enumerate(kids):
                if isinstance(c, Rec):
                    if c.name == 'CAI_BDI_COMPONENT_PROPERTY_SET' and j + 1 < len(kids) and isinstance(kids[j + 1], Val):
                        out.append((kids, j))
                    walk(c)
    walk(next(cm._iter_recs(sp.root, 'CAI_INTERFACE')))
    return out


# 'abrndeg' (sp_abndeg) = all but the 6 vanilla-sea<->new-sea boundaries (v): with v the load crashes at 0xD6D9E0,
# with v+h it hangs (research/00). In game: loads, 3 AI turns.
STAGES = 'abrndeg'


def startpos_zones(sp, regions_path=REGIONS, stages=STAGES):
    """Mutate a loaded startpos (world_build.startpos output) in place for the zones regions file. Returns a report.
    stages (crash bisection), any subset of:
      a  vanilla HLCIs of CHANGED regions refreshed in place (area list, point) + vanilla sea centroids; no new ids
      b  new CAI_REGION records, every new HLCI (new seas + new filler pass groups of eur_map_west/east), THEATRE
         region list
      c  boundaries (new pairs + rescaled vanilla lengths); needs b (new boundaries reference new regions)
         = r + v + n: r rescaled vanilla lengths only, v new boundaries vanilla sea - new sea, n new sea - new sea
      d  CAI_SEA_GRID_CELL: vanilla 66 get world cell indices, 1056 new blank cells, list sorted by index (1122),
         THEATRE cell list
      m  only the remap part of d: the 66 vanilla cells get world cell indices, nothing added
      e  CAI_CENTRAL_BDI_POOL[0] = next free id (no-op unless b/c/d allocated ids)
      g  new seas join the vanilla sea CAI_BASIC_REGION_GROUP_ANALYSIS (needs b; without it a boundary from a
         vanilla sea to a new one crashes the load, 2026-10-18 bisect: sp_abv; g alone did not fix it)
      h  per-region beliefs for the new regions, cloned from eur_norwegian_sea (region_beliefs); needs g"""
    assert set(stages) <= set('abcdemrvngh') and ('b' in stages or not set('cvngh') & set(stages)), stages
    assert 'h' not in stages or 'g' in stages, "h maps new regions to the sea group"
    regs, P, ez = model(regions_path)
    vregs, vP, ev = model(VAN + '/regions.esf')
    w = next(cm._iter_recs(sp.root, 'CAI_WORLD'))
    central = next(cm._iter_recs(sp.root, 'CAI_CENTRAL_BDI_POOL'))
    nxt = central.children[0].value
    def new_id():
        nonlocal nxt
        nxt += 1
        return nxt - 1
    R, H, B, S = (w.find(n) for n in ('CAI_WORLD_REGIONS', 'CAI_WORLD_REGION_HLCIS', 'CAI_WORLD_REGION_BOUNDARIES',
                                      'CAI_WORLD_SEA_GRID_CELLS'))
    TH = w.find('CAI_WORLD_THEATRES').items[0][-1]
    assert [it[-1].children[10].value for it in R.items] == [r['name'] for r in regs[:NV]] == [r['name'] for r in vregs]
    blank = copy.deepcopy(H.items[0][:-1])
    for it in H.items + B.items:
        assert sig(it[:1] + it[2:-1]) == sig(blank[:1] + blank[2:]), 'HLCI/boundary headers are blank apart from the id'
    def top(i):
        t = copy.deepcopy(blank); t[1] = Val(0x08, i); return t
    rep = defaultdict(list)

    # new sea regions (HLCI / boundary lists filled below)
    tmpl = R.items[98]
    assert tmpl[-1].children[10].value == 'eur_gulf_of_bothnia'
    for i in range(NV, len(regs) if 'b' in stages else NV):
        assert regs[i]['kind'] == 'sea', regs[i]['name']
        rec = copy.deepcopy(tmpl[-1]); c = rec.children
        c[1], c[7], c[9], c[13] = u32a([]), u32a([]), u32a([]), u32a([])
        c[10].value = regs[i]['name']
        c[2].value = c[11].value = c[12].value = 0
        R.items.append([copy.deepcopy(tmpl[0])] + top(new_id()) + [rec])
    rid = [it[2].value for it in R.items]
    CR = lambda i: R.items[i][-1].children

    # region group: every vanilla region sits in exactly one CAI_BASIC_REGION_GROUP_ANALYSIS (inner [0] = its regions,
    # header j+19 = those regions + inner [1] neighbour regions) and lists that group first in its header j+20. The
    # AI looks the group up when it walks a boundary from a vanilla sea, so new seas join the vanilla sea group.
    if 'g' in stages:
        grp = [(k, j) for k, j in cai_components(sp) if isinstance(k[-1], Rec) and k[-1].name == 'CAI_BASIC_REGION_GROUP_ANALYSIS']
        assert sorted(r for k, _ in grp for r in k[-1].children[0].array()) == sorted(rid[:NV]), 'one group per region'
        k, j = next(g for g in grp if rid[2] in g[0][-1].children[0].array())   # eur_atlantic_ocean_n
        gc = k[-1].children; n = len(gc[0].array())
        assert gc[4].value == 1 and k[j + 19].array() == gc[0].array() + gc[1].array(), 'sea group layout'
        gc[0] = u32a(gc[0].array() + rid[NV:])
        k[j + 19] = u32a(gc[0].array() + gc[1].array())
        for i in range(NV, len(rid)):
            assert R.items[i][2].value == rid[i] and R.items[i][1].name == 'CAI_BDI_COMPONENT_PROPERTY_SET'
            R.items[i][21] = u32a([k[j + 1].value] + R.items[i][21].array())
        rep['sea_group'] = (k[j + 1].value, n, len(gc[0].array()))

    # HLCIs: new seas, refreshed filler/grown seas
    hl = {it[1].value: it[-1].children for it in H.items}
    todo = (list(CHANGED) if {'a', 'b'} & set(stages) else []) + (list(range(NV, len(regs))) if 'b' in stages else [])
    for i in todo:
        have = {hl[h][1].value: h for h in CR(i)[1].array()}
        vg = groups(vregs, vP, i) if i < NV else {}
        assert set(vg) <= set(have) and set(have) <= set(groups(regs, P, i)), (i, 'vanilla pass groups must survive')
        ids = CR(i)[1].array()
        for pg, (al, polys) in groups(regs, P, i).items():
            if pg not in have:
                if 'b' not in stages: continue
                h = new_id(); ids.append(h)
                hl[h] = [Val(0x08, rid[i]), Val(0x08, pg), u32a(al), Val(0x04, 0), Val(0x04, 0)]
                H.items.append(top(h) + [Rec('CAI_REGION_HLCI', 0, hl[h])])
                x, y = interior_point(polys)
                rep['hlci_new'].append(h)
            else:
                if 'a' not in stages: continue
                h = have[pg]; c = hl[h]
                va, vpolys = vg[pg]
                same = c[2].array() == al == va and all(shapely.equals(vP[i << 16 | a], P[i << 16 | a]) for a in al)
                if same: continue
                c[2] = u32a(al)
                u, vu = shapely.union_all(polys), shapely.union_all(vpolys)
                old = shapely.Point(c[3].value / FIX, c[4].value / FIX)
                if abs(u.area - vu.area) < KEEP_REL * vu.area and u.contains(old):
                    rep['hlci_kept_point'].append((regs[i]['name'], pg)); continue
                x, y = interior_point(polys)
                rep['hlci_refreshed'].append((regs[i]['name'], pg))
            c = hl[h]; c[3].value, c[4].value = x, y
            if regs[i]['kind'] == 'sea':   # region centroid = its (only) pass-group point, as vanilla
                CR(i)[4].value, CR(i)[5].value = float(np.float32(x / FIX)), float(np.float32(y / FIX))
                if i < NV: rep['centroid_refreshed'].append(regs[i]['name'])
        CR(i)[1] = u32a(ids)

    # boundaries
    bst = set('rvn') if 'c' in stages else set(stages) & set('rvn')
    Lz, Lv = (shared_lengths(ez), shared_lengths(ev)) if bst else ({}, {})
    id2i = {v: i for i, v in enumerate(rid)}
    have = {frozenset((id2i[it[-1].children[0].value], id2i[it[-1].children[1].value])): it[-1].children for it in B.items}
    valid = [CR(i)[8].value for i in range(len(R.items))]
    for (a, b), L in sorted(Lz.items()):
        if not (valid[a] and valid[b]) or L <= 0: continue
        c = have.get(frozenset((a, b)))
        if c is None:
            if ('v' if a < NV else 'n') not in bst: continue
            h = new_id()
            B.items.append(top(h) + [Rec('CAI_REGION_BOUNDARY', 0, [Val(0x08, rid[a]), Val(0x08, rid[b]),
                                                                     Val(0x0a, float(np.float32(2 * L))), Val(0x08, 0)])])
            for r in (a, b): CR(r)[7] = u32a(CR(r)[7].array() + [h])
            rep['boundary_new'].append((regs[a]['name'], regs[b]['name']))
        elif 'r' in bst and abs(L - Lv[(a, b)]) > 1e-6 * max(1.0, Lv[(a, b)]):
            assert Lv[(a, b)] > 0
            c[2].value = float(np.float32(c[2].value * L / Lv[(a, b)]))
            rep['boundary_rescaled'].append((regs[a]['name'], regs[b]['name'], round(Lv[(a, b)], 2), round(L, 2)))
    for p in have if bst else ():
        a, b = sorted(p)
        if Lv.get((a, b), 0) > 0 and Lz.get((a, b), 0) <= 0: rep['boundary_lost'].append((regs[a]['name'], regs[b]['name']))

    # sea grid cells: one CAI object per world sea_grids cell, ordered by cell index
    vs, kmap = cell_map()
    ncell = len(cm.make_sea_grid_cells(proj.THEATRE_MIN, proj.THEATRE_MAX, vs.cell)[2])
    assert len(S.items) == len(kmap) and [it[-1].children[0].value for it in S.items] == list(range(len(kmap)))
    cells = [None] * ncell
    if {'d', 'm'} & set(stages):
        for i, it in enumerate(S.items):
            it[-1].children[0].value = kmap[i]; cells[kmap[i]] = it
    if 'd' in stages:
        ctmpl = next(it for it in S.items if not it[-1].children[1].items)
        for k in range(ncell):
            if cells[k] is None:
                rec = copy.deepcopy(ctmpl[-1]); rec.children[0].value = k
                cells[k] = top(new_id()) + [rec]
        S.items[:] = cells

    if 'h' in stages:
        region_beliefs(sp, R, rid, new_id, rep)

    th = TH.children
    assert th[3].array() == rid[:NV] and len(th[4].value) == 4 * len(kmap)
    th[3] = u32a(rid)
    th[4] = u32a([it[1].value for it in S.items])
    rep['ids'] = (central.children[0].value, nxt)
    if 'e' in stages: central.children[0].value = nxt
    return rep


# ---------------------------------------------------------------- poi
def poi_zones(regions_path=REGIONS):
    regs, P, _ = model(regions_path)
    poi = cm.read_poi(esf.load(VAN + '/poi.esf'))
    codes = [c for c in P if regs[c >> 16]['kind'] == 'sea']
    tree = shapely.STRtree([P[c] for c in codes])
    (x0, y0), (x1, y1) = proj.THEATRE_MIN, proj.THEATRE_MAX
    X, Y = np.meshgrid(np.arange(x0 + STEP / 2, x1, STEP), np.arange(y0 + STEP / 2, y1, STEP))
    pts = shapely.points(X.ravel(), Y.ravel())
    pi, ti = tree.query(pts, predicate='within')
    order = np.lexsort((pi, [codes[t] >> 16 for t in ti]))     # region order, then lattice order
    found = []
    for j in order:
        r, p = codes[ti[j]] >> 16, pts[pi[j]]
        if r < NV and VT.intersects(p): continue                # vanilla nodes already cover vanilla seas in VT
        found.append((r, round(p.x * FIX), round(p.y * FIX)))
    for r in range(NV, len(regs)):                             # every new sea gets at least one node
        if regs[r]['kind'] == 'sea' and not any(f[0] == r for f in found):
            found.append((r, *interior_point([P[r << 16 | a] for a in range(len(regs[r]['areas']))])))
    found.sort(key=lambda f: f[0])
    from scipy.spatial import cKDTree
    land = [n for n in poi.nodes if n.kind in LAND_KINDS]
    kd = cKDTree([(n.wx, n.wy) for n in land])
    _, near = kd.query([(x / FIX, y / FIX) for _, x, y in found])
    n0 = len(poi.nodes)
    for j, ((r, x, y), li) in enumerate(zip(found, near)):
        k = regs[r]['name']
        poi.nodes.append(cm.PoiNode(n0 + j, 6, False, x, y, k, 6, k, 6, 0.0, [], -1.0, [], [land[li].id], 0, False))
    return esf.dumps(cm.write_poi(poi))


# ---------------------------------------------------------------- sea grids
def sea_grid_zones(regions_path=REGIONS, poi_bytes=None):
    regs, P, _ = model(regions_path)
    g = cm.read_sea_grids(esf.loads(world_build.sea_grid()))
    vs, kmap = cell_map()
    nodes = cm.read_poi(esf.loads(poi_bytes or poi_zones(regions_path))).nodes
    n0 = len(cm.read_poi(esf.load(VAN + '/poi.esf')).nodes)
    codes = list(P)
    boxes = [box(*a, *b) for _, _, a, b in g.cells]
    ci, ti = shapely.STRtree([P[c] for c in codes]).query(boxes, predicate='intersects')
    inner = shapely.relate_pattern(np.array([P[codes[t]] for t in ti]), np.array([boxes[c] for c in ci]), 'T********')
    hits = defaultdict(set)
    for c, t, ok in zip(ci, ti, inner):
        if ok: hits[c].add(codes[t] >> 16)
    local = defaultdict(list)
    for n in nodes[n0:]:
        local[int((n.wx - g.bmin[0]) // g.cell) + int((n.wy - g.bmin[1]) // g.cell) * g.cols].append(n.id)
    idx = {r['name']: i for i, r in enumerate(regs)}
    vcell = {k: i for i, k in enumerate(kmap)}
    for k in range(len(g.cells)):
        land = {r for r in hits[k] if regs[r]['kind'] != 'sea'}; sea = hits[k] - land
        v = vs.info[vcell[k]] if k in vcell else None
        if v is not None:               # vanilla cell: vanilla lists (quirks kept) + new/changed regions only
            keep = lambda s, old: {r for r in s if r >= NV or r in CHANGED} | {idx[n] for n in old}
            land, sea = keep(land, v[0]), keep(sea, v[1])
        rest = (v[2], v[3]) if v is not None and v[1] else ([], local[k])
        g.info[k] = [[regs[r]['name'] for r in sorted(land)], [regs[r]['name'] for r in sorted(sea)], *rest] if sea \
            else [[], [], [], []]
    # edges: every pair of sea cells
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import shortest_path
    seac = [k for k in range(len(g.cells)) if g.info[k][1]]
    pos = {k: j for j, k in enumerate(seac)}
    r_, c_, d_ = [], [], []
    for k in seac:
        cx, cy = k % g.cols, k // g.cols
        for ddx, ddy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            n = (cy + ddy) * g.cols + cx + ddx
            if 0 <= cx + ddx < g.cols and 0 <= cy + ddy < g.rows and n in pos:
                r_.append(pos[k]); c_.append(pos[n]); d_.append(g.cell * np.hypot(ddx, ddy))
    D = shortest_path(coo_matrix((d_, (r_, c_)), shape=(len(seac),) * 2).tocsr(), directed=False)
    # vanilla costs straight from the vanilla file: world_build.sea_grid() remaps edges with the world column count
    van = {(kmap[a], kmap[b]): c for a, b, c in vs.edges}
    g.edges =[(a, b, van[(a, b)] if (a, b) in van else float(np.float32(D[pos[a], pos[b]] if np.isfinite(D[pos[a], pos[b]]) else 0.0)))
               for j, a in enumerate(seac) for b in seac[j + 1:]]
    return esf.dumps(cm.write_sea_grids(g))


# ---------------------------------------------------------------- check
def cai_ids(sp):
    """every CAI BDI component id (the u32 after each CAI_BDI_COMPONENT_PROPERTY_SET) under CAI_INTERFACE."""
    return [kids[j + 1].value for kids, j in cai_components(sp)]


VARIANTS = (('a', 'a'), ('ab', 'ab'), ('abc', 'abc'), ('abcd', 'abcd'), ('abcde', 'abcde'),   # cumulative
            ('d', 'd'), ('de', 'de'), ('m', 'm'),                                             # on the plain startpos
            ('abde', 'abde'), ('abr', 'abr'), ('abv', 'abv'), ('abn', 'abn'),                 # stage c split
            ('abv_fixed', 'abvg'), ('abc_fixed', 'abcg'), ('abcde_fixed', 'abcdeg'),          # + sea group
            ('abndeg', 'abrndeg'),                                    # fallback: all but the 6 vanilla-new boundaries
            ('abvgh', 'abvgh'), ('abcdegh', 'abcdegh'))                                       # + per-region beliefs


def write_stages(only=()):
    """work/world/zones/sp_<name>.esf per VARIANTS entry, each from the same world_build.startpos(minimap) base;
    reloads each and checks CAI ids unique, THEATRE lists = CAI_WORLD lists, sea cell indices unique."""
    os.makedirs(OUT, exist_ok=True)
    base = world_build.startpos(world_build.minimap())
    for name, st in VARIANTS:
        if only and name not in only: continue
        sp = esf.loads(base)
        rep = startpos_zones(sp, stages=st)
        open(f'{OUT}/sp_{name}.esf', 'wb').write(esf.dumps(sp))
        sp = esf.load(f'{OUT}/sp_{name}.esf')
        w = next(cm._iter_recs(sp.root, 'CAI_WORLD'))
        R, S = w.find('CAI_WORLD_REGIONS'), w.find('CAI_WORLD_SEA_GRID_CELLS')
        th = w.find('CAI_WORLD_THEATRES').items[0][-1].children
        ids = cai_ids(sp); nxt = next(cm._iter_recs(sp.root, 'CAI_CENTRAL_BDI_POOL')).children[0].value
        cix = [it[-1].children[0].value for it in S.items]
        assert len(ids) == len(set(ids)) and len(cix) == len(set(cix)) == len(S.items)
        assert th[3].array() == [it[2].value for it in R.items] and th[4].array() == [it[1].value for it in S.items]
        print(f'sp_{name}.esf stages={st}: regions {len(R.items)}, HLCIs {len(w.find("CAI_WORLD_REGION_HLCIS").items)}, '
              f'boundaries {len(w.find("CAI_WORLD_REGION_BOUNDARIES").items)}, sea cells {len(S.items)} '
              f'(index {min(cix)}..{max(cix)}), ids {len(ids)} unique, max {max(ids)}, counter {nxt}'
              f'{"" if nxt > max(ids) else " (BELOW max id: e not applied)"}; '
              + ', '.join(f'{k} {len(v) if isinstance(v, list) else v}' for k, v in rep.items()))


def check(regions_path=REGIONS):
    regs, P, ez = model(regions_path)
    names = [r['name'] for r in regs]
    new = names[NV:]
    rpoly = lambda r: [P[r << 16 | a] for a in range(len(regs[r]['areas']))]
    on_region = lambda r, p: any(q.covers(p) for q in rpoly(r))

    # --- startpos
    sp = esf.load(OUT + '/startpos.esf'); vsp = esf.load(world_build.VANILLA_SP)
    w, vw = (next(cm._iter_recs(e.root, 'CAI_WORLD')) for e in (sp, vsp))
    R, H, B, S = (w.find(n) for n in ('CAI_WORLD_REGIONS', 'CAI_WORLD_REGION_HLCIS', 'CAI_WORLD_REGION_BOUNDARIES',
                                      'CAI_WORLD_SEA_GRID_CELLS'))
    keys = [it[-1].children[10].value for it in R.items]
    assert len(R.items) == len(regs) == 139 and keys == names, 'CAI_WORLD_REGIONS = regions.esf order'
    print(f'CAI_WORLD_REGIONS: {len(R.items)} entries, keys == regions.esf order')
    rid = [it[2].value for it in R.items]; id2i = {v: i for i, v in enumerate(rid)}
    ids = cai_ids(sp)
    nxt = next(cm._iter_recs(sp.root, 'CAI_CENTRAL_BDI_POOL')).children[0].value
    assert len(ids) == len(set(ids)) and nxt > max(ids), 'CAI ids unique, counter above them'
    th = w.find('CAI_WORLD_THEATRES').items[0][-1].children
    g = cm.read_sea_grids(esf.load(OUT + '/sea_grids.esf'))
    assert th[3].array() == rid and th[4].array() == [it[1].value for it in S.items]
    assert [it[-1].children[0].value for it in S.items] == list(range(len(g.cells))), 'one CAI cell per sea_grids cell'
    print(f'CAI ids unique ({len(ids)}), next id {nxt}; THEATRE lists {len(rid)} regions, {len(S.items)} sea cells '
          f'(= sea_grids {g.cols}x{g.rows})')
    grp = {r: (k, j) for k, j in cai_components(sp) if isinstance(k[-1], Rec) and k[-1].name == 'CAI_BASIC_REGION_GROUP_ANALYSIS'
           for r in k[-1].children[0].array()}
    assert sorted(grp) == sorted(rid) and all(R.items[i][21].array()[0] == grp[rid[i]][0][2].value for i in range(len(rid)))
    sg = {id(grp[r][0]) for r in rid[NV:]} | {id(grp[rid[2]][0])}
    assert len(sg) == 1 and all(k[j + 19].array() == k[-1].children[0].array() + k[-1].children[1].array()
                                for k, j in grp.values())
    print(f'every region in one CAI_BASIC_REGION_GROUP_ANALYSIS, listed first in its header; new seas in the vanilla '
          f'sea group {grp[rid[2]][0][2].value} ({len(grp[rid[2]][0][-1].children[0].array())} regions)')
    T = rid[names.index('eur_norwegian_sea')]
    for k, j in cai_components(sp):
        a = next((c for c in k if isinstance(c, Rec) and c.name == 'CAI_ANALYSER'), None)
        if a is not None and T in a.children[1].array():
            assert set(rid[NV:]) <= set(a.children[1].array()[0::2]) and k[j + 16].value == len(a.children[0].array())
    print('every analyser keyed by eur_norwegian_sea also keys every new sea (region group, border analysis, border '
          'patrol, occupancy, 7 military strengths)')
    hl = {it[1].value: it[-1].children for it in H.items}
    for i in range(len(regs)):
        c = R.items[i][-1].children
        got = {hl[h][1].value: hl[h][2].array() for h in c[1].array()}
        assert all(hl[h][0].value == rid[i] for h in c[1].array())
        assert got == {pg: al for pg, (al, _) in groups(regs, P, i).items()}, (names[i], 'HLCI = pass groups')
        bl = sorted(it[1].value for it in B.items if i in (id2i[it[-1].children[0].value], id2i[it[-1].children[1].value]))
        assert sorted(c[7].array()) == bl, (names[i], 'boundary list')
    print('every region (139): HLCIs == regions.esf pass groups (area lists), field 7 == its boundaries')
    for i in range(NV, len(regs)):
        c = R.items[i][-1].children; h = hl[c[1].array()[0]]
        p = shapely.Point(c[4].value, c[5].value)
        assert shapely.Point(h[3].value / FIX, h[4].value / FIX).distance(p) < 1e-4, (names[i], 'centroid = HLCI point')
        u = shapely.union_all(rpoly(i)); big = max(shapely.get_parts(u), key=lambda q: q.area)
        assert u.covers(p), (names[i], 'centroid inside')
        assert big.covers(p) or u.centroid.distance(p) < 1e-3, names[i]
        assert len(c[7].array()) > 0 and c[8].value is True, names[i]
    print(f'{len(new)} new seas: CAI_REGION + HLCI present, centroid inside the region '
          f'(centroid or point on the largest part), >= 1 boundary each')
    # vanilla records
    vR = vw.find('CAI_WORLD_REGIONS').items
    changed = [i for i in range(NV) if sig(R.items[i]) != sig(vR[i])]
    for i in changed:
        a, b = R.items[i][-1].children, vR[i][-1].children
        diff = [j for j in range(len(a)) if sig(a[j]) != sig(b[j])]
        assert sig(R.items[i][:-1]) == sig(vR[i][:-1]) and set(diff) <= {1, 4, 5, 7}, (names[i], diff)
        assert b[7].array() == a[7].array()[:len(b[7].array())] and b[1].array() == a[1].array()[:len(b[1].array())]
        assert i in CHANGED or set(diff) == {7}, (names[i], diff)
    print('vanilla CAI_REGION records changed (fields):', [(names[i], [j for j in range(len(R.items[i][-1].children))
          if sig(R.items[i][-1].children[j]) != sig(vR[i][-1].children[j])]) for i in changed])
    vH = {it[1].value: it for it in vw.find('CAI_WORLD_REGION_HLCIS').items}
    Hc = {it[1].value: it for it in H.items}
    hch = [(names[id2i[hl[k][0].value]], hl[k][1].value) for k in vH if sig(vH[k]) != sig(Hc[k])]
    assert {n for n, _ in hch} <= {names[i] for i in CHANGED}
    print('vanilla HLCIs changed:', hch)
    vB = {it[1].value: it for it in vw.find('CAI_WORLD_REGION_BOUNDARIES').items}
    Bc = {it[1].value: it for it in B.items}
    bch = [(names[id2i[Bc[k][-1].children[0].value]], names[id2i[Bc[k][-1].children[1].value]], round(vB[k][-1].children[2].value, 2),
            round(Bc[k][-1].children[2].value, 2)) for k in vB if sig(vB[k]) != sig(Bc[k])]
    assert all(sig(vB[k][-1].children[:2] + vB[k][-1].children[3:]) == sig(Bc[k][-1].children[:2] + Bc[k][-1].children[3:]) for k in vB)
    print(f'vanilla boundaries {len(vB)}: lengths rescaled {bch}; new boundaries {len(B.items) - len(vB)}')
    vS = {it[1].value: it for it in vw.find('CAI_WORLD_SEA_GRID_CELLS').items}
    Sc = {it[1].value: it for it in S.items}
    assert all(sig(vS[k][:-1]) == sig(Sc[k][:-1]) and sig(vS[k][-1].children[1:]) == sig(Sc[k][-1].children[1:]) for k in vS)
    print(f'vanilla sea-grid cell objects {len(vS)}: unchanged apart from the world cell index')
    for nm in ('CAI_WORLD_SETTLEMENTS', 'CAI_WORLD_REGION_SLOTS', 'CAI_WORLD_RESOURCE_MOBILES', 'CAI_WORLD_FACTIONS'):
        assert sig(w.find(nm)) == sig(vw.find(nm)), nm
    print('CAI_WORLD_SETTLEMENTS / REGION_SLOTS / RESOURCE_MOBILES / FACTIONS identical to vanilla')

    # --- poi
    pn = cm.read_poi(esf.load(OUT + '/poi.esf')).nodes; vn = cm.read_poi(esf.load(VAN + '/poi.esf')).nodes
    assert pn[:len(vn)] == vn and [n.id for n in pn] == list(range(len(pn)))
    assert all(0 <= i < len(pn) for n in pn for i in n.links), 'poi link ids exist'
    add = pn[len(vn):]
    assert all(n.kind == 6 and n.links and on_region(names.index(n.region), shapely.Point(n.wx, n.wy)) for n in add)
    per = defaultdict(int)
    for n in add: per[n.region] += 1
    assert all(per[k] > 0 for k in new)
    print(f'poi: {len(vn)} vanilla nodes unchanged, {len(add)} new kind-6 nodes inside their sea, every link id exists; '
          f'every new sea has nodes (min {min(per[k] for k in new)}); vanilla seas grown: '
          f'{ {k: v for k, v in per.items() if k not in new} }')

    # --- sea grids
    vs, kmap = cell_map()
    allsea = {s for inf in g.info for s in inf[1]}
    assert set(new) <= allsea, set(new) - allsea
    sea_cells = [k for k in range(len(g.cells)) if g.info[k][1]]
    assert [(a, b) for a, b, _ in g.edges] == [(a, b) for j, a in enumerate(sea_cells) for b in sea_cells[j + 1:]]
    van = {(kmap[a], kmap[b]): c for a, b, c in vs.edges}
    E = {(a, b): c for a, b, c in g.edges}
    assert all(E[p] == c for p, c in van.items()), 'vanilla edge costs kept'
    assert all(0 <= i < len(pn) for inf in g.info for i in inf[3])
    grown = {names[i] for i in CHANGED} | set(new)
    adds = {}
    for i, k in enumerate(kmap):
        v, z = vs.info[i], g.info[k]
        for j in range(4):
            assert set(v[j]) <= set(z[j]), (i, j)
        assert (z[2], z[3]) == (v[2], v[3]) or not v[1]
        extra = sorted(set(z[0] + z[1]) - set(v[0] + v[1]))
        if extra: adds[i] = extra
        assert set(extra) <= grown, (i, extra)
    print(f'sea_grids {g.cols}x{g.rows}: every new key in a cell sea list; {len(sea_cells)} sea cells, '
          f'{len(g.edges)} edges (all pairs, vanilla costs kept); vanilla cells keep their lists, additions '
          f'(only new/grown/filler keys): {adds}')
    print('world_zones check OK')


def main():
    if sys.argv[1:] == ['check']:
        return check()
    if sys.argv[1:2] == ['stages']:
        return write_stages(sys.argv[2:])
    os.makedirs(OUT, exist_ok=True)
    pb = poi_zones()
    open(OUT + '/poi.esf', 'wb').write(pb)
    open(OUT + '/sea_grids.esf', 'wb').write(sea_grid_zones(poi_bytes=pb))
    sp = esf.loads(world_build.startpos(world_build.minimap()))
    rep = startpos_zones(sp)
    for k, v in rep.items(): print(k, len(v) if isinstance(v, list) and len(v) > 12 else v)
    open(OUT + '/startpos.esf', 'wb').write(esf.dumps(sp))
    check()


if __name__ == '__main__':
    main()
