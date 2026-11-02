# 10 - Adding ONE new land region (+ settlement, optional port) to mp_eur_napoleon

Gates Phase 5 (~156 non-European land regions). Extends research/09 section 3 (db tables, loc keys,
map-file list, REGION outline) - those are not repeated; this doc gives the exact cross-file id
plumbing, traced on the vanilla template **eur_ireland** (1 area, 1 settlement, 1 town, 1 port, 1 resource).

Tags: **[V]** verified by reading the files (vanilla mp_eur_napoleon loose startpos, vanilla
regions/pathfinding/poi/sea_grids/trade_routes.esf, db/loc, europe_lookup.tga, scripts in /tmp/r10).
**[I]** inferred, not yet verified in game.

---

## 1. Identifier systems (the whole problem in one table)

| Id system | Where it lives | Kind | Rule for a new region |
|---|---|---|---|
| region **key** `eur_ireland` | everywhere (db, loc, all esf, startpos strings) | string, free | new unique key; prefix free [V] (09) |
| **regions.esf region index** (Ireland = 75 of 101) | regions.esf `regions` order; = CAI_WORLD_REGIONS item order; = target of pathfinding `region_indices` | **dense, positional** | **append only** (tools/regions_world.py already keeps 0..100 and appends) [V] |
| **pathfinding local region ref** (Ireland = 56) | pathfinding grid_data `region_indices` i16[] (72 entries, one per *passable* region) | dense, positional | append; bump `passable_region_count` and `listed_region_count` [V] |
| **path domain id** (10-bit trait path_id) | pathfinding traits + startpos CAMPAIGN_PATHFINDER arrays (len 222) | **dense, ordered by class**: singletons 0..71, sea 72, composites 73..221, 1023 off-map | inserting a singleton **shifts sea and all composites by +1** [V] |
| **pass_group id** | regions.esf `pass_group`, CAI_SITUATED[4], CAI_REGION_HLCI[1], CAI_FACTION[2], poi `area` field | dense small ints | append a new id for a new isolated landmass (Ireland pg 3) [V]; ordering semantics (passable < impassable?) unknown [I] |
| **slot-key suffix** `settlement_1_slot:1` | regions.esf slot_descriptions key | = index in the region's `slot_descriptions` list (0 mismatches over all regions) [V] | renumber when cloning |
| **region handle** (Ireland 861265044) | startpos REGION[4], GOVERNORSHIP[2], CAI_REGION[11] | free u32 | allocate unused value [I: uniqueness is the only observed constraint] |
| **other handles**: settlement 604659604, slot handles, gov 739282900, recruitment mgr 638071812, faction 748414436, army 612174564 | startpos | free u32 | allocate values absent from the whole file; vanilla range ~6e8..8.6e8 [V range, I rule] |
| **CAI id** (Ireland region 579, settlement 1381) | every CAI_* table, BDI pools | free u32, globally unique, **each table sorted ascending** | take from `CAI_CENTRAL_BDI_POOL[0]` (= next id, 40333; max used 40332), bump it, insert into tables in ascending position [V] |
| **loc suffix** `...settlement:eur_ireland:dublin1584883816` | SETTLEMENT/CAMPAIGN_LOCALISATION + loc key | free int, unique per settlement (72 distinct) [V] | any unused int [I] |
| **trade port index** (Ireland waterford = 30) | trade_routes.esf PORTS order; startpos CAMPAIGN_TRADE_MANAGER PORT_INDICES | dense 0..P-1 | append [V] |
| **trade settlement index** (Ireland 64 = 39+25) | trade_routes.esf SETTLEMENTS order; startpos SETTLEMENT_INDICES = P + idx | dense, offset by port count | appending a port shifts every settlement index +1 [V] |
| **trade node index** (111..129) | TRADE_NODES[1], DOMESTIC_TRADE_ROUTE[6]/[7], startpos node routes | dense, offset P+S | appending a port or settlement shifts all node indices [V] |
| **sea_grid cell k** | sea_grids.esf cells | dense grid | unchanged; only cell contents change [V] |
| **lookup palette index** (Ireland 252 = RGB 151,101,103) | `<theatre>_lookup.tga` | P-mode palette, 256 entries | colour = db `regions_tables` RGB [V]; 8-bit palette limit is a Phase 5 problem (see 7) |

