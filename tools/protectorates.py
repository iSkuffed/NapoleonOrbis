"""Turn-1 protectorates in the startpos (pt_w11): copy of vanilla egy_napoleon's egy_ottomans -> egy_mamelukes encoding.

A protectorate is three startpos edits, nothing else in egy_napoleon references the pair:
  patron's DIPLOMACY_RELATIONSHIP toward the protectorate: state 'patron' (fields below),
  protectorate's DIPLOMACY_RELATIONSHIP toward the patron: state 'protectorate',
  protectorate's FACTION: the patron's handle in the i32 right after the 2nd CAMPAIGN_BONUS_VALUES (0 = none).
Attitude entries 1 and 5 of both relationships get the vanilla pair's values; the rest of the attitudes stay.

    python tools/protectorates.py check STARTPOS_OR_SAVE      # report the pairs
"""
import sys

import esf
import campaign_misc as cm
import land_probe_b as lpb

PAIRS = [('russia', 'russian_american_company'), ('britain', 'east_india_company')]
# DIPLOMACY_RELATIONSHIP v14 child index -> value (egy_napoleon egy_ottomans -> egy_mamelukes)
PATRON = {2: True, 3: -1, 4: 'patron', 5: 0, 6: 20, 7: 0, 8: 0, 9: 661, 10: 0, 11: 0, 12: 0, 13: 0, 15: 10, 16: 0,
          19: 1, 20: 'patron', 21: True, 22: True, 23: 45, 24: -1, 25: 0, 26: 0, 27: 0, 28: True}
PROTECTORATE = {**PATRON, 4: 'protectorate', 20: 'protectorate', 8: 661, 9: 0}
ATTITUDES = {1: [1, 30, 80, True, 0, False], 5: [1, 15, 60, True, 0, False]}


def _factions(sp):
    return {lpb.fkey(x[0]): x[0] for x in next(cm._iter_recs(sp.root, 'FACTION_ARRAY')).items}


def _rel(f, other_h):
    arr = f.find('DIPLOMACY_MANAGER').find('DIPLOMACY_RELATIONSHIPS_ARRAY')
    r = [it[0] for it in arr.items if it[0].children[0].value == other_h]
    assert len(r) == 1, (lpb.fkey(f), other_h, len(r))
    return r[0]


def _protector_idx(f):
    cb = [i for i, v in enumerate(f.children) if isinstance(v, esf.Rec) and v.name == 'CAMPAIGN_BONUS_VALUES']
    assert len(cb) == 2 and f.children[cb[1] + 1].tag == 0x04, (lpb.fkey(f), cb)
    return cb[1] + 1


def _set(rel, fields):
    assert rel.version == 14, rel.version
    for i, v in fields.items():
        old = rel.children[i]
        assert isinstance(old, esf.Val) and type(old.value) is type(v), (i, old, v)
        rel.children[i] = esf.Val(old.tag, v)
    att = rel.children[1]
    assert att.name == 'DIPLOMACY_RELATIONSHIP_ATTITUDES_ARRAY' and len(att.items) == 24, att.name
    for j, vals in ATTITUDES.items():
        it = att.items[j]
        assert len(it) == len(vals)
        att.items[j] = [esf.Val(o.tag, v) for o, v in zip(it, vals)]


def apply(sp, pairs=PAIRS):
    F = _factions(sp)
    for p, c in pairs:
        _set(_rel(F[p], lpb.fhandle(F[c])), PATRON)
        _set(_rel(F[c], lpb.fhandle(F[p])), PROTECTORATE)
        F[c].children[_protector_idx(F[c])] = esf.Val(0x04, lpb.fhandle(F[p]))
    return [f'{c} protectorate of {p}' for p, c in pairs]


def state(sp, a, b, F=None):
    F = F or _factions(sp)
    return _rel(F[a], lpb.fhandle(F[b])).children[4].value


def check(sp, pairs=PAIRS):
    """[(pair, ok, detail)]: both states, the protector field, and patron/protectorate at peace with each other's partner."""
    F = _factions(sp)
    fh = {lpb.fhandle(v): k for k, v in F.items()}
    out = []
    for p, c in pairs:
        st = (state(sp, p, c, F), state(sp, c, p, F))
        pr = fh.get(F[c].children[_protector_idx(F[c])].value)
        out.append((f'{c} protectorate of {p}', st == ('patron', 'protectorate') and pr == p, (st, pr)))
    ks = sorted({k for pc in pairs for k in pc})
    war = [(a, b) for a in ks for b in ks if a != b and state(sp, a, b, F) == 'war']
    out.append((f'no war among {ks}', not war, war))
    return out


if __name__ == '__main__':
    assert sys.argv[1] == 'check', __doc__
    rows = check(esf.load(sys.argv[2]))
    for name, ok, d in rows:
        print('OK  ' if ok else 'FAIL', name, d)
    sys.exit(0 if all(ok for _, ok, _ in rows) else 1)
