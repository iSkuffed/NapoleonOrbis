"""Religion of the new factions and regions in the startpos (2026-10-28).

Before this, the new factions kept their template's (oldenburg) rel_protestant and the new regions eur_ireland's
RELIGION_BREAKDOWN (catholic 0.7, protestant 0.3), Qing and Mughal India included.  Two startpos edits:
  FACTION: every rel_* string inside it (the faction's own religion, FAMILY::MONARCHY_INFO_CHARACTER x2),
  REGION/.../RELIGION_BREAKDOWN: the 9 (rel_key, f32) shares from regions.json 'religion' (absent = 0).
government(): a new faction whose factions.json government the game has (GOV: republic) gets it; the rest keep the
template's gov_absolute_monarchy.  GOVERNMENT [1] = the gov_* key, GOV_IMP = the type's record, copied from a vanilla
faction of that type (netherlands: GOVERNMENT::REPUBLIC; the posts are the same for every type).

    python tools/religion.py check STARTPOS_OR_SAVE      # faction religions and region shares
"""
import collections
import copy
import json
import os
import sys

import esf
import campaign_misc as cm
import land_probe as lp
import land_probe_b as lpb

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'world1805')
# factions.json religion -> the game's nine (rel_animist also stands for folk religions, rel_buddhist for Confucian /
# Shinto / Chinese folk practice, rel_orthodox for the oriental churches)
REL = {'protestant': 'rel_protestant', 'catholic': 'rel_catholic', 'orthodox': 'rel_orthodox', 'hindu': 'rel_hindu',
       'sikh': 'rel_sikh', 'buddhist': 'rel_buddhist', 'islamic': 'rel_islamic', 'animist': 'rel_animist',
       'sunni': 'rel_islamic', 'shia': 'rel_islamic', 'ibadi': 'rel_islamic', 'wahhabi': 'rel_islamic', 'zaydi': 'rel_islamic',
       'indigenous': 'rel_animist', 'polynesian': 'rel_animist', 'oriental': 'rel_orthodox', 'theravada': 'rel_buddhist',
       'confucian': 'rel_buddhist', 'shinto': 'rel_buddhist', 'vodou': 'rel_catholic', 'nonconformist': 'rel_nonconformist'}


def faction_rel(religion):
    """factions.json religion string -> rel_* key, by its first word that REL knows ('sunni_islam', 'catholic_vodou')."""
    for w in religion.lower().replace('-', '_').split('_'):
        if w in REL:
            return REL[w]
    raise KeyError(religion)


def targets(keys):
    """({faction: rel_*} for every non-vanilla faction, {region: {rel_*: share}} for regions.json regions in keys)."""
    F = json.load(open(os.path.join(DATA, 'factions.json')))
    R = json.load(open(os.path.join(DATA, 'regions.json')))
    return ({f['key']: faction_rel(f['religion']) for f in F if not f.get('vanilla')},
            {r['key']: r['religion'] for r in R if r['key'] in keys})


GOV = {'republic': ('gov_republic', 'netherlands')}   # factions.json government -> (gov key, vanilla faction to copy)


def government(sp):
    """GOV's types for the new factions (gov_republic: united_states) -> {faction: gov key}."""
    F = json.load(open(os.path.join(DATA, 'factions.json')))
    want = {f['key']: GOV[f['government']] for f in F if not f.get('vanilla') and f['government'] in GOV}
    fa = {lpb.fkey(it[0]): it[0] for it in next(cm._iter_recs(sp.root, 'FACTION_ARRAY')).items}
    done = {}
    for k, (gk, src) in want.items():
        if k not in fa:
            continue
        g, s = fa[k].find('GOVERNMENT'), fa[src].find('GOVERNMENT')
        assert g.children[1].value == 'gov_absolute_monarchy' and s.children[1].value == gk, (k, g.children[1].value)
        g.children[1] = esf.Val(g.children[1].tag, gk)
        g.find('GOV_IMP').items = copy.deepcopy(s.find('GOV_IMP').items)
        done[k] = gk
    return done


def _region_key(r):
    return next(c.value for c in r.children if isinstance(c, esf.Val) and c.tag in (0x0e, 0x0f))


def apply(sp, facs, regions):
    """facs {faction: rel_*} (factions not in the startpos skipped), regions {region: {rel_*: share}}."""
    n = collections.Counter()
    for it in next(cm._iter_recs(sp.root, 'FACTION_ARRAY')).items:
        want = facs.get(lpb.fkey(it[0]))
        if want:
            def fx(kids, j, v):
                if v.tag in (0x0e, 0x0f) and isinstance(v.value, str) and v.value.startswith('rel_'):
                    kids[j] = esf.Val(v.tag, want); n['faction strings'] += 1
            lp.walk_vals(it[0], fx)
            n['factions'] += 1
    for r in cm.first_rec(sp.root, 'REGIONS_ARRAY').items:
        mix = regions.get(_region_key(r[0]))
        if mix is None:
            continue
        rb = next(cm._iter_recs(r[0], 'RELIGION_BREAKDOWN'))
        have = [it[0].value for it in rb.items]
        assert len(have) == 9 and set(mix) <= set(have), (have, mix)
        rb.items = [[k, esf.Val(v.tag, float(mix.get(k.value, 0.0)))] for k, v in rb.items]
        n['regions'] += 1
    assert n['regions'] == len(regions), (n, len(regions))
    return dict(n)


def check(path):
    sp = esf.load(path)
    for it in next(cm._iter_recs(sp.root, 'FACTION_ARRAY')).items:
        got = collections.Counter()
        lp.walk_vals(it[0], lambda kids, j, v: got.update([v.value]) if v.tag in (0x0e, 0x0f) and isinstance(v.value, str)
                     and v.value.startswith('rel_') else None)
        print('faction', lpb.fkey(it[0]), dict(got), it[0].find('GOVERNMENT').children[1].value)
    for r in cm.first_rec(sp.root, 'REGIONS_ARRAY').items:
        rb = next(cm._iter_recs(r[0], 'RELIGION_BREAKDOWN'))
        print('region', _region_key(r[0]), {k.value[4:]: round(v.value, 2) for k, v in rb.items if v.value})


if __name__ == '__main__':
    if sys.argv[1:2] == ['check']:
        check(sys.argv[2])
    else:
        sys.exit(__doc__)