**Correction to research/08**: the trade "ordering differs" note is wrong in substance - startpos
PORT_INDICES / SETTLEMENT_INDICES *values* equal trade_routes.esf indices exactly; only item order
differs [V].

---

## 2. Per-file checklist (template: eur_ireland)

### 2.1 db (pack) - see 09 3.1 for table list [V]

| Table | Ireland row | New row derivation |
|---|---|---|
| regions_tables | `eur_ireland cont_europe 151 101 103 Ireland` | key, continent, **unique RGB** (must match lookup TGA if one is shipped), name |
| campaign_map_settlements | `settlement:eur_ireland:dublin eur_ireland Dublin 1 settlement` | `settlement:<region>:<name>`, slot_count N |
| campaign_map_towns_and_ports | `town:eur_ireland:cork town-commercial Cork`, `port:eur_ireland:waterford port Waterford` | optional; one row per town/port slot |
| campaign_map_slots | `wheat:eur_ireland:connemara eur_ireland wheat 0 \N` | optional; one per resource slot |
| groupings_tables | `region_ireland` | optional [V present, I unused by campaign] |

slot_count -> regions.esf settlement slots [V]: 1 -> 1x `settlement_1_slot`, 2 -> 2x `settlement_2_slot`,
3 -> 3x, 4 -> 4x, 5 -> 4x `settlement_4_slot`. **Probe: use slot_count 1.**

### 2.2 loc (type-2 pack local_en_gn.pack only, research/00) [V]

- `regions_onscreen_<region>`, `regions_battle_name_<region>`
- `start_pos_settlements_onscreen_name_settlement:<region>:<name><suffix>` (suffix = int in the SETTLEMENT CAMPAIGN_LOCALISATION)
- `start_pos_regions_rebel_faction_name_<region>mp_eur_napoleon` (Ireland = "Irish Revolutionaries")
- optional: `campaign_map_towns_and_ports_onscreen_name_<slotkey>`, `campaign_map_slots_onscreen_<slotkey>`

Use `world_build.loc_rows`/`localisation()` (already merges into local_en_patch).

### 2.3 regions.esf [V]

Append one region item (index = current count; 139 in the zones build, 101 in the plain build):
- kind land, its areas (polygon from `regions_model.area_polygons` style), new pass_group id
  (append to `pass_group`, and to nonwalk/landmass lists as regions_world.py does), bounds,
  connectivity/query_info rebuilt by the existing regions_world pipeline.
- Region item `[5]` i32 0, then `settlement_and_slots`: settlement position (world units),
  footprint `xy[]` (Ireland 112 values = 56 points), `slot_descriptions` in Ireland's order:
  `road:0`, `settlement_1_slot:1`, `fortification:2`, `wheat:3`, `town:4` (model nap_eur_town_com),
  `port:5` (model nap_eur_port, angle 62102, separate 2D dock xy + sea footprint).
  Suffix = position. **Probe: road / settlement_1_slot / fortification only.**
- Theatre `region_keys` (under `theatre`): append (key, settlement xy); list is not in index order, so
  position is free [V].
- If the polygon is carved from `eur_map_west/east` filler, that filler region's polygon must lose the
  same area (shared edges must match or pathfinding welding breaks - memory/pathfinding-welding).

### 2.4 pathfinding.esf [V structure, I for generator details]

Ireland: local ref 56, singleton domain 55, 255 uniform cells `Trait(0, 69649, 255, 55)` with costs8 `0x1f`x8.
1. Append the new regions.esf index to `region_indices`; `passable_region_count` and `listed_region_count` +1 (72 -> 73).
2. Path domains: insert singleton at id 72 (before the sea separator). Renumber **every trait with
   path_id >= 72 by +1** (sea 72 -> 73, composites 73..221 -> 74..222). 1023 untouched.
   `tools/pf_gen.py` and `probe_g3.py` hard-code `SEA = Trait(1, 69649, 255, 72)` - must become 73.
3. Convert the region's cells (currently sea/OFF outside VT) to land traits:
   uniform cells `Trait(0, 69649, 255, 72)`, costs8 0x1f. Border cells against sea need kind 6/7
   traits like vanilla coast cells (singleton kinds seen: 0, 6, 7) [V kinds, I exact recipe];
   simplest probe: an **inland-only rectangle or polygon whose border cells are fully land or fully sea
   and do not touch another land region** -> no composite domain needed.
