# 09 - Per-faction and per-region data requirements (NTW eur_napoleon)

Scope: exact checklist of what must exist for each NEW faction and each NEW region so a generator can emit it. Evidence is local only. Tags: [L] verified in local files, [I] inferred, [?] unknown / needs in-game test (game launch is not allowed for this task).

Method: db tables decoded via RPFM `schema_nap.ron` into `work/scratch_db/tsv/*_tables.tsv`; loc from `local_en.pack` + `local_en_patch.pack` into `work/scratch_db/localisation.tsv`; pack file lists in `work/scratch_db/list_*.txt`; startpos (`data/campaigns/eur_napoleon/startpos.esf`, 32 MB, v5 ABCE) unpickled to `work/scratch_db/eur.pkl`; dumps `denmark_faction.txt`, `den2.txt`, `denreg.txt` (denmark FACTION / REGION records).

Vanilla scale for reference: `factions_tables` 77 rows (all campaigns), `regions_tables` 159 rows (128 cont_europe + 31 cont_middle_east, all campaigns), eur startpos uses 72 regions / 41 factions. [L]

---

## 1. Join model (read first)

- Everything joins by STRING key (`factions.key`, `regions.key`, `settlement_id`, `slot_id`, `town_id`). The faction `index` column (int32, e.g. denmark 5, belgium 1322886196) never appears in the startpos; it is just a unique id (vanilla mixes small ints and random int32s). [L]
- Startpos stores the keys as UTF-16 strings plus runtime object handles (i32/u32 ids like 615211060 for the denmark faction, 865658036 for the region). Handles are internal to the startpos; a generator must allocate its own unique handles and keep cross-references consistent. [L]
- A region's colour (`regions_tables` r,g,b) must match a palette entry in `europe_lookup.tga` exactly (see 03-engine-limits-and-db.md). [L]

---

## 2. Q1 - per-FACTION checklist

### 2.1 Minimal "dormant minor" set (template: `belgium`, `brittany`, `catalonia`)

Belgium appears in exactly these 9 db tables (grep of all decoded tsv) and has exactly 4 loc keys. Anything beyond this is optional polish. [L]

| # | Table | Rows per faction | Belgium example / what | Clone or unique |
|---|-------|------------------|------------------------|-----------------|
| 1 | `factions_tables` (v3) | 1 | `belgium 1322886196 sc_european_west minor ... skin=usa ... icon_path_units=data\ui\units\icons\belgium flags_path=data\ui\flags\belgium republican_flag_path=\N same_gov_type_revolution_flag_path=data\ui\flags\rebels_europe, colours 0.0 (all 12 colour cols), military_group=united_provinces_group, settler_rebellion_faction=austrian_rebels, audio_faction_string=Du, name groups names_dutch, attack_desc/defend_desc strings` | key, index, screen_name, screen_adjective, attack/defend text, flag/icon paths UNIQUE; subculture, category, skin, name_group, military_group, settler_rebellion_faction, audio string, rebel colours CLONE from a similar existing faction |
| 2 | `cdir_faction_junctions` | 1 | `denmark	denmark` (key,faction; `all	\N` is the global row) | unique row, trivially generated (campaign AI director link) |
| 3 | `faction_uniform_colours` | 1 | `denmark 214 38 38 54 54 54 54 55 127` (primary, secondary, tertiary RGB) | unique RGB, free choice |
| 4 | `uniforms` | 1 per unit the faction can field | `Denmark_Art_Foot_12_lber	denmark	Denmark_Art_Foot_12_lber	Art_Foot_12_lber` (uniform_name, faction, filename, unit). Belgium 13 rows, denmark 21 | CLONE: `filename` may point at ANOTHER faction's uniform (verified: `Britain_Inf_Line_Dutch_Line_Infantry` -> filename `United_Netherlands_...`). So a new faction needs the row, not new meshes |
| 5 | `uniform_to_faction_colours` | same count as `uniforms` | `Belgium_Art_Foot_12_lber belgium 30 35 67 54 54 54 173 173 173` (3 RGB tints applied to the atlas colour mask) | unique RGB per unit, free |
| 6 | `units_to_exclusive_faction_permissions` | same count as `uniforms` (13 belgium, 21 denmark) | `Art_Foot_12_lber	denmark	true` (key=unit, faction, allowed) | unique rows; which units the faction may recruit |
| 7 | `faction_rebellion_units_junctions` | 8 (belgium) - 11 (denmark) | `denmark	Art_Foot_12_lber` (faction_key, unit_key) | pick units from permitted set |
| 8 | `technology_faction_junctions` | 46 (belgium and denmark both 46) = full tech list | `admin1_classical_economics	denmark` ... | UNIQUE rows but trivially cloned from any faction by renaming faction_key. Without them the faction has no tech tree |
| 9 | `unit_stats_naval_crew_to_factions` | 1 | `belgium	euro_marine	euro_seaman	euro_guncrew	euro_naval_admiral	euro_naval_commodore	euro_naval_officer	euro_naval_drummer` | CLONE exact row, change key |

