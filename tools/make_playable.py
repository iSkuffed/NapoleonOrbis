#!/usr/bin/env python3
"""Mark factions selectable on the Coalition (mp_eur_napoleon) faction screen.
  python tools/make_playable.py IN.esf OUT.esf key [key ...]
Per key: FACTION_INFOS bools (+0x18,+0x19) True and a ListOrder; PLAYERS_ARRAY bool +0xa9 True in both
CAMPAIGN_PLAYERS_SETUP copies; a VICTORY_CONDITION_OPTIONS entry cloned from britain (REGION_KEYS emptied).
Keys not listed keep their flags (the vanilla 4 stay playable; france stays off unless the exe branch is patched)."""
import copy, sys
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import esf
from esf import Val

src, dst, keys = sys.argv[1], sys.argv[2], sys.argv[3:]
e = esf.load(src)
pre = e.root.find('CAMPAIGN_PREOPEN_MAP_INFO')
fi = {it[0].value: it for it in pre.find('FACTION_INFOS').items}
missing = [k for k in keys if k not in fi]
assert not missing, f'not in FACTION_INFOS: {missing}'
order = max(it[4].value for it in fi.values())
for k in keys:
    it = fi[k]
    it[2], it[3] = Val(0x01, True), Val(0x01, True)
    order += 1
    it[4] = Val(0x04, order)
setups = [pre.find('CAMPAIGN_PLAYERS_SETUP'), e.root.find('CAMPAIGN_ENV').find('CAMPAIGN_SETUP').find('CAMPAIGN_PLAYERS_SETUP')]
for cps in setups:
    for it in cps.find('PLAYERS_ARRAY').items:
        s = it[0]
        if s.children[2].value in keys:
            s.children[4] = Val(0x01, True)          # 2nd bool after the key = struct +0xa9 "playable"
vco = pre.find('VICTORY_CONDITION_OPTIONS')
have = {it[0].value for it in vco.items}
tpl = next(it for it in vco.items if it[0].value == 'britain')
for k in keys:
    if k in have:
        continue
    new = [Val(0x0e, k), copy.deepcopy(tpl[1])]
    for blk in new[1].items:
        blk[0].find('REGION_KEYS').items = []
    vco.items.append(new)
open(dst, 'wb').write(esf.dumps(e))
print('ok', len(keys), 'factions; ListOrder up to', order)