4. Run `tools/pf_check.py` (welding must be 0 mismatches).
5. Startpos `CAMPAIGN_PATHFINDER/PATHFINDING_GRID[0]` leaf 8 `bool[222]` and leaf 11 `f32[222]` are
   per-domain: insert one entry at index 72 (True, 0.6667 - the vanilla majority value) -> length 223 [I].
6. Capacity: path_id is 10 bits, 1023 reserved -> <= 1023 domains. 228 singletons + sea + ~470
   composites fits [V arithmetic, I composite count].

### 2.5 poi.esf [V]

Ireland has 62 nodes (kind 2 x26, 7 x19, 5 x13, 1 x2, 3 x1, 4 x1). The single **kind-4 node sits at the
settlement xy** with neighbors into the adjacent sea nodes. The `area` field is pass_group space
(74% = containing area's pass_group, rest a nearby area's). Probe: one kind-4 node at the settlement
(region = new index, area = new pass_group) plus a few kind-2 land nodes linked to it; rebuild
neighbors / edge_idx via `campaign_misc` writers [I minimum].

### 2.6 sea_grids.esf [V]

Ireland's key appears in the land lists of cells 22, 33, 34 and its port in cell 34's port list.
Add the key to every cell it overlaps (only matters if coastal); add port only with a port slot.
Inland probe: no change [I].

### 2.7 trade_routes.esf + startpos CAMPAIGN_TRADE_MANAGER [V]

- Settlement: append to `SETTLEMENTS` and to startpos `SETTLEMENT_INDICES` (value = P + new index).
  This shifts every trade node index (P+S+k) by +1 -> renumber TRADE_NODES[1],
  DOMESTIC_TRADE_ROUTE[6]/[7], the 741 node routes in startpos TRADE_ROUTES (1653 = 912 esf ROUTES +
  741 node routes).
- Port: append to `PORTS` + `PORT_INDICES`; shifts every settlement *and* node index by +1.
- Probe variant A: register the settlement (required renumber). Variant B: omit it entirely and test
  whether a settlement absent from trade data is tolerated [I - unknown].

### 2.8 Lookup TGA [V facts, I need]

`europe_lookup.tga` is P-mode 605x300 over the *vanilla* theatre rect, 85 palette indices used
(72 regions + 13 non-region, sea 225, black 255). The world build already ships the vanilla lookup
under a changed theatre and loads, so the lookup is not read for correctness of new regions [I].
Probe: leave it alone. Phase 5: >243 regions cannot fit an 8-bit palette - lookup must be
abandoned or proven unused.

### 2.9 Display (optional for probe) [V]

borders `borders/<region>_<n>.rigid_spline` (`border:<region>:<n>`, coords world/40), roads optional,
world.markers OVERLAY decals keyed by `region:slot` names optional. metadata.dat: sea/land codes only,
nothing per-region.

### 2.10 Startpos WORLD records (non-CAI) [V]

Clone Ireland's REGION (REGIONS_ARRAY item; array has its own order, Ireland = item 1; append):

| Leaf | Ireland | New value |
|---|---|---|
| [0] | `eur_ireland` | new key |
| [1] POPULATION | 5650000 / 11300000, catholic .7 protestant .3 | any plausible |
| [3] REGION_SLOT_MANAGER | slots, see below | rebuilt for new slots |
| [4] | 861265044 | **new region handle** |
| [5] SETTLEMENT | see below | rebuilt |
| [9..15] | 900,1000,1000,200,200,200,-5 | copy |
| [20] | britain 748414436 | **owner FACTION handle** |
| [21] LINE_OF_SIGHT | | copy, then regridded by `cm.regrid_visibility` [I] |
| [22] | 739282900 | **owner governorship handle** |
| [23] | `europe` | theatre name used by build (`europe`) |
| [24] | `ireland` | rebel/emergent faction key: a dormant FACTION_ARRAY key or a db `is_rebel` faction (e.g. `french_rebels`, no FACTION record) |
| [25] | `Irish Revolutionaries` | rebel display name (also loc key above) |
| [26] | `sc_european_west` | subculture |
| [27] REGION_RECRUITMENT_MANAGER | handle 638071812 | new handle |
| [28]..[33] | True, u32[8]x4, bool[20] | copy |
| [37] RESOURCES_ARRAY `global`, [38] '', [39] 10, [40] 3079353058 (constant in all 72), [42] f32 0 | | copy |
| [41] CAMPAIGN_LOCALISATION | `regions_onscreen_eur_ireland` | `regions_onscreen_<new>` |