Not required for belgium (so optional) [L]: `battle_type_faction_presets` (denmark has 2 rows, belgium 0), `diplomacy_negotiation_faction_override_strings` (538 rows total, belgium 0), `groupings_factions_junct` (9 rows), `building_faction_variants` (45 rows, keyed faction+building).

Models tables (needed for campaign models; belgium has them) [L]:
- `warscape_rigid_tables`: `agent_ID_<faction>` (RigidModels/CampaignBuildings/CampaignAgentIcons/Textures, category campaign_template_extra) + `warscape_rigid_lod_tables` row `...CampaignAgentIcons/agent_ID_<faction>.rigid_model`. 101 agent_ID rows total. Also `agent_ID_<faction>_republic` for factions that can turn republic (denmark has it, belgium does not).
- `warscape_animated_tables`: `campaign_euro_general2_<faction>` (texture dir UnitModels/Textures/campaign_euro_general1, or ..._captain2 for denmark) + 2 rows in `warscape_animated_lod_tables` (lod1 40.0, lod2 0.0). 51 such general rows. CLONE: belgium points at the generic `campaign_euro_general1` textures, i.e. no new texture needed if the mesh/tex is reused. [L]

### 2.2 UI / file assets per faction (what denmark has vs what belgium has)

| Asset path (under data/) | Count (denmark) | Needed? | Clone? |
|--------------------------|-----------------|---------|--------|
| `ui\flags\<flag>\` : `flag_animation0000..0011.tga` (12), `flag_132.tga`, `hud_left.tga`, `hud_right.tga`, `id_flag_artillery/cavalry/infantry/naval.tga`, `large.tga`, `large.dds`, `mini_flag.tga`, `portrait_flags.tga`, `small.tga` (belgium: 24 files in dir) | 24-28 | YES: `flags_path` points here; faction select / HUD / diplomacy use it | copy a flag dir and recolour; ~24 files each |
| `ui\flags\<flag>_republic\` | same set | only if `republican_flag_path` is set (belgium: \N) | skip for dormant minors |
| `ui\units\icons\<faction>_<unit>_icon.tga` | 21 (one per unit) | YES per unit in `uniforms` (belgium has own set; icon_path_units column `data\ui\units\icons\<faction>`) | copy unit icon of another faction/rename |
| `ui\units\info\<faction>_<unit>_info.tga` | 21 (denmark); belgium 13 | per unit | copy/rename |
| `variantmodels\units\atlas\<faction>_{diffuse,normal,gloss,colour_mask}.{atlas,dds}` (8 files) | 8 | belgium and denmark both own a set | Clone; possible to avoid if `unit_variant` files reference another faction atlas [?] |
| `variantmodels\units\<faction>_<unit>.{soldier,officer,musician,standard_bearer}.unit_variant` | ~3-4 per unit | belgium has them (46 files) | CLONE by text copy; `uniforms.filename` can instead redirect to an existing faction's variant (verified for britain->united_netherlands) [L]; whether the unit_variant must exist physically for a new-faction `uniforms.filename` that points to another faction is the redirect mechanism, so no new unit_variant is needed in that case [I] |
| `rigidmodels\naval\textures\ensign_<faction>_diffuse.dds` | 1 (+ `_republic`) | belgium/catalonia/norway all have one (349672 bytes each) | copy |
| `rigidmodels\campaignbuildings\campaignagenticons\agent_id_<faction>.rigid_model` + `textures\agent_id_<faction>_diffuse.dds` | 2 | belgium has | copy |
| `testdata\campaignflags\flag_<faction>.dds`, `logs\cai\flags\flag_<faction>.jpg` | 1 each | NOT needed (dev leftovers) | skip |

Per-faction campaign road/border splines: `rigidmodels\campaignborders\denmark.rigid_spline` (182 border files total) and `campaignroads\main*\denmark_1..8.rigid_spline`. These are named after the REGION/pieces (not faction art); see region section. [L]

### 2.3 Loc keys per faction

Belgium: exactly 4 [L]
- `factions_screen_name_<f>` ("Denmark")
- `factions_screen_adjective_<f>` ("Danish")
- `factions_attack_desc_<f>` ("You are attacking a Danish force.")
- `factions_defend_desc_<f>` ("You are defending against a force of Danish attackers.")

Optional extras seen for denmark: `random_localisation_strings_string_attack_<f>`, `..._defend_<f>` (duplicates of the two desc keys), `random_localisation_strings_string_player_stats_mp_{land,naval}_won_<f>` (MP stats only), `names_royalty_name_<f><Name>` (8 for denmark), `names_forts_fort_name_names_<group>*` and `names_name_names_<group>*` (355 for danish; shared per name_group so reuse an existing `name_group` instead of creating), `ancillaries_onscreen_name_Anc_Order_<F>` (optional). Playable factions additionally need `start_pos_factions_description_<hash>` (308 `factions_*` keys total; vanilla playable descriptions are PLACEHOLDER text for several) and frontend strings. [L]

Loc file mechanics: `local_en_patch.pack` overrides `local_en.pack`; loc is a tab-separated key/text/tooltip. A new pack may add a `.loc` file with new keys; no collision as long as keys are new. [L]

### 2.4 Startpos FACTION record (trace: denmark)

Dump: `work/scratch_db/denmark_faction.txt`. `<FACTION v18>` children in order [L]:
1. `ANCILLARY_UNIQUENESS_MONITOR v1` (empty entries)
2. `CAMPAIGN_PLAYER_SETUP v3` (+ `CAMPAIGN_VICTORY_CONDITIONS v5`, `..._INGAME_MODIFIABLES v2`, string `'denmark'`, 3 bools)
3. `FACTION_ECONOMICS v6` (history, treasury i32 5000, u8[25], u32)
4. `DIPLOMACY_MANAGER v3` (`DIPLOMACY_RELATIONSHIPS_ARRAY` - list entries, not fixed array)
5. `ARMY_REINFORCEMENT_MANAGER v1`
6. `GOVERNMENT v1` (handle, `'gov_absolute_monarchy'`, POSTS_ARRAY, GOV_IMP)
7. `FAMILY v2` (10 `MONARCHY_INFO_CHARACTER`)
8. i32 handle 615211060, `'denmark'` (key), `'Denmark'` (display)
9. 10 x `NAME_ALLOCATION_DETAILS v1` (name pools, u16 arrays sized to name-group counts: 51, 56, 1, 0, 212, ...) - a faction with an empty set is valid (several are size 0) [L]
10. `LAND_UNIT_NAME_ALLOCATOR`, `NAVAL_UNIT_NAME_ALLOCATOR`
11. `CHARACTER_ARRAY v0 x22` (CHARACTER v12), `FACTION_TECHNOLOGY_MANAGER v4` (techs), `ARMY_ARRAY x3` (ARMY, NAVY, ARMY), `MORGUE`
12. `'rel_protestant'` (state religion), `FORT_UPGRADE_MANAGER` x2, handles, `EXPOSED_CHARACTERS`, `PRESTIGE v2`, `bool[20]`
13. strings `'nap_eur_maintainance'`, `'default'` x3 (campaign/AI scripting profile names)
14. `FACTION_FLAG_AND_COLOURS v1` x2: flag path `data\ui\flags\denmark` + 3 RGB (214,38,38 / 255,255,241 / 165,0,33 - same values as `factions_tables` primary/secondary/uniform colours)
15. `CAMPAIGN_BONUS_VALUES v1` x2, `CHARACTER_RECRUITMENT_MANAGER v1`, `RECENT_PROPOSALS`, trailing run of ~44 u32 zeros + `u32[0]`

What the faction record references from db/ui: flag path string; colours; state religion string; government key (`gov_*`); name pools (indexes by name group); tech manager (tech keys); units inside armies (unit keys from `units`). No `index` from factions_tables. [L]

Cross-record places a faction key appears (all string keys): FACTION record; every owned REGION (owner string); settlement/slot ownership; rebels' `settler_rebellion_faction`; each other faction's `DIPLOMACY_RELATIONSHIPS_ARRAY` (a per-pair relation list, scales O(n^2) entries but variable length); `CAMPAIGN_ENV/CAMPAIGN_SETUP` playable/unlocked lists; CAI_INTERFACE faction-keyed entities (BDI pools) [L, detail of CAI not decoded]; `scripting.lua` references by key. [I for exhaustiveness]

Playability is a startpos flag (CAMPAIGN_SETUP), not `factions_tables.category` (categories seen: playable, minor, non-expansionist, rebel). A dormant minor needs no player UI; making it playable additionally needs flag UI, a description loc key, frontend campaign-details entry (layout/Lua, not data). [L]/[I]

### 2.5 Cloneable vs unique summary (faction)

- Pure clone (copy a row, change key): `unit_stats_naval_crew_to_factions`, `technology_faction_junctions` (46), `faction_rebellion_units_junctions`, `warscape_animated/rigid(+lod)` rows (point at shared meshes), `uniforms` rows with redirected `filename`, `units_to_exclusive_faction_permissions`.
- Free-choice values: `faction_uniform_colours`, `uniform_to_faction_colours`, flag colours.
- Must be unique: `factions_tables.key`/`index`, loc names, flag dir (or reuse another faction's by pointing `flags_path` at it - allowed by the column being a path [I]), startpos FACTION handle, `cdir_faction_junctions` row.
- Gotchas: `subculture` drives BATTLE city/bridge/farm styles (see section 5) and ancillaries; `military_group` shares unit rosters/AI doctrine; `audio_faction_string` is a 2-letter voice set (Ge, Du, ...). [L]

### 2.6 Faction-count limits

No hard faction-count limit visible. [L]
- No fixed arrays sized to faction count: the faction-related fixed arrays in the startpos are `bool[20]`, `u8[25]`, `u32[8]` x4 (region), all smaller than the 41 factions already present, so they are indexed by something else (religions=9, pop classes=3, etc.) [I]. The diplomacy and faction arrays are counted record arrays. [L]
- Techs/units are per-faction rows, not bitfields. [L]
- Web search found no documented cap (see 03-engine-limits-and-db.md). Cap for ~120 factions is therefore UNKNOWN [?] and can only be proven in-game. Biggest risk is CAI / diplomacy cost O(n^2), not a data limit.
- Mods that flip every faction playable edit startpos only (no cap discussed).

---

## 3. Q2 - per-REGION checklist

### 3.1 DB (4 tables) [L]

| Table | Rows per region | Example (`eur_denmark`) |
|-------|-----------------|--------------------------|
| `regions_tables` (key, continent, r, g, b, battle_name) | 1 | `eur_denmark	cont_europe	137	81	83	Denmark` (continent FK to `regions_continents`: 8 values; NTW uses cont_europe and cont_middle_east) |
| `campaign_map_settlements` (settlement_id, region, default_onscreen_name, slot_count, slot_type) | 1 (159 rows = one per region) | `settlement:eur_denmark:copenhagen	eur_denmark	Copenhagen	3	settlement`. slot_count distribution: 87 x1, 33 x2, 28 x3, 6 x4, 5 x5 |
| `campaign_map_towns_and_ports` (town_id, slot_type, onscreen_name) | 0-n (233 rows total) | `town:eur_denmark:hamburg	town-commercial	Hamburg`, `town:eur_denmark:schleswig	town-intellectual	Schleswig`, `port:eur_denmark:aalborg	port	Aalborg`. slot_type values town-commercial, town-intellectual, ..., port |
| `campaign_map_slots` (slot_id, region, slot_type, rotation, underlay) | 0-n (145 rows total; resource slots only) | `wheat:eur_denmark:aarhus	eur_denmark	wheat	0	\N` (rotation always 0 in the data; 4 allowed rotations 0/90/... in `campaign_map_slots_templates_rotations`) |

Other region-adjacent tables: `resources_tables` (20 resource types, incl. icon path), `region_unit_resources` (38), `region_economics_factors` (13, UI pip paths, not per-region), `campaign_map_tooltips`, `campaign_map_famous_battles` (empty), `empires_regions_junct` and `groupings_regions_junct` (both EMPTY in this install). There is NO per-region climate, religion or population table: climate comes from the map raster; religion and population live in the startpos REGION record (`POPULATION`, `RELIGION_BREAKDOWN`). [L]

Region slot count reconciliation (CAI view): 481 building slots = 337 + 72 roads + 72 forts; 195 region slots = 82 resource + 74 town + 39 port. [L]

### 3.2 Loc keys per region [L]

- `regions_onscreen_<region>` ("Denmark")
- `regions_battle_name_<region>` ("Denmark") - this is the ONLY thing `regions_tables.battle_name` is used for (a display label for battle/headline naming; it is NOT a link to a `battles_tables` map, see section 5)
- `campaign_map_towns_and_ports_onscreen_name_<town_id>` per town/port
- `campaign_map_slots_onscreen_<slot_id>` per resource slot ("Århus Farmland")
- `start_pos_settlements_onscreen_name_<settlement_id><signed int>` per campaign (denmark has two: `...copenhagen-2049605355` and `...copenhagen114577098`; the integer is a hash/handle suffix and is the exact string stored in the startpos `CAMPAIGN_LOCALISATION` node of the SETTLEMENT; eur_napoleon and mp_eur_napoleon have separate suffixes) - 293 such keys in total
- `start_pos_regions_rebel_faction_name_<region><campaign>` (`...eur_denmarkeur_napoleon`, `...eur_denmarkmp_eur_napoleon`) = rebel faction display name ("Danish Revolutionaries"), also stored in the REGION record

### 3.3 Map files (region must exist in every one) [L]

Under `data/campaign_maps/nap_europe/`:
- `europe_lookup.tga` (8-bit paletted, palette entry == `regions_tables` RGB; sea/black/border use extra indices; ~250 usable palette entries ceiling)
- `europe_map.tga`, `stratradar_europe.tga` (visual overlays)
- `regions.esf` (9.2 MB) - per-region geometry/boundary and settlement/slot positions; `poi.esf` (1.5 MB), `sea_grids.esf`, `trade_routes.esf` (389 KB), `pathfinding.esf` (4.8 MB), `metadata.dat` (MTGI header: w,h + 1 byte/pixel, semantics [?] maybe climate or ground type)
- `display/` : per-region border splines (`rigidmodels\campaignborders\<name>.rigid_spline`, 77 in this map's display + 182 in the pack list), roads (219; `campaignroads\main*\<region>_<n>.rigid_spline`), coastline, heightmap, supertexture, fogmask, environment lighting, trees

### 3.4 Startpos REGION record (trace: eur_denmark)

Dump: `work/scratch_db/denreg.txt`. `<REGION v5>` [L]:
1. key `'eur_denmark'` (utf16)
2. `POPULATION v1` -> `REGION_FACTORS v1` (f32[7]) + `POPULATION CLASSES x3` (v3 each; upper/middle/lower) + u32 totals (961000 / 1922000 / 961000, total population 1,922,000) + `RELIGION_BREAKDOWN v0 x9` (rel_hindu, rel_nonconformist, rel_sikh, ... 9 religions with f32 share)
3. `TRAITS v1` (empty)
4. `REGION_SLOT_MANAGER v1` -> `REGION_SLOT_ARRAY x7` (REGION_SLOT v3 each) + `ROAD_SLOT v0` + `FORTIFICATION_SLOT v0`. Each REGION_SLOT v3 = `SIEGEABLE_GARRISON_RESIDENCE v1` + `BUILDING_MANAGER v1` + u32 handle + slot key string (e.g. `'settlement:eur_denmark:copenhagen:settlement_road:3'`, `...:settlement_fortification:0`) + i32 x,y fixed-point position (int32 x 2^-20; e.g. -89146736 / 92000040 -> about -85.0, 87.7 map units) + flags (owner/visibility/-1 sentinel/4294967295)
5. i32 region handle (865658036)
6. `SETTLEMENT v2` -> `SIEGEABLE_GARRISON_RESIDENCE`/`GARRISON_RESIDENCE` (region handle 615211060 = owner FACTION handle), handles, i32 x/y fixed point (-88310192 / 91716144), `LINE_OF_SIGHT`, `CAMPAIGN_LOCALISATION` string (see 3.2), settlement level i32 3, `'settlement:eur_denmark:copenhagen'` x2
7. tail: `u32 1, bool, bool`, `u32 1600, 1850, 1850, 1500, 1500, 1500` (wealth/tax/etc. numeric block - tax constant 136 per 03), owner faction handle, `LINE_OF_SIGHT`, handle, theatre string `'europe'`, owner `'denmark'`, rebel name `'Danish Revolutionaries'`, subculture `'sc_european_north'`, `REGION_RECRUITMENT_MANAGER v1`, `bool`, `u32[8]` x4, `bool[20]`, `RELIGIOUS_MISSION_BUILDING_ARRAY`, `FORT_ARRAY`, `RESOURCES_ARRAY x1` (`'global'` + others), u32 10 / handle, `CAMPAIGN_LOCALISATION` `'regions_onscreen_eur_denmark'`, f32 0.0

Notes [L]:
- The region record's `subculture` string (sc_european_north) is independent of the owner's `factions_tables.subculture` (denmark = sc_european_west): the REGION subculture drives building/slot art and battle-terrain style, so it is a per-region choice the generator must set, not derived from the owner.
- The REGION record is repeated for every region in `WORLD/REGION_MANAGER` (72 in eur). Also referenced from CAI: `CAI_INTERFACE` has per-region and per-slot entities (481 + 195 slots in eur) with BDI pools keyed by handle. The CAI graph was not fully decoded [?]; the minimal valid startpos for a new region requires those CAI entities, or the CAI load-fixup may crash [?, in-game test].
- Buildings: starting buildings live in `BUILDING_MANAGER` inside each slot; building keys come from `building_*` tables (culture variants via `building_faction_variants`, 45 rows, and culture, not faction). Empty slots are allowed (a slot with no building is valid [I]).

### 3.5 Region checklist (generator)

For each new region: (1) pick key `<theatre>_<name>`, unique RGB; (2) `regions_tables` row; (3) paint polygon in `europe_lookup.tga` with that colour; (4) `campaign_map_settlements` row (+ slot_count); (5) 0-n rows in `campaign_map_towns_and_ports` / `campaign_map_slots`; (6) loc keys from 3.2 (regions_onscreen, regions_battle_name, per town/port/slot, settlement start_pos key with the exact numeric suffix used in the startpos, rebel faction name); (7) entries in `regions.esf`, `poi.esf`, `sea_grids.esf` (for coastal), `trade_routes.esf`, `pathfinding.esf`, `metadata.dat`, border/road splines in `display/`; (8) REGION record + REGION_SLOT_MANAGER + SETTLEMENT in startpos; (9) CAI region/slot entities; (10) ownership by an existing/new faction string.

---

## 4. Q3 - tables and files that reference the theatre / map

[L] unless stated.

- `campaign_map_playable_areas` (5 rows, no onscreen_name col in this version): index (I32-looking string), sea_trade(false), map_file, overlay_file, radar_file, meaningful_id, preview_width, preview_height, preview_border. Rows: 1242140790 italy_main (513x300), 1244818741 europe_main (605x300; eur), 1246294763 spain_main (337x300), 1248087989 europe_main (605x300; second row for tut/mp), 1564135506 egypt_main (253x300). All use europe_map.tga / europe_lookup.tga / stratradar_europe.tga for the europe rows. A world map needs the preview width scaled to 300 px height (e.g. 2:1 -> 600x300, or 4:3 -> 400x300). The generated map likely REPLACES rows 1244818741 and 1248087989.
- Startpos: string `campaign_maps/nap_europe` and `europe_main` (CAMPAIGN_SETUP / CAMPAIGN_PREOPEN_MAP_INFO) - link campaign to map folder; `'europe'` also per REGION record.
- Loc `campaign_map_playable_areas_onscreen_name_%S` (5 keys) - theatre display name.
- `regions_tables` r,g,b <-> `europe_lookup.tga`. `regions_continents` (8 values, FK).
- `campaign_map_settlements`, `campaign_map_towns_and_ports`, `campaign_map_slots` keyed by region id strings.
- `climates_tables` (33 rows: 23 land `lc_*`, 10 sea/coast `sc_*`; `colour_index` 0-32) - climate colours are painted in the map raster; where the raster lives is [?]: `metadata.dat` or `regions.esf` per-cell data. `sea_climate_details`, `fort_underlay_climate_jcts`, `trees_climates_jct`, `small_vegetation_climates_jct`, `climate_to_tilesets` all key on climate names (no per-map data).
- Empty/irrelevant: `campaign_map_famous_battles` (0 rows), `empires_regions_junct` (0), `groupings_regions_junct` (0).
- Frontend campaign list/preview is layout+Lua, not data-driven (`work/scratch_db/fe/`): campaign selection UI lists campaigns by `campaigns_onscreen_name_*` loc + `campaigns_description_*`; a campaign key has no db table (confirmed absence of `campaigns_tables`).
- `scripting.lua` in the campaign folder: region/faction keys by string (read-only for this task).

If keeping a single theatre named `europe_main`, the minimum change set is: replace the 5 map files + 3 tgas, regions.esf, poi, sea_grids, trade_routes, pathfinding, metadata.dat, display/*, startpos, and keep the two `campaign_map_playable_areas` rows (update preview width). Renaming the theatre requires matching string edits in the startpos (many occurrences).

---

## 5. Q4 - battle and battle-map links

[L] unless marked.

- `regions_tables.battle_name` is a LOC LABEL key suffix only: `regions_battle_name_<region>` = e.g. "Denmark". It is not a foreign key into `battles_tables`. (`battle_name` values in table: mostly unique per region; duplicates e.g. Tyrol x2, Navarra x2, Galicia x2, Gibraltar x2 mean two regions share a name.)
- `battles_tables` (87 rows: historical `NHB_*`, MP `NMPB_*`/`NHMPB_*`/`NAP_MP_*`, forts, `caribbean`, `TUT_*`, sieges `rti_fort_*`) - these are hand-made maps for historical/MP battles and forts. Campaign battles in regions are NOT among them; they are generated at runtime from terrain.
- Campaign battle terrain chain: battle location -> campaign-map climate (23 land climates `lc_*`; all 23 are present in `battle_terrain_set_climates_jcts`, so any region painted with an existing climate has a terrain set) -> `battle_terrain_set_climates_jcts` (climate -> `battle_terrain_texture_set_grouping`, e.g. lc_eu_south_humid -> Grass) -> `battle_terrain_set_groupings` (26 rows: grouping -> climate_grouping Arid(6)/Cold(4)/Dry(3)/Seascape(3)/Temperate(9)) -> `battle_terrain_sets` (82 rows: grouping x variation x season_summer/winter with colour_map, blend_map, grass_map, cliff_map, rock_map, tiled_detail_map, detail_map_a-d, forest_underlay, grass_type; all paths under `BattleTerrain/...`; real files have suffix `_diffuse`/`_normal`, a naive existence check gives false misses) -> `battle_sky_types` (1676 rows: season x weather x time_of_day x climate -> .environment sky file) via `battles_to_battle_sky_types_junctions` for named battles.
- Settlements/farms/bridges: `battle_city_subculture_jct` (13 subcultures: sc_european_america/east/north/south/west, sc_indian_*, sc_mideast_islamic, sc_tribal_american, sc_egy_*) -> `battle_cities` (5 styles American, Eastern, European, ...), `battle_bridge_subculture_jcts` (subculture -> simple/refined bridge), `battle_terrain_farms` (farm styles e.g. EU_East + EU_East_Winter, own blend/colour/grass maps and wall pieces). KEY RULE: the REGION's subculture string (startpos) picks these, so a new world subculture (say sc_chinese) needs a row in each of those three tables or reuse an existing subculture (the 13 rows above are the entire supported set unless rows are added). New battle art (building models, farm tiles) is only needed if you add a new city/farm/bridge style; otherwise point the new subculture at an existing style.
- Climate-dependent: `fort_underlay_climate_jcts`, `trees_climates_jct`, `small_vegetation_climates_jct`, `sea_climate_details` (sea colour/sun/sky per climate, 33 rows).
- To get battles on "new terrain types" using only data: add `battle_terrain_sets` rows with new `BattleTerrain/...` texture paths, add a grouping in `battle_terrain_set_groupings`, map climate(s) in `battle_terrain_set_climates_jcts` (+ optional new climate row in `climates_tables` with a fresh `colour_index`, new `sea_climate_details`, `trees_climates_jct`, etc. rows). New climate means extending the raster palette that encodes climate [?]. Safer: keep the 33 existing climates and only re-skin their terrain sets.
- Dangling refs in vanilla: only a few `BattleTerrain` paths do not resolve (after fixing the suffix check), so vanilla itself is not perfectly consistent; do not rely on validating every path.

---

## 6. Hard limits found

- Palette ceiling: 256 entries per `*_lookup.tga`; vanilla uses 72 colours for 72 regions plus a few extras, so ~250 regions per map. Need 200+ regions: tight but feasible; > 250 impossible. [L]+[I]
- Raster: strategic images are always 300 px tall; width = 300 x aspect (605 for 2:1); heightmap 4096x2048 Europe, Egypt metadata 4096x4096. [L]
- `campaign_map_slots_templates_rotations` has 4 rotations (0, 90, ...). [L]
- No explicit faction-count cap. No fixed array indexed by faction found. [L]
- `unit_stats_naval_crew_to_factions`, `technology_faction_junctions` (46 each) scale linearly: 120 factions x 46 = 5,520 rows (vanilla 3,213). [L]
- `uniforms` (1,120 rows vanilla): 120 factions x ~13-21 units => up to ~2,500 rows. No limit known. [?]

## 7. Risks / unknowns

1. Where the climate raster is stored (metadata.dat vs regions.esf cells) and the exact `regions.esf` per-region layout (NTW has an extra float vs ETW, 03-doc note) - decode needed before generating regions.esf. [?]
2. CAI entity graph in `CAI_INTERFACE` (BDI pools, per-faction and per-region/slot handles) - minimal consistent subset not proven; requires an in-game load test, which is out of scope here. [?]
3. Whether all `unit_variant` files must exist for each new faction or whether `uniforms.filename` redirect fully suffices at runtime (britain->united_netherlands proves redirect works for existing factions). [I]
4. Reused-uniform factions: icon/info tga requirements per unit not conclusively checked for redirected uniforms (grep inconclusive); safest is to copy `ui\units\icons\<f>_<unit>_icon.tga` and `ui\units\info\<f>_<unit>_info.tga` for every `uniforms` row. [?]
5. Frontend (campaign selection, faction pick, preview image) is Lua/layout: not data-driven, needs manual mod of `fe/` layouts if the campaign is to be user-selectable.
6. The `start_pos_settlements_onscreen_name_...<int>` suffix per campaign must be copied exactly from the generated startpos; a mismatch just shows the raw key (cosmetic). [I]
7. `regions_tables` is shared by all campaigns of the install: new region keys must not collide with ita/spa/egy keys, and unused regions (159 total vs 72 used) are harmless. [L]
8. Faction count above 41 in a single startpos (we need ~120): no data evidence either way; plan to test with growing counts. Prefer dormant minors (belgium template: db rows only; whether its startpos FACTION has armies/characters was not checked) to cap CAI cost. [?]
