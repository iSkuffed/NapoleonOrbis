# 03 - NTW engine limits and db-table side of a new campaign

Scope: Napoleon: Total War (NTW, Warscape, Steam app 34030) - what the engine tolerates and which db tables / files define a campaign, its regions and factions.
Written 2026-10-18. Read-only research; nothing in the game dir was modified.

Evidence tags: **[L]** verified locally (command + result given), **[W]** from a web source (URL given), **[I]** my inference (not verified), **[?]** unknown / no source found.
Helper scripts used for [L] checks live only in /tmp/ntw (pack index reader `packls.py`, db decoder `dbdec.py` driven by the RPFM schema). They are throwaway.

---------------------------------------------------------------------------
## 0. Headline facts (read this first)

1. No source, public or local, documents a hard numeric cap on factions or regions in NTW/ETW. The only "limit" statements are forum opinion ("impossible to add regions", Steam) that the OpenETW / Distant Seas work has since contradicted (section 6). Treat every number below as "vanilla scale", not "engine ceiling".
2. Vanilla scale in NTW: largest campaign (eur_napoleon, same map as mp_eur and tut) = **72 regions, 49 factions in startpos (41 non-rebel + 8 rebel)**; whole region table = 159 rows; whole faction table = 77 rows. [L] (section 1.2)
3. Napoleon.exe is **already Large-Address-Aware** (PE Characteristics 0x0122). The "4GB patch" is not needed for this build. [L] (section 5.1)
4. The theatre system of ETW is still fully present in the NTW binary (CAMPAIGN_THEATRE, THEATRE_TRANSITION_INFO, CAMPAIGN_MAP_TRANSITION_LINK, transition_areas, TheatreList Lua API, `campaign_transition_markers`) and the NTW eur/egy startpos files still contain THEATRE_TRANSITION_INFO / CAMPAIGN_MAP_TRANSITION_LINK nodes. But every vanilla NTW campaign uses exactly **one** playable area. [L] (section 2)
5. A campaign is NOT registered in a db table (there is no `campaigns_tables` in NTW). It is: `data/campaigns/<key>/startpos.esf` + `scripting.lua`, a map folder `data/campaign_maps/<map>/`, rows in `campaign_map_playable_areas`, `campaigns_campaign_variables_junctions`, loc keys, and **frontend UI layout/Lua** (the campaign list UI is a layout file, not data-driven). The campaign-to-map link lives inside startpos.esf as the string `campaign_maps/nap_europe`. [L] (section 3.3)
6. Regions are keyed by an RGB triple in `regions_tables` that must match a palette entry in an 8-bit `*_lookup.tga` exactly (72/72, 30/30, 25/25, 32/32 verified; the lookups also use a few extra palette indices for sea/black/border, e.g. spain 38 indices used for 32 regions). Palette = 256 entries, so ~250 regions per lookup image is a plausible hard ceiling per theatre. [L]+[I]
7. Largest vanilla raster: Europe heightmap **4096x2048** (8-bit gray TGA), Egypt metadata grid **4096x4096**. Strategic-map/lookup TGAs are always **300 px tall**. [L]
8. RPFM schemas for NTW exist: `schema_nap.ron` (7.08 MB), and for Empire `schema_emp.ron`. [W]+[L]
9. Proton: ProtonDB summary for app 34030 = tier Gold, 64 reports, best reported Platinum. [W] Steam on this machine already assigns GE-Proton11-5 to app 34030 [L]; the prefix exists but contains no Creative Assembly appdata yet (never launched here).
10. Prior art exists and is the single most important finding for planning: **Distant Seas** (given peace; reverse-engineering NTW's 65,571 functions, global spherical map) and **OpenETW** (daruskiy; splits ETW provinces, ETW map loaded inside NTW). Both are claims in secondary sources (YouTube descriptions, ModDB comments), not primary technical writeups. (section 6)

---------------------------------------------------------------------------
## 1. Hard engine limits

### 1.1 What is and is not documented

- Factions: no documented cap for ETW or NTW. Web searches for "maximum number of factions", "faction limit", "32/64 factions" in ETW/NTW returned nothing concrete [W: negative result, searched 2026-10-18]. Mods that flip every faction to playable ("Napoleon Total Factions", "Empire Total Factions") only edit startpos flags; no cap discussed. TWC wiki index lists tutorial "How to unlock non playable and emergent factions" https://www.twcenter.net/forums/showthread.php?t=336697 (via wiki index https://web.archive.org/web/20230809005240/https://wiki.twcenter.net/index.php?title=Napoleon:_Total_War_-_Modding_Index ).
- Regions: Steam forum opinion "So far as i know its impossible to add more regions" and "CA limited the modding capabilities in the Warscape engine ... map can't be changed" https://steamcommunity.com/app/10500/discussions/0/1458455461476320582/ (2017, ETW; opinion, now contradicted by OpenETW). Only concrete cap found anywhere is Rome: Total War = 200 regions (different engine; irrelevant, [W] via search snippet https://rtw.heavengames.com/rtw/mods/tutorials/adding_new_regions/ ).
- Map size: one TWC poster (ETW "modding campaign map" thread, page 21) says the heightmap has a max size but "can be stretched" over a larger map with loss of detail, and guesses ~1000x1000 miles is the practical limit for sensible topography [W, snippet only; page not fetchable (403): https://www.twcenter.net/threads/modding-campaign-map.548643/page-21 ]. Anecdote, not a spec.
- Memory: Steam thread claims NTW late-campaign crash 0xc0000005 is out-of-memory and grows "more than exponentially" with campaign length [W, opinion] https://steamcommunity.com/app/34030/discussions/0/154644045361489511/ ; another advises a Large Address Aware enabler https://steamcommunity.com/app/34030/discussions/0/135511913390479506 . Neither confirms a fix. Our exe already has the flag (5.1).

### 1.2 Vanilla scale (local, decoded from data.pack with the RPFM nap schema)

Method: parse PFH0 index of data/data.pack, decode db files (header `fcfdfeff` + u32 version, then `01` + u32 rowcount) with `schema_nap.ron` at the matching version.

| quantity | value | evidence |
|---|---|---|
| `factions_tables` rows | 77 (db version 3) | decode of `db\factions_tables\factions` |
| `regions_tables` rows | 159 (db version 1): eur 72, spa 32, egy 30, ita 25 | counter on key prefix |
| `campaign_map_settlements` rows | 159 (1:1 with regions except extras like `eur_provence:toulon_tut`, +/- duplicates) | decode |
| `campaign_map_slots` rows | 145 (resource/mine/etc slots) | decode |
| `climates` rows | 33 | decode |
| `trade_nodes` rows | 24 (eur 19 incl. one per sea zone, spa 5) | decode |
| db tables in data.pack | 310 | `grep -c '^[0-9]* db\\' ` on the index listing |
| faction keys referenced inside startpos.esf (UTF-16 strings matching factions_tables keys) | eur_napoleon 49, mp_eur_napoleon 49, egy 6, ita 17, spa 9, tut 6 | python regex over each startpos.esf |
| region keys referenced inside startpos.esf | eur 72, mp_eur 72, egy 30, ita 25, spa 31 (32 in table), tut 72 | same |

Faction categories present in `factions_tables.category`: `playable`, `minor`, `non-expansionist`, `rebel`. Rebels are per-nation factions (`austrian_rebels`, `french_rebels`, `slavic_rebels`, ...), 8 of them in eur. [L]

Faction `index` column is I32: small ints (1..84) for original ETW-era factions, large pseudo-random ints (e.g. `-8292990`, `1322886196`, `-1881902117`) for factions CA added later (belgium, brittany, catalonia, all `ita_*`/`egy_*`/`spa_*`/`tut_*`). That is direct evidence that **arbitrary unique int32 values are accepted** for new faction indices. [L] Whether index must also be consistent with a startpos FACTION_ARRAY entry is [?] (assume yes).

`campaign_variables` contains `tax_efficiency_total_regions = 136.0` (balance constant, a count that was clearly tuned for vanilla map size - needs retune for 150+ regions) and per-campaign `character_recruitment_max_distance` (egy/ita 340, eur 550, spa/tut 680) and `faction_gdp_other*` via `campaigns_campaign_variables_junctions`. These values are in map units, which gives a relative scale of the maps: a bigger world needs larger values. [L]

### 1.3 Map raster / coordinate sizes (local)

Command: python reads TGA/DDS headers under data/campaign_maps/*.

| map | heightmap.tga | fogmask.dds | snow/winter.dds | metadata.dat (`MTGI` hdr: w,h) | *_lookup.tga | stratradar |
|---|---|---|---|---|---|---|
| nap_europe (eur, mp_eur) | 4096x2048, 8-bit gray (type 3) | 2048x4096 | 2048x4096 | 2048x1024 (file 2,097,164 B = 12 + w*h) | 605x300 | 605x300 |
| nap_tut | 4096x2048 | 2048x4096 | 2048x4096 | (no metadata.dat present) | 605x300 | 605x300 |
| nap_italy | 2048x2048 | 2048x2048 | 2048x2048 | 2048x2048 | italy 513x300 + europe 490x300 | 513x300 / 490x300 |
| nap_spain | 2048x2048 | (none) | 1024x1024 | 2048x2048 | 337x300 | 337x300 |
| nap_egypt | 2048x2048 | (none) | (none) | **4096x4096** (16 MB) | egypt 253x300 + europe 490x300 | 253x300 / 490x300 |

- `metadata.dat` = magic `MTGI`, u32 width, u32 height, then 1 byte/pixel (file size = 12 + w*h). Content semantics (ground type / climate index?) [?].
- Aspect: europe 2:1 (4096x2048). Lookup/strategic images always 300 px tall; width = 300 * map aspect (605/300 = 2.02). [L]
- Detail textures: campaign_detail.dds 1024x1024, campaign_detail_mask 512x1024 (europe) or 512x512, campaign_rocks.dds 512x512. [L]
- Supertexture is `supertexture.stpd/.stpi` (only europe has it listed in display/; others derived). Format [?].
- World coordinate extent in game units: not found in any source. Inference from `character_recruitment_max_distance` etc. only. [?]
- Maximum heightmap/supertexture size the renderer accepts: [?]. Europe 4096x2048 is the largest shipped in NTW. Distant Seas claims a "spherical" global map in NTW (6) which means the renderer tolerated their custom sizes, but size not published.

Per-map file set a new theatre needs (from `data/campaign_maps/nap_europe/`): `regions.esf` (9.2 MB, ESF `ceab`), `pathfinding.esf` (4.8 MB), `poi.esf` (1.5 MB), `sea_grids.esf`, `trade_routes.esf`, `metadata.dat`, `<name>_map.tga`, `<name>_lookup.tga`, `stratradar_<name>.tga`, and `display/` {heightmap, supertexture, fogmask, snow, snowmask, environment/*.lighting (4 seasons), detail, coastline/*.rigid_mesh, borders/*.rigid_spline (one per region piece), rivers, roads, bridges.markers, world.markers, trees/campaign.rigid_trees, traderoutes/*.rigid_spline, tradenodes/all_tradenode.rigid_model, arrows}. [L] A TWC user in 2010 reports regions.esf in NTW has an extra float (3D point) vs ETW and that his edited regions.esf came out 16 MB vs 9 MB and would not reopen (STARTPOS thread, wayback https://web.archive.org/web/20230504010805/http://www.twcenter.net/forums/showthread.php?339181-STARTPOS-ESF-analysis-and-modifications ). [W]

### 1.4 Other limits seen in the binary / data (local)

- ESF/Lua loader limits visible as strings: "Max entries exceeded for type '", Lua 5.1 "chunk has too many lines/local variables", "Too many boot packs - only one is allowed." [L: `strings -n 6 Napoleon.exe`]. The last one means only one boot.pack is accepted (DME ships DME_boot.pack as replacement, not additional).
- Army/navy size: `max_army_size` exists as a string/scripting query ("Out: Returns the maximum number of units allowed in a navy" is also in the Lua docs). Value: 20 per army is the ETW/NTW norm [I, not re-verified here]. No db key found in `campaign_variables`.
- Campaign Lua: "The maximum number of execution steps allowed before failing automatically with a forced end turn" - a script watchdog; heavy scripts on a big map can trigger forced end-turn [L string].
- AI: the campaign AI builds per-world analysers from the startpos: `CAI_WORLD_THEATRES`, `CAI_WORLD_TRANSITION_AREAS`, `CAI_HIGH_LEVEL_PATHFINDER_REGION_OWNERSHIP`, `CAI_THEATRE_*` nodes are present in startpos [L]. Distant Seas dev says "new regions the AI actually reacts to" needed binary-level work (7f31ynwtYvo description, section 6) [W, secondary]. **Risk: vanilla CAI may ignore or mishandle regions not in its hardcoded assumptions; test early.** [I]

---------------------------------------------------------------------------
## 2. ETW multi-theatre system in NTW

ETW (shipped) had 3 main theatres (Europe, Americas, India) plus 4 small trade theatres, with transition areas for armies/navies between them. Source: https://bit-tech.net/previews/gaming/pc/empire-total-war-hands-on-preview/5/ and https://wiki.twcenter.net/index.php?title=ETW (search snippets; sources disagree on the exact trade-theatre list) [W].

Is the code still in NTW? **Yes.** Local evidence:

- `strings -n 6 Napoleon.exe | grep -i theatre` -> `TheatreList`, `HomeTheatre`, `RegionsInTheatre`, `TheatreMapPaths`, `TheatreMapDimensions` ("Returns the world offset, width & height of the specified theatre map (x, y, w, h)"), `CharacterInTheatre`, `UnitInTheatre`, `IsTheatreGovernor`, `CurrentTheatre`, `SetRadarTheatreAndPosition`, `theatre_offset`, `theatre_dimensions`, class `EMPIRECAMPAIGN::CAMPAIGN_THEATRE`, `THEATRE_TRANSITION_INFO`, `REGION_OWNERSHIPS_BY_THEATRE`, `CCQ_TRANSITION_THEATRE`, `transition_theatre`, `transition_to_theatre`, `campaign_transition_markers`, `transition_areas`, `transition_links`, `CAMPAIGN_MAP_TRANSITION_LINK`, `campaign_map_transition_areas_onscreen_name_%d`, `campaign_map_playable_areas_onscreen_name_%S`, `CAI_WORLD_TRANSITION_AREAS` ("CAI: WORLD: Post Load Fixup A: Transition Areas."), "Make selected naval character transition to edge of nearest transition area", trade theatres `TRADE_THEATRE_COMMODITY_RECORD`, `CDIR_DESIRE_FILL_TRADE_THEATRES`, `tw_growth_ministers_home_theatre`. [L] (file: /tmp/ntw/exe_strings.txt, lines ~15237, 16029, 18367-18391, 19390, 20934)
- Startpos files carry the nodes. Command: regex `[A-Za-z_]{5,}` over each startpos.esf and filter on theatre/transition. Result [L]:
  - eur_napoleon, egy_napoleon, DME(Empire) startpos: `THEATRE`, `THEATRES`, `THEATRE_TRANSITION_INFO`, `CAMPAIGN_MAP_TRANSITION_LINK`, `REGION_OWNERSHIPS_BY_THEATRE`, `CAI_WORLD_THEATRES`, `CAI_WORLD_TRANSITION_AREAS`, `CAI_THEATRE_*`.
  - ita_napoleon: has THEATRES / CAI_WORLD_TRANSITION_AREAS but no THEATRE_TRANSITION_INFO / CAMPAIGN_MAP_TRANSITION_LINK.
  - DME startpos additionally has `CAI_TRANSITION_AREA` (Empire-style multi-theatre data).
- `campaign_map_playable_areas` (the theatre table) in NTW has 5 rows; one theatre per campaign: `italy_main` (italy_map/italy_lookup/stratradar_italy), `europe_main` x2 (eur, tut/mp), `spain_main`, `egypt_main`. Row key `index` is an I32-looking string (e.g. `1242140790`). Schema v9 columns: index, sea_trade (bool), map_file, overlay_file, radar_file, meaningful_id, preview_width, preview_height, preview_border, onscreen_name. NTW's file is version 0 (first 9 columns). `sea_trade=true` marks ETW trade theatres. [L]
- Frontend UI still contains ETW theatre widgets: `ui\frontend ui\grand_campaign_scripts\main_panel.luac` references `europe`, `america`, `india`, `EU_map`, `US_map`, `IND_map`, `europe_main`, `map_nap_europe`, `spain_main`, `TheatreList`, `theatres`, `InitialiseMaps`. [L: python strings over the luac from data.pack]
- Egypt/Italy folders ship a *second* map image set (`europe_map.tga` + `europe_lookup.tga` + `stratradar_europe.tga`, 490x300). These are used for the region-ownership overview image (Lua doc: "Table of images depicting region ownership for that faction in each theatre"), not as a second playable theatre (egy/ita startpos mention only `egypt_main`/`italy_main`). [L]+[I]

Can NTW load multiple theatres in one campaign? **Code path present, never exercised by CA data in NTW**. Evidence for it working:
- DME folder in this install holds an *Empire* grand-campaign startpos (52.7 MB, strings `caribbean:...`, `india_highlands:...`, `campaign_maps/global_map`, `names_royalty_name_mysore...`) at `data/campaigns/DME/startpos.esf`. It is Empire/Darthmod-Empire content that was put in the NTW dir; I could NOT confirm it actually runs under Napoleon.exe. [L] file contents; running [?]
- Secondary: "They Put Empire INSIDE Napoleon!" (Gudea Academy) says OpenETW's ETW map (India, Mysore, Goa) renders under Napoleon's interface, early WIP https://www.youtube.com/watch?v=I2bcONI-YQ0 and short https://www.youtube.com/shorts/IJgvqyK1oVc [W, secondary]. ModDB comment (via wayback 2026-10-04): OpenETW main work is in Empire, "because Napoleon shares such a similar build of the same engine, they are able to fairly easily port bits over to napoleon" https://web.archive.org/web/20261004191456/https://www.moddb.com/mods/openetw [W].
- Another ModDB comment: author announced a "seamless" super-world map "without seams and transitions, as is present on the default map" (translated from Russian) - i.e. the theatre-transition seams are being designed out, not used [W, same page].

Design implication [I]: a single huge theatre (like Distant Seas' globe, OpenETW's "no seams") is the approach the active community is taking, not stitching ETW-style theatres. The transition system is available as fallback (separate heightmap per theatre, smaller rasters each).

---------------------------------------------------------------------------
## 3. db tables, files, and registration

### 3.1 RPFM schema availability

- Repo: https://github.com/Frodo45127/rpfm-schemas (MIT). `README.md` says one `schema_<game>.ron` per game, `patches.ron` overlay. File list via GitHub API (2026-10-18): `schema_nap.ron` 7,080,279 B (**Napoleon**), `schema_emp.ron` 7,647,889 B (**Empire**), plus sho2, sho2_ce, rom2, att, tob, troy, wh/wh2/wh3, 3k, ph, ph_dyn, are. [W+L]
- Direct: https://raw.githubusercontent.com/Frodo45127/rpfm-schemas/master/schema_nap.ron and .../schema_emp.ron
- `schema_nap.ron` holds **1273** `*_tables` definitions (all versions of the Assembly Kit set, including tables not packed into NTW's data.pack). Per table: ordered `fields` (name, field_type StringU8/StringU16/OptionalStringU16/I32/I64/F32/Boolean, is_key, is_reference, ...), several `version:` blocks. Match the db file's version header to the right block: e.g. local `factions` is v3 although the schema's newest block is v34. Using the newest block on a real NTW file will mis-decode. [L: first attempt with newest block gave wrong column sets]
- Official CA data: "Official RAW Database Table (XML, XSD)" (CA released NTW db XML+XSD July 2011) https://www.twcenter.net/forums/downloads.php?do=file&id=4358 ; CA Q&A thread https://www.twcenter.net/forums/showthread.php?463810-Official-CA-Q-amp-A-thread-XML-and-XSD-modding (wayback https://web.archive.org/web/20230507040450/https://www.twcenter.net/forums/showthread.php?463810-Official-CA-Q-amp-A-thread-XML-and-XSD-modding ) [W]. Also taw/etwng has `db/DB.xsd` and `db/schema.xml` for ETW https://github.com/taw/etwng/tree/master/db [W]. No Assembly Kit proper for NTW (map/startpos editor) is known to be public [?]; CA's Assembly Kit exists for later titles.
- ESF/startpos: `ceab` magic (0xABCE) files: tools = Esf Total Editor, EditSF, EasyEsf (TWC wiki index), taw/etwng `esf*`, and the local `tools/esf.py`. Format notes: https://github.com/taw/etwng/blob/master/docs/ESF.txt . CA post: http://blogs.sega.com/totalwar/2012/03/20/fao-modders-changes-to-esfsave-format/ (link from etwng docs; not re-fetched).

### 3.2 Tables present in NTW data.pack that define world, map, factions (local, decoded)

Format = key columns first as listed by schema at the NTW db version. `*` = not an actual `is_key` in schema (schema marks almost none); keys are my reading.

| table (db ver) | columns | role / notes |
|---|---|---|
| `campaign_map_playable_areas` (0) | index, sea_trade, map_file, overlay_file, radar_file, meaningful_id, preview_width, preview_height, preview_border | one row per theatre/playable area; `map_file`=`europe_map.tga` (campaign backdrop), `overlay_file`=`europe_lookup.tga` (region colour lookup), `radar_file`=`stratradar_*.tga`; `meaningful_id` = `europe_main` etc. Rows (5): see 2. |
| `regions` (1) | key, continent, r, g, b, battle_name | region key + lookup colour. `continent` FK to `regions_continents`: cont_africa_south, cont_america_latin, cont_america_north, cont_europe, cont_impassable, cont_india, cont_middle_east, cont_se_asia (8 rows). NTW uses only cont_europe (128 regions) and cont_middle_east (31). Newer schema block v5 (key, r,g,b, owner_bundle, faction_swapping_id) is a later patch format, not what this install has. |
| `campaign_map_settlements` (0) | settlement_id (`settlement:<region>:<town>`), region, default_onscreen_name, slot_count, slot_type | the one settlement per region + slot count (1..5). `toulon_tut` extra row for tut. |
| `campaign_map_slots` (0) | slot_id (`gold:eur_austria:rauris`), region, slot_type, rotation, underlay | resource/mine/farm/fort slots. |
| `campaign_map_towns_and_ports` (0) | town_id, slot_type, onscreen_name | |
| `campaign_map_famous_battles`, `campaign_map_tooltips`, `slots`, `slots_art`, `slots_templates_models`, `slots_gdp_values` | | slot types (21 rows incl. settlement_1..4_slot, port, fort, wheat/wine/iron/...), per-culture campaign models. |
| `factions` (3) | key, index, subculture, category, screen_name, screen_adjective, name_group, skin, ui_skin, is_rebel, mp_available, mp_available_naval, icon_path_units, flags_path, republican_flag_path, ..., colours (primary/secondary/uniform + alt), military_group, settler_rebellion_faction, ..., audio_faction_string, unit_regiment_name_group, ship_name_group, attack_desc, defend_desc | 77 rows. |
| `cultures` (0) / `cultures_subcultures` (0) | culture key,index,fallback_ui_culture / subculture,culture,index,farm | 9 cultures (european, middle_east, indian, tribal, egy_european, egy_middle_east, PIR_*); 16 subcultures (sc_european_west/south/north/east, sc_mideast_islamic, sc_indian_hindu/islamic/sikh, sc_tribal_*, sc_european_america ...). New nations must pick an existing subculture (it drives building/unit/name/uniform sets). |
| `faction_uniform_colours`, `uniform_to_faction_colours`, `uniforms` | per-faction RGB triples | |
| `groupings`, `groupings_factions_junct`, `groupings_continents_junct`, `groupings_cultures_junct`, `groupings_empires_junct`, `groupings_military`, `groupings_regions_junct`, `groupings_subcultures_junct` | | sets used by effects/missions/AI (25 groupings, e.g. all_european_factions, faction_france, region_egypt). Leftover Empire groups (factions_in_america, factions_india). |
| `trade_nodes` (1) | id, commodity, base_quantity, percentage_increase_per_agent, maximum_percentage_increase, group | 24 sea trade nodes (eur_atlantic_ocean_n_01..10, eur_aegean_sea_01/02, ...). Groups in `trade_node_groups`: eur_africa, eur_india, eur_north_america, eur_south_america, eur_black_sea, eur_mediterranean, eur_north_europe. Positions come from `trade_routes.esf` + `tradenodes/all_tradenode.rigid_model`, not the db. |
| `trade_theatre_commodities`, `trade_details` | | ETW trade-theatre commodity table is still in the pack (name in index); schema file lacks it. |
| `campaign_variables` (0) / `campaigns_campaign_variables_junctions` (0) | variable_key,value / variable_key,campaign_name,value | 121 global tunables; per-campaign overrides keyed by campaign name (`egy_napoleon`, `eur_napoleon`, `mp_eur_napoleon`, `spa_napoleon`, `tut_napoleon`, ...). **This is the only db table that names campaigns.** |
| `climates` (0) | climate_type, colour_index, conifer_line, tree_line, is_land | 33 rows. See 4. |
| `campaign_ground_types` (1) | type, movement_modifier, can_ambush, causes_heat_attrition, causes_cold_attrition | 19 rows (dense_forest ... Tundra_cold_att). Note: v1 NTW file; schema's newest block is a different layout. |
| `regions_continents`, `empires`, `seasons`, `resources`, `commodities*`, `population_classes`, `taxes_*`, `governorships`, `region_economics_factors`, `region_unit_resources` | | economy side. |
| `campaign_ai_personalities` (0) | personality, is_default | only 3: `default`, `eur_france`, `spa_spender`. Junction tables `campaign_ai_personality_junctions`, `campaign_ai_managers`, `campaign_ai_manager_behaviour_junctions`, `cdir_*` (cdir_campaign_junctions key->campaign, cdir_faction_junctions key->faction) assign AI behaviours per campaign/faction. |
| `diplomatic_relations_*`, `diplomacy_*` | | attitudes matrices. |
| `technology_faction_junctions`, `units_to_exclusive_faction_permissions` (key,faction,allowed), `unit_stats_naval_crew_to_factions`, `battle_type_faction_presets` (faction FK), `building_faction_variants`, `building_culture_variants`, `family_trees` (faction), `historical_characters` (faction FK), `names_*`, `unit_regiment_names`, `ship_names`, `loading_screens`, `pdlc` | | per-faction content hooks. |
| `battle_terrain_set_climates_jcts`, `climate_to_tilesets`, `sea_climate_details`, `fort_underlay_climate_jcts`, `small_vegetation_climates_jct`, `trees_climates_jct`, `battle_climate_groupings` | | climate -> battle terrain (section 4). |

Tables that do NOT exist in NTW: `campaigns_tables`, `start_pos_*`, `campaign_map_*_provinces`/`provinces`, `regions_provinces`, any `empires_regions_junct`, `groupings_regions_junct` (these two are in the pack listing but my schema lookup flagged them missing from schema_nap: they are in data.pack name list `empires_regions_junct_tables`, `groupings_regions_junct_tables`; schema gap, decode by hand). [L]

Mod mechanics note [L]: DME_campaign.pack ships `db\factions_tables\DMUC_factions_tables` (95 rows, db v2, Empire layout) as a *separately named file inside the same table folder* - the engine merges all files in a `<name>_tables` folder across packs, last loaded wins on key collision (standard TW behaviour; general knowledge, consistent with DME). Pack load order is defined via `user.script.txt` `mod <name>.pack;` lines [W general knowledge: TWC wiki, not re-verified here]. Pack type 3 = mod pack (DME_campaign type 3; data.pack type 1, boot.pack 0, local_en_patch 2, media 4). [L: header words]

### 3.3 How a new campaign is registered (what the evidence supports)

Evidence-based chain (each link [L] unless stated):

1. **Campaign folder** `data/campaigns/<campaign_key>/` with exactly `startpos.esf` + `scripting.lua` (all 8 vanilla campaigns: eur, egy, ita, spa, tut, mp_eur, mp_egy, mp_ita). Exe strings: `data/campaigns/%S/startpos.esf`, `campaigns/%S/scripting.lua`, `CAMPAIGN_STARTPOS`. Campaign key is a free name (DME's `DME` folder proves a non-vanilla key is accepted by the loader when UI starts it).
2. **Map link inside startpos**: startpos.esf contains the UTF-16 string `campaign_maps/nap_europe` and `campaign_maps/nap_europe/display` (positions 755850/755901 in eur_napoleon). The exe also builds `data/campaign_maps/` + `/regions.esf`, `/pathfinding.esf`, `/poi.esf`, `/sea_grids.esf`, `/trade_routes.esf`, `/metadata.dat`. So a new map is a new folder; no db row names the folder. The folder name strings `nap_italy,nap_egypt,nap_europe,nap_spain` (adjacent in the exe string pool at 0xf502e0) are in the Lua-doc string pool near CommanderTrait docs, i.e. probably a doc example list, not a registry. [I]
3. **Playable area row** in `campaign_map_playable_areas` with `meaningful_id` (`europe_main`) matched by a string in startpos (`europe_main`, `egypt_main`, `italy_main`, `spain_main` found in respective startpos).
4. **Campaign tunables**: rows in `campaigns_campaign_variables_junctions` keyed by campaign name (optional; falls back to `campaign_variables`).
5. **Localisation** (text\localisation.loc / ui.loc in local_en*.pack): keys `regions_onscreen_<region>`, `factions_screen_name_<faction>`, ..., exe pattern `campaigns_onscreen_name_%S` (campaign title; key itself not in the shipped loc that I could scan - [?] where the campaign title lives; likely ui.loc with a different prefix).
6. **Frontend registration is UI, not data**: the single-player campaign choice screens are layout files in data.pack: `ui\frontend ui\grand_campaign`, `ui\frontend ui\spain_grand_campaign`, `ui\frontend ui\mp_grand_campaign`, `ui\frontend ui\sp_episodic_campaign` (+ `.luac`), `ui\frontend ui\sp_tutorials`, `ui\frontend ui\host_campaign_popup`, faction pickers `faction_selection_big/historical/small`, scripts in `grand_campaign_scripts\{main_panel,faction_selection,grand_campaign,advanced_options}.luac`. `grand_campaign.luac` calls `FrontEnd:OpenMapDataFile`, `StartCampaign`, `selected_campaign`; `main_panel.luac` uses `Factions`, `ListOrder`, `button_faction_<n>`, `TheatreList`, `campaign_details`, `spanish_campaign`/`spa_napoleon` special case. The exe pushes a "campaign details" table to Lua with fields `TimeRemaining, StartYear, faction, StartingRegions, LeaderPortrait, ListOrder, VictoryConditions, GameTypes, TotalFactions, StartDate, BulletList, Unlocked`, plus `theatres`, `images`. Hence a new campaign button needs a **UI layout edit** (override files in a mod pack: DME_darthmod.pack does exactly that: ships replacement `grand_campaign`, `faction_selection_*`, `mp_grand_campaign`, `host_campaign_popup` layouts and `.luac`). Whether the campaign list is fully enumerated by `FrontEnd:EnumerateNapoleonsCampaigns` (episodic, historical) vs hardcoded names in layouts [?]. Cheapest path [I]: replace the files of an existing campaign slot (as DME does by swapping startpos under a vanilla name) rather than add a new button.
7. Multiplayer variants (`mp_*_napoleon`) need their own folders and appear in `multiplayer_online_scripts\campaigns.luac`.

Prior-art confirmation of the swap-in approach: Dawn of War 1792 "Tuscany" test pack = vanilla campaign + 1 new region, installed by dropping a startpos in `mp_eur_napoleon` and a regions file in `nap_europe` and a user-script pack entry https://www.moddb.com/mods/dawn-of-war-mod-for-napoleon-total-war (search snippet; a commenter reported units unchanged; unverified) [W]. Napoleon startpos mods all use `startpos.esf` + `scripting.lua` in the mp_eur_napoleon folder (Daum cafe collection snippet https://m.cafe.daum.net/shogun/4rgB/93 ) [W].

### 3.4 Adding a new region (minimal consistent set) [I from the evidence above]

1. `regions_tables` row (key, continent, unique r,g,b, battle_name). Key prefix convention `eur_...`.
2. Paint the region into `<map>_lookup.tga` using exactly that palette colour (palette entry == r,g,b; 256 palette max).
3. `campaign_map_settlements` (+ `campaign_map_slots`, `campaign_map_towns_and_ports`) rows.
4. `regions.esf` (region geometry, slot positions - 3D points include extra float vs ETW), `pathfinding.esf`, `poi.esf`, `sea_grids.esf`, `trade_routes.esf` entries; `display/borders/<region>_N.rigid_spline`, coastline, roads, rivers.
5. startpos.esf: REGION entries, settlement/building slots (slot type is numeric in NTW, 0..3, 5=prestige per a TWC post), CAI region ids (STARTPOS thread), `REGION_OWNERSHIPS_BY_THEATRE`.
6. Loc: `regions_onscreen_<key>`, settlement/battle names; battle map ("battle_name" -> battle terrain set via `battle_terrain_sets*`, `battles`, `battle_cities*`).
7. Balance: `tax_efficiency_total_regions` and similar.

Hard parts: items 4-5 (binary ESF). Only Esf Total Editor / etwng / custom code. `tools/esf.py` exists for this.

### 3.5 Adding a new playable faction [I from schema + data; steps from TWC STARTPOS thread headings]

TWC thread headings (husserlTW, "Minor faction playable", "Emergent to playable", "Playable to emergent", "Protectorate playable", "Change faction's capitol", "Change region's ownership", "Editing starting armies") [W] https://web.archive.org/web/20230504010805/http://www.twcenter.net/forums/showthread.php?339181-STARTPOS-ESF-analysis-and-modifications .

Data side checklist:
- `factions_tables` row: unique `key`, unique `index` (any int32; vanilla uses random ones), `subculture` (existing), `category` (playable/minor/non-expansionist/rebel), `screen_name`/`screen_adjective` (loc keys), `name_group`, `skin` / `ui_skin`, colours (primary, alt, secondary, uniform...), `flags_path`, `icon_path_units`, `republican_flag_path`, `military_group`, `settler_rebellion_faction` (points to the nation's rebel faction row), `audio_faction_string`, `unit_regiment_name_group`, `ship_name_group`, `attack_desc`/`defend_desc`, `mp_available*`.
- Rebel faction row for each new nation (the exe even has per-nationality battle strings `attack_<nation>_rebels`, `defend_<nation>_rebels` - unit-of-rebels hard-coded loc table: `attack_french_rebels`, `attack_maratha_rebels`, ...) [L strings]. New rebel types likely fall back to generic text [?].
- Units: `units_to_exclusive_faction_permissions`, `units_to_groupings_military_permissions` (`military_group` in factions), `units_to_gov_type_permissions`, `building_units_allowed` / `building_levels` + `building_faction_variants`/`culture_variants`, `unit_regiment_names`, `uniform_to_faction_colours`/`faction_uniform_colours` (per-faction RGB tinting; **no per-faction model needed if the culture/subculture already has models**), `battle_type_faction_presets` (MP/historical battle presets).
- AI: `cdir_faction_junctions`, `campaign_ai_personality_junctions` (only 3 personalities exist), diplomacy attitudes.
- Content: `names_*`/`family_trees`/`historical_characters`, `technology_faction_junctions`, `ancillary*`, `ship_names`, `loading_screens`, `pdlc` (DLC gating).
- UI: faction picker is built from the campaign details table (`Factions`, flag textures `ui\flags\<flags_path>\flag_animation0000.tga`, `LeaderPortrait`, `ListOrder`) - confirmed by `faction_selection.luac` strings (`flag_animation0000.tga`, `FlagPath`, `placeholder_faction_`). Playability itself is a flag **in startpos** (FACTION entries: playable/non-playable/emergent; `Unlocked` list), not in `factions_tables.category` (category is AI/diplomatic role). [I]
- startpos side: FACTION_ARRAY entry per faction (capital, treasury, government type, technology, diplomacy, armies, characters) - see TWC thread.
- Loc: `factions_screen_name_<key>` and family.

Known hardcoded faction keys: Lua docs/exe reference rebel-per-nation strings (`attack_american_rebels`, `attack_barbary_rebels`, `attack_maratha_rebels`, `attack_mughal_rebels`, ...); `campaign_variables` / scripts reference `france`, `britain` etc. by key; campaign scripting.lua files reference faction names in script logic [not audited]. In the NTW AI personalities, `eur_france` and `spa_spender` are campaign-specific. [L, partial]. Culture/subculture indices are fixed ints in `cultures_subcultures.index` (1..13 for original, big ints for newer) - adding a subculture is possible in principle (CA added `sc_egy_*`, `sc_PIR_*` that way with large indices) [L].

---------------------------------------------------------------------------
## 4. Climates and terrain

Local `climates_tables` (33 rows, NTW v0), identical in spirit to ETW's list - **all ETW climates survive**:
- land (is_land=True, 23): lc_am_desert, lc_am_great_plains, lc_am_jungle, lc_am_s_arid, lc_am_se_usa, lc_am_tropical_humid, lc_am_us_central, lc_am_us_east, lc_as_temp_humid, lc_as_temp_s_arid, lc_as_trop_humid, lc_as_trop_s_arid, lc_boreal, lc_desert, lc_eu_central_humid, lc_eu_north_humid, lc_eu_north_s_arid, lc_eu_south_humid, lc_eu_south_s_arid, lc_mediterranean, lc_sand_desert, lc_steppe, lc_tundra.
- sea (is_land=False, 10): sc_arctic, sc_arctic_coast, sc_lake, sc_mediterranean, sc_subtropic, sc_subtropic_coast, sc_temperate, sc_temperate_coast, sc_tropic, sc_tropic_coast.
- colour_index values 0..32 (campaign-map palette index), conifer_line 400 / tree_line 600 (land) or 1000 / 2000 (sea). [L]

Battle terrain support (`battle_terrain_set_climates_jcts`, 23 rows) maps each *land* climate to a texture-set grouping: lc_am_desert->Red_Desert, lc_am_great_plains->Prairie, lc_am_jungle->Humid_Forest, lc_am_s_arid->Savannah, lc_am_se_usa/lc_am_tropical_humid/lc_as_trop_humid->Jungle, lc_am_us_central->Central, lc_am_us_east/lc_eu_central_humid->Central_Green, lc_as_temp_humid->Humid_Forest, lc_as_temp_s_arid->India_Arid, lc_as_trop_s_arid->India_Central, lc_boreal->Moorland_Rocky, lc_desert->Rocky_Desert, lc_eu_north_humid->Bushy, lc_eu_north_s_arid->Lowlands, lc_eu_south_humid->Grass, lc_eu_south_s_arid->Arid_Half_Green, lc_mediterranean->Mediteraen_Rural (sic), lc_sand_desert->Desert_Dune, lc_steppe->Prairie, lc_tundra->Tundra_Frozen. Groupings enum `battle_climate_groupings`: Arid, Cold, Dry, Seascape, Temperate. Tilesets (`terrain_tilesets`): default, desert; `climate_to_tilesets`: lc_desert and lc_sand_desert -> desert. [L]

Whether the *battle terrain art for those groupings actually ships in NTW* (e.g. Jungle, India_Arid, Red_Desert, Savannah): `battleterrain.pack` is 2.26 GB and `battle_terrain_sets*` tables exist. I did not enumerate the pack contents per grouping. [?] Quick follow-up: list `battleterrain.pack` entries and check for per-grouping texture dirs (NTW removed some ETW battlefields; the db rows survive). `sea_climate_details` has all 33 climates with identical placeholder colours (sea 0.02,0.032,0.035; sky 0.49,0.54,0.65), i.e. water per-climate is not differentiated in NTW's data. [L]

Campaign movement terrain (`campaign_ground_types`, 19 rows): dense_forest, desert, grassland, hills, hilly_light_forest, jungle, light_forest, marsh, plains, swamp, tundra + `_cold_att` variants (cold attrition). Desert has heat attrition. Global attrition `maximum_attrition_pct` 0.15. These come from `metadata.dat` or the region ESF [?].

---------------------------------------------------------------------------
## 5. 4 GB / LAA, Proton, tooling

### 5.1 Large Address Aware: already set [L]
Command: python reads PE header of `Napoleon.exe`.
Result: Machine 0x14c (i386), Characteristics **0x0122** = EXECUTABLE_IMAGE (0x0002) | **LARGE_ADDRESS_AWARE (0x0020)** | 32BIT_MACHINE (0x0100); PE timestamp 2023-05-12 19:20:31 UTC (re-linked/repacked Steam build, not the 2010 original), image base 0x400000, 6 sections (.text 0xf058fc, .rdata, .data virtual 0x3f5ed8, _RDATA, .rsrc, .reloc), file 17,895,424 B.
=> A 32-bit process with LAA gets 4 GB address space on a 64-bit OS (Wine/Proton: WoW64/32-bit prefix ok; with PROTON_LARGE_ADDRESS_AWARE default on). The "4GB Patch" tools (NTCore https://www.moddb.com/downloads/4gb-patch1 , winget NTCore.4GBPatch) would be a no-op. Do not patch the exe: Steam verification and any mod tool that hashes the exe may complain.
If the process still dies near ~2 GB under Proton, check whether the launch path actually uses Napoleon.exe directly (not a launcher stub). [?]

Memory side effects of a big map [I]: heightmap 4096x2048 8-bit = 8 MB (tiny); fogmask 2048x4096 DDS, supertexture.stpd (streamed), `metadata.dat` 16 MB (egypt). The dominant cost is startpos/ESF object count, AI analysers (CAI_* builds N-region path analysers: `CAI_REGION_PATH_TRANSITION_ANALYSIS_*`), and unit models in battle. Late-campaign OOM reports [W] are ETW/NTW "old" 2 GB-limit tales; irrelevant if LAA is active.

### 5.2 Proton / Linux [W+L]
- ProtonDB app page https://www.protondb.com/app/34030 ; JSON summary https://www.protondb.com/api/v1/reports/summaries/34030.json -> `{"bestReportedTier":"platinum","confidence":"strong","score":0.54,"tier":"gold","total":64,"trendingTier":"gold"}` (fetched 2026-10-18). Individual report text not retrieved (JS-rendered).
- Local: Steam config assigns app 34030 -> `GE-Proton11-5-x86_64`; compat tools installed in ~/.local/share/Steam/compatibilitytools.d: GE-Proton10-17, 10-30, 10-33, 10-34, 11-5, proton-cachyos-11.0-20260703-slr; prefix `compatdata/34030/pfx` exists but has no `AppData/Roaming/The Creative Assembly/` yet, so the game has not been run here (it will create `Napoleon/scripts/preferences.script`, `user.script.txt` on first start). [L]
- `wine` and `protontricks` are installed (`which`), no RPFM binary installed (`which rpfm rpfm_cli` -> none), `cargo` is on PATH ([L] PATH).
- Useful config knobs for modding in preferences.script (names seen in an NTW/S2 forum paste, similar family): `vfs_log_level` (0 off, 1 mod-user, 2 dev) -> logs which files the virtual file system loads; `write_preferences_at_exit`; `gfx_*`; `campaign_unit_multiplier`. Use `vfs_log_level 1/2` to verify that a mod pack overrode a db/ui file [W: https://steamcommunity.com/app/34030/discussions/0/135511913390479506 ; same key list is the Warscape preferences format].
- Steam launch option suggestions from ProtonDB-style threads for other Total War titles (not NTW-specific, unverified for NTW): `DXVK_ASYNC=1 gamemoderun %command%`, `PULSE_LATENCY_MSEC=60 %command%` (audio crackle), try Proton Experimental / GE-Proton if crash. [W, other titles]
- Darthmod must be launched from inside Steam (Steam thread snippet https://steamcommunity.com/app/34030/discussions/0/1489987634009755088/ ) [W, tangential].
- Tooling that runs on Linux: RPFM (Rust, native; https://github.com/Frodo45127/rpfm; supports NTW via schema_nap.ron) [W]; taw/etwng (Ruby) https://github.com/taw/etwng ; the local python tools in tools/{packtool.py,esf.py}; Windows-only tools via wine: Esf Total Editor, EditSF, EasyEsf, PackFileManager 3.5.2 (.NET) [TWC wiki index]. NTW Data Checker v1.4, Scripting and Debug Toolkit v1.1 (TWC wiki).
- PFH0 pack format (local, confirmed): header `PFH0`, type u32 (0 boot,1 release,2 patch,3 mod,4 movie), pi_count, pi_size, file_count, index_size; index entries = u32 size + NUL-terminated path (backslashes); no per-file compression; data concatenated in index order. `data.pack` has 19,235 files / 2.85 GB, `local_en_patch.pack` 112, `boot.pack` 19.

---------------------------------------------------------------------------
## 6. Prior art (all secondary, treat as claims)

- **Distant Seas** (given peace): total conversion, "global campaign on a spherical map: Europe, Americas, Africa, Asia, Pacific; naval invasions; new coastal factions" https://www.youtube.com/watch?v=hNKhk6Tmrac , Patreon https://www.patreon.com/DistantSeas , channel https://www.youtube.com/@DistantSeasMod , teaser short https://www.youtube.com/shorts/eyBdeE6js2Q . Coverage by Gudea Academy: "Napoleon: Total War has 65,571 functions, no source code ... One modder is reading every single one and rewriting it ... about 6% of the way there ... unlocking ... new regions the AI actually reacts to, mid-battle save states, and a spherical globe campaign map" https://www.youtube.com/watch?v=7f31ynwtYvo (chapter title "The wall every Napoleon modder hit"; transcript not available). Also mixed land/naval battle AI rebuilt at binary level https://www.youtube.com/watch?v=mnv88LaOYlI , amphibious battles https://www.youtube.com/watch?v=_gI7D-INMLw , naval AI training https://www.youtube.com/watch?v=3JnRMmRilcc , full overview https://www.youtube.com/watch?v=YNvzUkNTkKQ .
  Implication [I]: db-only edits reach a ceiling ("the wall"); a truly global map with working AI may require exe patching/hooks. Our mod may need to coordinate with or avoid duplicating Distant Seas.
- **OpenETW** (daruskiy): "Open Empire Total War - Global Map Platform. Expanding the ETW Map!", 22 comments, author claims seamless world map by end of 2026 (translated comment) https://web.archive.org/web/20261004191456/https://www.moddb.com/mods/openetw ; Gudea Academy videos: https://www.youtube.com/shorts/s8iQCLi_R6Q ("France and Spain are more than one region now"), https://www.youtube.com/watch?v=I2bcONI-YQ0 , community Discord linked from that video description (https://discord.gg/wMSxWgnsKa, as printed in the description).
- Older: "Big Map for Absolutum Dominium" (ETW; extra regions/factions, early campaign only) https://www.moddb.com/mods/big-map-for-absolutum-dominium (snippet); Dawn of War 1792 Tuscany pack (NTW, +1 region) see 3.3; TWC "adding new provinces" https://www.twcenter.net/threads/adding-new-provinces.542507/page-2 (snippet: modder noticed pathfinding data in startpos contained more forts than vanilla) ; TWC "how to add new regions" https://www.twcenter.net/threads/how-to-add-new-regions.341368/ (2010; reply: "MUCH more complicated" than copying Empire's map).
- twcenter.net and wiki.twcenter.net return HTTP 403 to scripted fetches; wayback captures work for some.

---------------------------------------------------------------------------
## 7. Risks for the global-map mod (ranked)

1. **AI / startpos assumptions**: CAI world analysers are built from startpos; large region counts, new theatres or non-vanilla topology may crash or idle the AI. Needs smoke test with a tiny edit (add 1 region) before scaling. (1.4, 6)
2. **ESF editing fidelity**: regions.esf / pathfinding.esf / poi.esf are huge binary graphs (9 MB / 4.8 MB / 1.5 MB for europe); only partial format knowledge public ([etwng ESF.txt] says "Data within is barely known"). Round-tripping already broke for one 2010 user (16 MB vs 9 MB output).
3. **Lookup palette**: 256 colours per lookup image -> split into theatres or reuse colours across disjoint theatres. Unverified whether the engine really requires a 256-colour paletted TGA or accepts 24-bit.
4. **Frontend**: campaign menu needs UI layout/Lua edits (not db).
5. **Culture content**: ETW's non-European cultures (indian, tribal, american) rows exist, but whether NTW ships all models/buildings/units for them is unverified; DME's Empire startpos in this folder suggests content was imported from ETW.
6. **Balance constants** tied to region count (`tax_efficiency_total_regions=136`).
7. **Theatre transitions**: code exists but untested by CA in NTW data; prefer single-theatre.

---------------------------------------------------------------------------
## 8. Open questions / suggested next probes (all read-only unless noted)

1. Enumerate `battleterrain.pack` per climate-grouping dir to answer "does each ETW climate have NTW battle terrain art?" (4).
2. Parse `campaign_map_playable_areas` references and the playable-area/transition structures in eur/egy startpos (`THEATRE_TRANSITION_INFO`, `CAMPAIGN_MAP_TRANSITION_LINK`): what do they contain for single-theatre campaigns? Use tools/esf.py.
3. Decode `metadata.dat` byte values vs `campaign_ground_types` / climates (2048x1024 for europe, half the heightmap height - check the mapping to heightmap pixels).
4. Reverse the world-coordinate extent: compare region.esf settlement coordinates to heightmap pixel positions for known cities (Paris, Moscow) to derive units per pixel; compare `character_recruitment_max_distance` 550 (eur) to map units.
5. Find where campaign titles/descriptions live in loc (`campaigns_onscreen_name_%S`, description) and whether `FrontEnd:EnumerateNapoleonsCampaigns` reads a directory.
6. Whether Napoleon.exe actually loads the DME (Empire) startpos (needs a run; not allowed in this task).
7. Look for the regression behind Distant Seas' "wall": candidates: hard-coded per-region arrays sized by vanilla counts in the exe (search ESF parse code for fixed-size arrays; needs disassembly), `faction_swapping_id`/region-owner-bundle in newer schema blocks.
8. Check `scripting.lua` of eur_napoleon / `episodicscripting.lua` / `export_*.lua` for hardcoded faction and region key lists (events, missions, advice) that a global map must extend.
9. Confirm 256-colour requirement of lookup TGAs and whether 24-bit lookup works.
10. Reach OpenETW / Distant Seas authors (Discord) for ground truth on limits; their findings supersede everything in section 1.