REGION_SLOT (v3) per slot: SIEGEABLE_GARRISON_RESIDENCE / GARRISON_RESIDENCE `[0]` owner handle,
`[1]` slot handle; BUILDING_MANAGER/BUILDING (100, building key, owner faction **key string**, gov type);
`[2]` slot handle, `[3]` slot key (must equal the regions.esf slot_descriptions key), `[6],[7]` fixed
position (i32/2^20 world); `[8..14]` type flags - settlement `(0,3,False,1,1,0xFFFFFFFF,0)`,
town `(0,1,True,1,1,-1,2)`, port same + REGION_RECRUITMENT_MANAGER + PORT_GARRISON_MANAGER (19 fields),
resource `(1,0,False,0,2,0|-1,0)`. ROAD_SLOT / FORTIFICATION_SLOT are `[True, REGION_SLOT]`.

SETTLEMENT: SIEGEABLE_GARRISON_RESIDENCE (owner handle, settlement handle, x/y at [10],[11],
**[12] garrison ARMY handle** - **0 is valid**: 16 of 72 vanilla settlements have 0, e.g. eur_finland,
eur_corsica [V]), LINE_OF_SIGHT, CAMPAIGN_LOCALISATION (settlement loc key + suffix), level 3
(all 72 are 3 [V]), key x2, handle.

Also:
- CAMPAIGN_PREOPEN_MAP_INFO / REGION_OWNERSHIPS_BY_THEATRE `europe_main`: append (key, owner key) [V].
- CAI_HISTORY event strings mentioning regions: cosmetic, skip [V present, I harmless].

---

## 3. Ownership

### 3.1 Where ownership lives [V]

Ownership is **not** a list on the FACTION record. It is the set of:
1. REGION[20] owner faction handle, and every GARRISON_RESIDENCE owner handle in the region's slots
   and settlement, and BUILDING owner-key strings;
2. **GOVERNORSHIP**: `FACTION/GOVERNMENT/POSTS_ARRAY/CHARACTER_POST 'governor_<theatre>'/GOVERNORSHIP`
   = `[1]` gov handle, `[2]` u32[] region handles, `[3]` owner faction handle. 23 governorships cover
   all 72 regions, each exactly once. FACTION holds a u32[] of its governorship handles directly after
   MORGUE (britain `[739282900]`). REGION[22] points back at the governorship;
3. REGION_OWNERSHIPS_BY_THEATRE (preopen UI info);
4. CAI: CAI_SETTLEMENT OWNED_DIRECT -> CAI_FACTION, CAI_FACTION[0] region CAI ids,
   CAI_GOVERNORSHIP[3] region CAI ids (section 4).

### 3.2 Owned by an existing faction (probe choice) [V template]

Set REGION[20] + all residence owners = britain handle, BUILDING owner keys = `britain`,
REGION[22] = 739282900, append the new region handle to that GOVERNORSHIP[2], add to
REGION_OWNERSHIPS_BY_THEATRE. No new faction, character or post records.

### 3.3 Rebel / neutral-owned [I - no vanilla precedent]

Every region is owned at start in both mp_eur and eur_napoleon; no region references the rebel
faction [V]. WORLD/REBEL_FACTION/FACTION is handle 747903428, empty key, **no GOVERNMENT** (so no
governorship to list the region in), CAI_FACTION id 792 with no regions [V]. Minimal attempt:
REGION[20] = 747903428, REGION[22] = 0, residences owner 747903428, building owner key `rebels`?
(unknown string). High crash risk; do not use for the first probe.

### 3.4 Owned by a new faction (on top of 3.2)

Everything in research/09 section 2 (FACTION record, db/loc/UI assets, CAI_FACTION), plus:
a GOVERNMENT with a `governor_<theatre>` CHARACTER_POST + GOVERNORSHIP (new gov handle, region
handles, faction handle), the gov handle in the FACTION post-MORGUE u32[], a governor character
(CAI_GOVERNORSHIP[2] references character CAI id 2601 for Ireland's) [V shape], a capital
(CAI_FACTION[5]/[36]) [V]. Simplest path: activate a **dormant** FACTION_ARRAY nation (e.g. `ireland`:
no posts, empty gov list, 0 chars, 0 armies [V]) and give it a governorship - still needs a GOVERNMENT
post and a character [I].

---

## 4. CAI tables: what must change vs what can stay stale

Facts: CAI tables are post-load fixed up in this order (exe strings): Theatres, Factions, Regions,
Region Boundaries, Settlements, Building Slots, Region Slots, Trading Posts, Resource Mobiles, Units,
Characters, Forts, Time, Trade Routes, Trade Route Segments, Technology Trees, Governorships,
Transition Areas, Region HLCIs, History [V]. Vanilla CAI at 101 regions + regions.esf at 139 **loads**
(zones run with plain startpos) [V research/00]. The world_zones CAI additions crash
(null deref `napoleon+0x96d9e0 mov eax,[ecx+0x10c]`, caller 0xC3FD30) and are being bisected via
`tools/world_zones.py` `stages` [V].

Ireland's CAI footprint [V]:

| Record (id) | Content |
|---|---|
| CAI_REGION 579 | header OWNED_INDIRECT=1381 + BDI beliefs; [0] theatre [28], [1] HLCI [580], [2] settlement 1381, [3] region-slot ids [1383,1385,1387], [4],[5] f32 settlement xy, [7] boundaries [3535,3700,3701,3743], [8] True, [9] mobiles [2560], [10] key, [11] region handle, [12] governorship 3825 |
| CAI_SETTLEMENT 1381 | OWNED_DIRECT 675 (CAI_FACTION britain); CAI_SITUATED (x, y, region 579, [28], pass_group 3); CAI_GARRISONABLE[0] 2560 (0 in the 16 garrison-less settlements); [0] building slots [1378,1379,1380]; [2] settlement handle |
| CAI_BUILDING_SLOT | [0] slot handle, [1] kind (settlement/prestige 0, road/fort 1, town 2, port 3, gold/iron 4, wheat/wine 5, pasture/timber 6), [2] owner (CAI settlement or CAI region slot) |
| CAI_REGION_SLOT | [0] 1, [1] building slot id, [5] bool (True = port, then CAI_SITUATED on dock xy, sea region 522, pass_group 6) |
| CAI_REGION_HLCI 580 | (579, pass_group 3, [area idx 0], settlement xy) |
| CAI_REGION_BOUNDARY 3535 etc. | (a region id, b region id, f32 2x shared length, u32 0) |
| CAI_GOVERNORSHIP 3825 | OWNED_DIRECT 675; [0] gov handle, [1] 28, [2] character 2601, [3] region ids [579,614,524,584,106] |
| CAI_FACTION 675 britain | [0] region ids sorted, [1] theatres, [2] pass groups [4,3], [3] mobiles, [4] characters, [5] capital 524, [6] faction handle, [10] governorships [3825], [36] capital |
| CAI_WORLD_REGIONS | 101 items in regions.esf index order (Ireland at 75) |
| global BDI analysers | REGION_OCCUPANCY (101 beliefs), BORDER_PATROL (per region id), BASIC_REGION_GROUP_REGION (72, per settlement) |

Classification [I unless stated]:

| Table | Verdict | Reason |
|---|---|---|
| CAI_WORLD_REGIONS, CAI_REGION, CAI_REGION_HLCI, CAI_REGION_BOUNDARY, CAI_SEA_GRID_CELL, THEATRE region/sea lists | **can stay stale** | proven by the 139-region zones run [V]; new regions simply have no CAI shadow |
| global BDI analyser beliefs | stale | regenerable beliefs |
| CAI_SETTLEMENT / CAI_BUILDING_SLOT / CAI_REGION_SLOT | **probably stale-OK for probe, unproven** | an owned settlement with no CAI shadow is the main unknown; the AI may look it up by handle when the owner acts on it (siege, construction). Test in probe A; add in probe B |
| CAI_FACTION[0], CAI_GOVERNORSHIP[3] | must update **only if** the CAI_REGION for the new region exists (they hold CAI ids, not handles) | consistency |
| CAI_CENTRAL_BDI_POOL[0] | must bump if any CAI id is allocated | id allocator [V] |
| CAI_SITUATED pass_group on existing objects | unchanged | new pass_group only used by new objects |

---

## 5. Minimal first in-game probe

Goal: one inland region in North America, owned by Britain, settlement only, vanilla CAI.

**Base**: plain `tools/world_build.py` (no `--zones`; vanilla 101-region regions.esf + filler, plain
startpos with vanilla CAI, obstacles emptied). Choose a polygon inside `eur_map_west` filler that is
landlocked by sea/off-map cells only (e.g. an island-like block on the North American landmass with
coast on all sides is ideal: no composite domains, no land neighbours).

Edit sequence:
1. **regions.esf**: carve the polygon from `eur_map_west`; append region `nam_probe` (index 101 /
   after zones), kind land, new pass_group id (append), settlement_and_slots with
   `road:0`, `settlement_1_slot:1`, `fortification:2` cloned from Ireland and translated; append to
   theatre `region_keys`.
2. **db** (mod pack): `regions_tables` (unique RGB), `campaign_map_settlements`
   `settlement:nam_probe:probetown nam_probe Probetown 1 settlement`.
3. **loc** (type-2 pack): regions_onscreen, regions_battle_name, settlement onscreen (with chosen
   suffix), rebel_faction_name ...mp_eur_napoleon.
4. **pathfinding.esf**: cells inside polygon -> `Trait(0,69649,255,72)` costs 0x1f (coast cells copy
   a vanilla coast recipe); renumber traits path_id >= 72 by +1 (SEA -> 73); append region_indices;
   counts 72 -> 73; `pf_check.py` = 0.
5. **startpos**: clone Ireland REGION -> new key/handles/positions/loc key; owner britain at [20] and
   all residences; [22] = 739282900; SETTLEMENT[12] = 0 (no garrison, as eur_finland); slot manager
   with the 3 slots only; append handle to Britain GOVERNORSHIP[2]; append to
   REGION_OWNERSHIPS_BY_THEATRE; insert True / 0.6667 at index 72 of PATHFINDING_GRID leaves 8/11.
6. **trade**: append settlement to trade_routes.esf SETTLEMENTS + startpos SETTLEMENT_INDICES;
   renumber trade nodes +1 in both files.
7. **poi**: one kind-4 node at the settlement + a few kind-2 nodes (region 101, area = new pg).
8. sea_grids, lookup TGA, borders, CAI: **unchanged**.
9. Run, load Coalition as Britain: check settlement visible/clickable, region name, end turn x3
   (AI turn = pathfinding/CAI stress), move an army there if reachable by sea.
10. If A crashes: drop step 6 (variant), then drop the CAI concern by adding CAI_SETTLEMENT /
    BUILDING_SLOTs / CAI_REGION / HLCI / governorship+faction list entries with ids from
    CAI_CENTRAL_BDI_POOL (probe B), each stage separately (reuse world_zones `stages` bisection).

---

## 6. Open questions only the game can settle

1. Does an owned settlement with **no CAI_SETTLEMENT/CAI_REGION shadow** survive the AI turn and
   player interaction (construction, siege)? (Probe A vs B.)
2. Root cause of the world_zones CAI crash (`mov eax,[ecx+0x10c]`) - determines whether CAI shadows can
   be added at all (bisect in progress).
3. Is a settlement **absent from trade_routes.esf / SETTLEMENT_INDICES** tolerated?
4. Meaning of PATHFINDING_GRID leaf 8 bool[] / leaf 11 f32[] (0.6667 vs Austria 0.5), and whether a
   length mismatch with the domain count crashes.
5. Can a region start **rebel-owned** (REBEL_FACTION has no GOVERNMENT)?
6. Is the lookup TGA read for new regions at all (click selection, tooltips)?
7. pass_group numbering rules (must passable ids precede impassable ones?).
8. Land border recipe: are composite domains required on a shared land border, or can borders be
   cell-aligned with singleton-only domains (much simpler generator for 156 regions)?
9. Coast trait recipe (kinds 6/7, middle20, contact_mask) needed for armies to embark/disembark.
10. Is a garrison-less, CAI-less region still capturable by the AI (needs probe 2 with an enemy army).
