# Local findings (main session, from the installed game files)

Tools: `tools/packtool.py` (PFH0 list/extract/build, validated on all 28 installed packs),
`tools/esf.py` (ABCE ESF load/dump/save; byte-exact round-trip on all 34 campaign ESFs:
5 maps x {regions,pathfinding,poi,sea_grids,trade_routes} + 9 startpos). Python env: `.venv`.

## Coordinate system (nap_europe)
- World extent in regions.esf `region_data`: (-640,-320)..(640,320) = 1280 x 640 units.
- Playable theatre `1244818741`: (-410,-190)..(340,195) = 750 x 385 units.
- heightmap.tga 4096x2048 L8 -> covers world extent, 0.3125 u/px. Values 0..226.
- metadata.dat: 12-byte header (u32 'MAPI'? 0x4947414D..., u32 2048, u32 1024) + 2048x1024 u8 = world extent, 0.625 u/px.
  Values: 6 = sea (465,406 cells), 0 = land / off-map, 1 = 5 cells. Row 0 = north.
- europe_lookup.tga (P, 605x300, 85 colours) / europe_map.tga / stratradar (RGB 605x300) = minimap/UI images of the theatre.
- pathfinding.esf / poi.esf use int32 fixed point, 1 unit = 2^20 (e.g. -429916160 = -410.0).
  => representable range +-2048 units on each axis (4096 x 4096 max), if the engine uses the same convention.
- Scale: Europe theatre spans ~65 deg of longitude in 750 u => ~11.5 u/deg. Whole globe at that scale ~4140 u wide,
  just over the +-2048 fixed-point range: full world needs either a smaller scale or polar/ocean cropping.

## regions.esf top level
theatres_and_region_keys (theatre id, bounds, region_keys + centre xy) | theatres (bounds, 2x climate_map u32 w,h + u8 grid
2344x1203, wind_map 300x154 i8, **transition_areas** (empty: Empire's theatre-transition system still exists in the format)) |
black_shroud_outlines | region_data (shared vertex pool xy[33073]; 101 regions incl. 'eur_map_west/east' land and sea
regions; each region -> areas -> faces u32[] + outlines + connectivity) | mountain_data | climate_indices (23 land incl.
Empire leftovers lc_am_desert, lc_am_great_plains; 10 sea incl. sc_arctic) | query_info (quadtree) | groundtypes (8:
grassland, light_forest, ...) | map_heights | trade_nodes (19) | bridges xyz[149].

## pathfinding.esf
pathfinding_areas x1 -> vertices (93,380 fixed-point pairs) + u32[369,994] + grid_data (origin -410,-190 fixed, cell 2.0 u,
375 x 193 cells, 22,242 grid_cells each with u8[8] + boundaries + u8[18780] blobs). Hardest file to regenerate.

## Other
- sea_grids.esf: CAI sea grid, 75-unit cells, 11x6 over the theatre. Simple, regenerable.
- trade_routes.esf: SPLINES (766), PORTS (39), SETTLEMENTS (72), ROUTES (912 graph edges w/ cost), TRADE_NODE_ROUTES.
- poi.esf: CAI points of interest (5,513), fixed-point positions.
- display/: per-region border & road rigid_splines, coastline rigid_mesh, supertexture.stpd (124 MB), fogmask/snow dds.
- Installed DarthMod (DME) packs are loaded too; DME_campaign.pack (type 3 mod) overrides db\factions etc.

## Extents differ per campaign map (so the world box is data-driven, not hard-coded)
| map | theatre bounds | world bounds | metadata.dat | heightmap | climate_map | regions |
|---|---|---|---|---|---|---|
| nap_europe | (-410,-190)..(340,195) | +-640 x +-320 | 2048x1024 | 4096x2048 | 2344x1203 | 101 |
| nap_egypt | (-220,-260)..(220,260) | +-320 x +-320 | 4096x4096 | 2048x2048 | 1375x1625 | 36 |
| nap_italy | (-185,-120)..(175,105) | +-320 x +-320 | 2048x2048 | 2048x2048 | 1125x703 | 32 |
| nap_spain | (-213,-179)..(219,206) | +-320 x +-320 | 2048x2048 | 2048x2048 | 691x616 | 37 |
- climate_map resolution is ~3.125 px per unit of theatre size (Europe 2344/750, Egypt 1375/440, Italy 1125/360); spain differs (1.6).
- heightmap = 3.2 px per world unit in Europe and Egypt (4096/1280, 2048/640).
- Geographic scale is per campaign: Italy ~30 u/deg vs Europe ~11.5 u/deg. A world map can choose its own scale;
  the constraint is gameplay feel (army/settlement model sizes are in world units) and the +-2048 fixed-point range.

## The "DME" install is DarthMod **Empire** (an Empire: Total War mod) dropped into the Napoleon folder
- `data/DME/dme_log.txt` (12/10/2026): "Selected campaign: Early", "boot.pack removed"; Steam later re-verified vanilla files (Oct 18).
- `DME_Media.pack`, `DME_MediaUC.pack`, `DME_UPC_v6_3.pack` are type-4 (movie) packs: NTW auto-loads movie packs, so Empire content
  is likely being loaded into Napoleon. Before any in-game test, move every `data/DME_*.pack` into a backup folder (reversible).
- Useful as a **format reference only (CA content, never ship it)**:
  - `data/DME/Campaigns/{Custom,DME/Early,DME/Late,Empire,Mp}/*startpos.esf`: Empire multi-theatre startpos files. They parse and
    round-trip with tools/esf.py. 4T_startpos has REGION_OWNERSHIPS_BY_THEATRE x3 (Europe/America/India), CAI_WORLD_THEATRES x7,
    CAI_WORLD_TRANSITION_AREAS x23, navy THEATRE_TRANSITION_INFO/CAMPAIGN_MAP_TRANSITION_LINK, trade THEATRES x4.
  - `DME_Custom.pack: campaign_maps/global_map/*`: only Empire's UI rasters (lookup/map/stratradar TGAs for europe, america, india,
    brazil, east_indies, ivory_coast, madagascar). No regions/pathfinding ESF or terrain.

## Vanilla projection (fitted 2026-10-18)
- Fitting the 72 settlement positions in `mp_eur_napoleon/startpos.esf` (REGION_SLOT `settlement:<region>:<town>:...:0`, int32 x·2^-20)
  against real lon/lat: nap_europe is **plate carrée**, x = 13.14·lon − 240.9, y = 13.04·lat − 636.1 (rms 5 u; towns are hand-placed).
  Miller (5.7) and Mercator (7.0) fit worse, conic far worse. No cos(lat) shrink in x.
- Whole world at 13.1 u/deg = 4717 u wide: exceeds the fixed-point range (int32·2^-20 → |x| < 2048).
  Equirectangular at ~11.3 u/deg fits in ±2040 (86 % of vanilla scale); lat −58..78 → ~1540 u tall.
- heightmap.tga is **land relief only** (sea and plains are 0, Alps max 226) and its content spans the theatre, not the world box.
- metadata.dat does not share the heightmap's frame (sea mask is offset/scaled): extent under investigation (research/08).
- Heightmap resolution: **fixed 3.2 px/unit, framed as a box centred on the world origin** (image size / 3.2), independent of
  the regions.esf box. 8192x4096 and 12288x6144 are accepted (G2). (An earlier "2048x1024 renders flat" note was taken with a
  broken TGA header and is void.)
- Supertexture probes (2026-10-18, in game): a half-density supertexture (16384x8192, levels = vanilla levels 1..5, with or without
  an extra 1x1 level, header field 6 or 5) renders **black terrain**. Treat density as fixed at 25.6 texels/unit over the world box.
  **Shared tile offsets work**: pointing every level-0 index record at one tile's data renders fine. So a world supertexture can
  store each distinct tile once (open ocean = a handful of blobs). World 4068x1537 u -> ~104k x 39k texels, ~16k level-0 tiles.

## Startpos pathfinder probes (2026-10-18, in game, Coalition campaign on cloned nap_world)
- `CAMPAIGN_PATHFINDER/PATHFINDING_GRID` with **zero items** → crash on campaign load.
- Same item kept but **all dynamic obstacle content emptied** (field0 = 0 dynamic polygons, dynamic stream/lookup empty,
  OBSTACLE_BOUNDARY_MANAGER, OBSTACLE_BOUNDARIES, OBSTACLE_BASE_GRID_NODE, OBSTACLE_LISTS incl. 103 CHARACTER_OBSTACLE all
  empty; per-domain bool[222]/f32[222] kept) → **loads and plays**: two AI turns, French armies marched and attacked Austria
  (battles in Bavaria and Tyrol), auto-resolve fine. So a generated startpos needs only the per-path-domain arrays, not the
  character obstacle graph. (Side effect untested: characters may not block each other until the engine re-registers them.)

## Gate G2: bigger world box (2026-10-18, in game, Coalition campaign, vanilla Europe embedded unchanged)
- PASS for centred ±1280x±640 and ±1920x±960 (tools/probe_g2.py + regridded startpos): terrain, settlements, armies, flags,
  labels, fog, intro camera pan, advice, AI turn and battle deployment all work.
- Terrain (heightmap 3.2 px/u, supertexture 25.6 texels/u) is centred on the origin, NOT on the regions box: keep boxes centred.
- Enlarging the regions box without other changes → game logic runs (armies in Lists panel, AI moves, battles) but characters/
  flags are invisible and the map is shrouded. Causes, all keyed to the regions box min:
  - **Visibility grids** (QUAD_TREE_BIT_ARRAY: LINE_OF_SIGHT per character, CAMPAIGN_SHROUD 5 factions x 3 arrays): fixed
    1.25 u/cell from the box min, y north-up, header W,H = box/1.25 (vanilla 1024x512). Must be regridded
    (`campaign_misc.regrid_visibility`). Old-sized arrays hide characters.
  - **pathfinding.esf grid_data** u16 start cells = (theatre min − box min)/2 u (vanilla 115, 65). probe_g2 patches them.
  - EPISODIC_RESTRICTIONS children[9:13] world rect: set to the box.
  - The intro script's `show_shroud(false)` during the camera pan masks shroud breakage; with the pan disabled a broken grid
    shows a fully black map.
- QTBA layout: u32 W, H, root (pow2 ≥ max(W,H)); child k covers x half k&1, y half 1−(k>>1); 8x8 leaf = u32 lo, hi with
  bit r*8+c = cell (c, r) north-up; bigger uniform leaves are (0,0) or (FFFFFFFF,FFFFFFFF). Shroud arrays 0, 1 identical, 2 empty.
- Zoom-out stays limited by the campaign script's set_zoom_limit; the minimap still shows europe_map.tga (rebake later).

## Gate G3: one world-sized theatre (2026-10-18, in game, Coalition campaign as Britain)
- PASS (tools/probe_g3.py): theatre (-1910,-940)..(1910,950), pathfinding grid 1910x945 cells (25x vanilla; vanilla 375x193
  pasted at col 750, row 375), climate maps resampled to 1.6 px/u, wind map 0.4 px/u, sea grid 51x26, startpos pathfinder
  obstacle state emptied. Loads; 5 end-turns with AI turns, diplomacy, events and an auto-resolved naval battle; a fleet
  ordered 600 u west of the old map edge sails there over 3 turns, renders with its sight ring, and an AI fleet follows it.
  A second theatre (G5) is not needed.
- Fleet orders need two things: a **sea region** under the target in regions.esf (the Atlantic polygon was grown west; flipping
  the off-map region `eur_map_west` to kind sea did nothing), and **pathfinding connectivity** (the vanilla map-edge strip
  cells around x -392 have sea polygons closed to the W, middle20 W nibble 0, so they had to be replaced too).
- **Crash lesson:** the first G3 build put uniform sea cells directly next to uniform off-map cells. Vanilla never does this:
  both cells of every shared side split it into identical sea/land/blocked intervals with identical vertices
  (tools/pf_check.py: 0 mismatches in vanilla; boundaries between domains never lie on a cell side). On the 3rd end-turn the
  game died with out-of-memory: napoleon.exe+0x755f6b (VA 0xb55f6b), a vector<u32> push_back in an outline-tracing routine
  (0xb555a0, called by 8 template instances) had grown to 134M entries and asked for 1 GiB. Rebuilt with welded mixed
  "rim" cells (half-cell raster + strips/vertex import matching vanilla neighbours), it passes. **Every generated grid must
  pass pf_check with 0 unwelded sides.**
- Napoleon.exe is large-address-aware (characteristics 0x122), so the 32-bit process has 4 GiB under wow64.
- The minimap still shows europe_map.tga but maps clicks onto the whole theatre, so clicking it throws the camera into black
  unexplored shroud far off-map. Rebake the minimap image (Phase 4). The off-theatre supertexture shows grey-green
  parchment; the probe's filler tile (vanilla recs[0]) shows as brown wood.

## Projection decision (2026-10-18)
Piecewise-linear plate carrée: identity on the vanilla Europe band, so all vanilla Europe data (regions, pathfinding cells,
rasters) is reused unchanged and the rest of the world is compressed around it, with the seam in the Pacific. G3 shows a
world-sized single theatre is viable, so no second theatre is needed for the Americas or Asia.

Numbers (`tools/proj.py`, self-checked): identity on (-410,-190)..(340,195) = lon -12.87..44.21, lat 34.21..63.74. Outside,
each axis is linear to the theatre edge: x 9.61 u/deg west, 10.70 u/deg east; y 10.15 u/deg north and south. Seam 169 W.
World box (-1920,-1280)..(1920,1280); theatre (-1910,-1240)..(1910,365) (lat -58 -> y -1126, lat 80 -> y 360), chosen
so 2-unit pathfinding cells and 75-unit sea-grid cells stay aligned with vanilla. Land: `tools/worldgeo.py` (Natural
Earth 10m land + minor islands - lakes). Seam-cut geometry must be projected with `to_world(..., wrap=False)`, or
vertices on the cut wrap to the far edge and draw hairlines across the oceans.

## M1 "world ocean" in game (2026-10-18)
Build: `tools/world_build.py` (reuse regions, 101 regions), pf_gen pathfinding, parchment-era terrain bake, packed as
`zz_gn_world.pack` (799 MB, 440 files), loose startpos_m1. Coalition as Britain:
- Loads into nap_world. Terrain, settlements and characters render, and the new minimap shows.
- 5 end-turns with full AI turns: diplomacy offers, trade-raid events, Austria/France turns. No crash, no OOM. Log noise is
  only DBG_PRINTEXCEPTION traces.
- Fleet tooltip reads "Atlantic Ocean - Right click to sail here" far west of the old edge. The order is accepted with a
  multi-turn route (red/blue/yellow legs) through generated cells. Whether the fleet actually arrived was not checked
  visually; retest with a one-turn hop.
- Edge-scroll (mouse at the screen edge) pans the camera; xdotool arrow-key holds do not.
- The old bake's parchment frame shows in game as a green strip at the vanilla VT edge. Fixed by the lane B painted-mask
  rebake (research/07).
- **Localisation loading (verified 2026-10-18):** `text/localisation.loc` in a mod pack (type 3, listed in user.script) is
  ignored, and so is an extra `text/gn_world.loc`. The same full file in a **type-2 (patch) pack** `local_en_gn.pack` is read
  and wins over local_en_patch.pack: the region, settlement and sea-tooltip probes all showed. (A mod-pack `text/ui.loc` does
  load; the exe hard-codes both names.) Type-2 packs in data/ load without user.script, so the test pack must be removed
  after every test. Coalition settlement labels use the `...dublin1584883816` suffix. A release has to merge our rows into
  the player's own localisation.loc rather than ship CA's file.
- Terrain with the painted-mask rebake (EDGE_TRIM 9): no parchment strip in game; sea runs on past the old edge.
- **Zones variant (139 regions, 38 wld_ seas):** regions.esf + world_zones poi/sea_grids load with the *plain* startpos
  (CAI tables left at vanilla's 101 regions). Tooltips show the new seas ("North Atlantic Ocean"), and two AI turns run at
  about 2 min each. The startpos_zones() CAI edits crash the campaign load with a null deref:
  napoleon+0x96d9e0 `mov eax,[ecx+0x10c]`, VA 0xD6D9E0 at base 0x400000, caller VA 0xC3FD30. Bisect pending.

## First new land region in game (2026-10-18, tools/land_probe.py, research/10 §5)
`nam_probe` = Newfoundland (region 101, owned by Britain, settlement "Probetown", trade variant A, vanilla CAI tables, no
CAI shadow records). It loads, renders and labels the settlement ("Probetown, Newfoundland", player-red), selects as Region
Capital with construction/recruitment panels, and survives 3 AI turns. This answers research/10 open question 1 for the
first turns: an owned settlement with no CAI_REGION/CAI_SETTLEMENT/HLCI records is tolerated. db `regions_tables` and
`campaign_map_settlements` were shipped as full tables in the type-3 mod pack.
- Zones bisect: the crash is only the 6 CAI_REGION_BOUNDARY records between vanilla seas and new seas (sp_abv). The
  new-new boundaries, the rescaled lengths, new CAI_REGION/HLCI records, the 1122 sea cells and the counter bump all load.
  sp_de: 6 AI turns, about 5 min each (plain startpos about 2 min), and a fleet sailed from the Channel into
  wld_north_atlantic over 6 turns.
- Harness: the minimap click doesn't move the camera; edge-scroll about 26 s west of London reaches Newfoundland.
- Group fix (stage g: new seas in sea region group 3789) does not help: sp_abv_fixed and sp_abcde_fixed still crash at
  0xD6D9E0. Adding stage h (per-region CAI beliefs cloned from eur_norwegian_sea: border analysis, occupancy, 7 military
  strengths, border patrol, all 11 region-keyed analysers) turns the crash into a **load hang**: sp_abvgh sits at ~15% of
  the loading bar with one core at 100% and constant RSS for 8+ min. Vanilla-sea <-> new-sea CAI boundaries are parked.
- Fallback sp_abndeg (everything except those 6 boundaries; new-new boundaries, CAI regions, sea cells, group 3789)
  loads to the campaign map.
- sp_abndeg (stages abrndeg) survives 3 AI turns (Early Jan to Late Feb 1805, about 9.5 min of wall time each with
  generous waits). It is now the world_zones default; `world_build.py --zones` reproduces it byte for byte.
- Probe B1 (3 adjacent US regions, Britain, tools/land_probe_b.py): the B1 map files load with probe A's startpos, but
  the B1 startpos crashes right after "Done Campaign Terrain Display", i.e. in Campaign Building Display:
  napoleon+0x5625e8 `mov ecx,[ebx+8]`, ebx=0x2c. Being fixed by lane F.
- Flags (tools/flags.py, lane G): the 24-file `ui/flags/<dir>/` set for all 66 new factions, all drawn by code (16
  historical designs, 50 colour placeholders), self-check passes. Not yet tested in game. The DDS files are DXT5 (vanilla
  uses DXT3), and about 20 vanilla factions ship TGA only, so the DDS can be dropped if it fails. `morocco` and `mysore`
  already have vanilla flag dirs, so the faction lane must use distinct flags_path dirs.
- **Hard-coded building-display box (lane F, disassembly):** buildings go into a quadtree with fixed root bounds x,z in
  [-1000, 1000] (16-byte constant at VA 0x1363EE0, plus an immediate 1000.0 at VA 0x9009B0). An insert outside the box
  returns NULL, and building display then faults at 0x9625E8. B1's US settlements were at x ≈ -1022..-1102. The world box is
  ±1920, so the full map needs an exe patch (planned: a patcher run on the player's machine) or settlements within ±1000.
- B1 with settlements inside the box (Boston, Sherbrooke, Moncton): loads, labels render, the hover shows the owner,
  and Boston selects as Region Capital. End turn crashes: after queuing a recruit at napoleon+0x8d94e5 (caller near
  0xC3FCF0), and with plain end turns, turns 1-2 pass and turn 3 crashes at napoleon+0x85f363. Probe A (island) passed 3
  turns, so land-adjacent regions seem to need data the AI turn walks. Lane F is analysing.
- **Root cause of both B1 end-turn crashes (lane F):** every CAI army/fleet/agent's CAI_SITUATED (+8, field +0x10) points
  to the CAI_REGION it stands in. The new regions 101-104 had no CAI_REGION, so the AI task loops (0xCD8D70, goal
  0xC5F2F0) dereference NULL. Probe A only survived because nothing ever stood in Newfoundland. Fix: land_probe_b
  cai_regions() adds CAI_REGION + HLCIs + new-new boundaries + region group (the world_zones recipe).
- Display boxes in the exe are only Building (VA 0x1363EE0 + imm 0x9009B0) and Tree (VA 0x1363ED0 + imm 0x903BC2),
  both x,z ±1000. The other displays (Effects, Terrain, Border, Road, Shroud, Trade, Marker) have no bound. Patch for
  ±2048: file offsets 0xF62CE0/0xF62CD0 (min x, min z, max x lanes) and 0x4FFDB0/0x502FC2 (max z).
- B1 with cai_regions() (CAI_REGION records with Ireland's settlement, slots, mobiles and governorship cleared) crashes
  earlier, during load right after CAI_INTERFACE creation: VA 0xC3C330 `mov eax,[ecx+0x168]`, ECX=0, from the CAI task
  loop (0xCCD01B). Lane F is analysing.
- B1 + CAI_SETTLEMENT/owner links (lane F): loads and the campaign starts. France's turn 1 AI then crashes at VA 0xD96AC0,
  a vector erase-by-value whose shift loop overruns when the value is absent. It corrupts the heap, so Wine's crash
  handler hangs in heap_allocate_block, which looks like a frozen AI turn. To tell hang from crash, run gdb on the busy thread:
  `gdb -batch -p <tid> -ex bt`; the original fault is the last non-DBG `dispatch_exception code=` line in the Proton log.
- Note: /tmp/turns.sh "turn N: running" only means the game is alive; check the date in the end screenshot.
- tools/exe_patch.py (status|patch|restore): widens the building and tree display boxes to ±2048, patching only the
  vanilla Steam exe (sha256 44880ec1...). The patched exe loads the world_m1 zones build to the campaign map. Test
  routine: restore the exe after each test, like the startpos.
- Showcase pass (2026-10-19, unpatched exe): far out in the western Atlantic, the camera pan stops at a limit, and
  past a straight line the screen is pure black (no sea or terrain drawn). New England (x ≈ -1000) still renders. Open:
  find the camera bound and the render extent (metadata/camera limits or another exe constant).
- **Terrain display extent (lane H):** the terrain grid and draw box are hard-coded at ±1280 x ±640 (grid init
  0x11C0E00 called with 256x128 cells, draw box VA 0x1457F1C). That causes the black area and the camera stop. The
  `terrain` group in tools/exe_patch.py (±1920 x ±1280, 384x256 cells) fixes both in game: the camera pans from New
  England past the Caribbean into the "North Pacific Ocean" with the Central American coast drawn. Camera rectangle
  itself comes from startpos EPISODIC_RESTRICTIONS (already ±1920 x ±1280 in our startpos).
- East B1 with the region-group map fix: 4 full AI turns (Early Jan to Early March 1805, date checked). Recruiting a
  unit in Boston then crashes at 0xD6D9E0 (null+0x10C, the zones crash site; likely per-region
  CAI_REGION_MILITARY_STRENGTH missing). Lane F is adding the per-region beliefs.
- East B1 + per-region beliefs (land_probe_b land_beliefs: 22 beliefs per region across the 20 region/settlement-keyed
  analysers, cloned from eur_ireland): recruiting Fencibles in Boston works. The unit appears in Boston's new Army tab,
  and 3 AI turns run (Early Jan to Late Feb 1805). The recruited army's movement range crosses the land border into Lower
  Canada, and it marches north towards Sherbrooke.
- Army walk passes: the Boston recruit marched over 2 turns from US Northeast across the new land border to Sherbrooke
  (Lower Canada), and the AI turns ran with it standing there. Note (corrected below under Real AI turn times: about 100 s): these AI turns can take more than 7 min with the zones
  build, so /tmp/turns.sh's fixed wait can miss a turn; always check the date.
- us trio B1 (Washington, Richmond, Cincinnati, x ≈ -1022..-1102) with the patched exe (display + terrain): loads,
  the settlements render (Cincinnati's buildings visible, Lake Erie drawn), and 3 AI turns run (Late Feb 1805). This confirms
  the display patch in game.
- East B2 (new faction usa) crashes at load at VA 0xA8E6C0: there is no CAI_FACTION for usa (the game→CAI faction hash
  lookup 0xA86F80 misses, unchecked). A full CAI faction clone is about 320 components + 190 edits. Testing first: repoint
  dormant hannover's CAI faction (777) at usa.

### Real AI turn times (2026-10-19, `tools/ntw.sh turns N`)
- `ntw.sh turns` ends a turn and waits until the HUD date text changes. The date crop is thresholded because the HUD dims
  during the AI turn, and half-written screenshots are skipped. Earlier per-turn times (5 to 9.5 min) came from fixed
  waits in turns.sh and were not measurements.
- Vanilla Coalition (empty mod pack, vanilla startpos): 106 s, 106 s. Zones world build (sp_abndeg = startpos_m1.esf):
  93 s, 119 s. The world map and its 954-cell sea grid add no measurable AI turn time, so no sea grid change is needed.

### Probe B2: first new faction in game (2026-10-19)
- Option 1: hannover's dormant CAI faction 777 is repointed at the appended game faction usa, with a usa governorship
  (no governor), a usa-owned region group in the analyser-5 map, and trio settlements owned by 777. No RTPA infos and no
  CAI characters; the load sync creates what it needs.
- East trio (Boston, Sherbrooke, Moncton): loads, 3 AI turns (Late Feb 1805; 106/132/93 s). Boston reads "Region
  Capital, United States". Diplomacy lists United States under Minor Nations (Oldenburg's cloned flag and leader
  Wilhelm I), Open Negotiations works. The attitude map shows no colours for usa, so per-pair records may be missing.
- US trio (Washington, Richmond, Cincinnati), patched exe: loads, 3 AI turns (Late Feb 1805; 106/106/93 s).
- Only 20 dormant slots exist for about 66 new factions, so lane F is writing a CAI faction generator (option 3).

### Probe b3: two generated CAI factions (2026-10-19)
- tools/cai_faction.py `clone_cai_faction()` clones oldenburg's CAI faction (453 components) for a new game faction;
  b3 = usa (Boston) + BNA (Sherbrooke, Moncton), hannover's 777 left dormant. Static checks pass.
- In game (east): loads, turn 1 OK (105 s), then a crash in the turn-2 AI phase after the autosave: NULL read at
  VA 0xB83E22 (`mov esi,[eax+0x1c]`, eax 0; callers 0x137FA80, 0xBB9A90). Lane F is tracing it.
- Cause (lane F): 0xB83C30 is a turn-start pass over trade routes. It looks up the route keyed by the two settlement trade
  nodes (here 112, 113 = Boston, Sherbrooke) with no NULL check. Vanilla has a route between every pair of adjacent
  settled regions, so new regions need TRADE_ROUTES between adjacent settlements (startpos + trade_routes.esf). It only
  bites once two factions border: b1/b2 (one owner) never looked the pair up.
- With the routes: b3 east loads and runs 4 AI turns (Early March 1805). Diplomacy lists United States and British North
  America. Britain declared war on BNA (joined by Austria, Sicily, Naples, Russia, Sweden), then 3 AI turns at war ran
  (Late Feb 1805; 105/119/80 s).
- Open: the "attitudes towards" map stays blank for a generated faction, but Oldenburg's (its template) shows colours.
  The diplomacy minimap still uses the vanilla lookup TGA, so all colours land in the wrong places anyway.

### europe_lookup.tga (2026-10-19, tools/lookup_tga.py)
- 605x300 8-bit colour-mapped TGA (BGR24 palette, rows stored south first, TRUEVISION footer). The pixel is a palette
  colour, not an index: a land region's r,g,b from db regions_tables; all seas share (43,120,139); black = no region
  (filler, plus a 1 px outline on the land side of borders). Vanilla grid fits the land bbox (x0 -393.43, ytop 180.045,
  1.207 u/px). The world build uses proj.THEATRE, the same box as the world europe_map.tga.
- Rebuilt from regions.esf it matches vanilla to 96.9% of pixels (the outline rasteriser is approximate). In game the
  diplomacy attitudes map now colours Europe in the right place (before: scattered over the Americas and Africa).
- New land regions need regions_tables rows (lookup_tga.build(table=...)).

### W1: North America, data-driven (2026-10-19, tools/world_regions.py)
- 29 of 36 North American regions from data/world1805/regions.json built into the zones build (168 regions total);
  7 tiny-island regions are deferred (no room for a settlement), and there are no ports yet.
- w1a (all regions owned by existing factions, land–sea CAI boundaries ON): load crash at 0xD6D9E0 right after "Done
  Created CDIR_INTERFACE", the same address as the zones 'v' crash. The sea side of a boundary lacks per-region data.
- w1a_nol (land–sea boundaries off): loads, minimap/diplomacy lookup colours North America by owner, 3 AI turns
  (Late Feb 1805; 133/107 s for turns 2–3). An OOM on the host (two parallel builds plus the game) killed the first run.
- Cause (lane F): 0xD6B5B0 walks a region's CAI_REGION_BOUNDARYs. For the region at the other end it looks up the
  region's CAI_REGION_MILITARY_STRENGTH in each world manager (0xA73490) without a NULL check. The wld seas have none,
  so a land–sea boundary crashes. The zones 'v' crash is the same thing from the vanilla-sea side.
- w1a_m (7 cloned military strengths per wld sea): the same crash, the same EDX=0x7e (Gulf of Mexico). The clones are
  not where 0xA73490 looks.
- w1a_s (stage h, a vanilla sea's full belief set, on the wld seas): hangs at load about 15% after CDIR_INTERFACE, no
  fault. The same hang as sp_abvgh, so h itself causes the hang.
- Hang root cause (lane F, static): world_zones.region_beliefs (stage h) never set each clone's owner link (header j+9
  = [analyser, BLOCK_OWNS row]), so 380 clones pointed at the template sea's row. Fixed in region_beliefs.
- w1a_s rebuilt with the fix (stage h on the 38 wld seas plus land–sea boundaries): loads and runs 3 AI turns
  (138/85/112 s). Land–sea CAI boundaries work, so the AI can plan from new land onto the world seas.
- So the zones 'v'+'h' combination (sp_abvgh, which also hung) should be retried with the fixed h.
- w1 (all 29 regions, 4 generated factions: united_states, native_plains, native_pacific_nw, haiti): load crash at
  0x6A3110 (getter on NULL) from 0xC39820, which walks CAI_WORLD_SEA_GRID_CELLS and reads each cell's game grid cell
  [+0xFC]. Cause: clone_cai_faction treated a CAI_SEA_GRID_CELL's first field (its sea_grids.esf cell index) as a
  CAI id. The 1122-cell world grid has cells 774..776 = oldenburg's (template) CAI ids, so each faction cloned 3 cells
  with remapped, out-of-range indices. Fixed in cai_faction.Cai.body0; world_regions check now requires cell indices
  0..n-1 once each. Vanilla (66 cells) and b3 could never hit it.
- w1_s (stages "ls") and w1_s_v ("lsv", plus 6 vanilla-sea <-> wld-sea boundaries): both load and run 3 AI turns
  (106/93/105 s and 106/105/119 s, patched exe). Minimap tooltip shows the Great Plains owned by "Plains and Mountain
  Nations". North America W1 is done; 'v' works once h is fixed.
- W2 (South America, `--wave w2`, 23 more regions, 191 total, 6 generated factions incl. amazonian_peoples and
  mapuche; w1 output byte-identical): w2_s_v loads and runs 3 AI turns (105/105/93 s, patched exe). 122 of 252
  lookup palette colours used. No afr_/mea_/asi_ region duplicates a vanilla land region (vanilla Coalition has no
  North Africa/Anatolia/Levant/Caucasus); 4 of them border vanilla land.

### G4a: 24-bit lookup TGA (2026-10-19)
- w2_s_v with europe_lookup.tga rewritten as uncompressed 24-bit truecolour (type 2, same pixels, 122 colours):
  load crash at 0x10DBDDE right after "MVC Manager Open Handler". 0x10DBDD0 is a palette-entry getter: palette
  pointer [this+0x24] (NULL for a truecolour image), entry = index*4. The engine reads the lookup as
  index + palette only, so the 8-bit palette (252 usable colours) is a real limit of the lookup image.
- Still open: what a region without a lookup colour loses. The probes before fd3e22f ran with the vanilla lookup
  (new regions absent from it) and loaded, played, fought wars and showed in diplomacy; only the minimap/diplomacy
  map did not colour them. So regions past 252 are likely possible with no minimap colour/tooltip; and nothing yet
  tests a hard region count elsewhere in the engine (G4b: more than 252 regions).
- Ghidra 12.1.4 headless (tools/ghidra/run.sh, project work/ghidra/ntw): the palette getter 0x10DBDD0 has exactly 3
  callers. (1) 0xA43400 = the campaign regions.esf loader ("data/campaign_maps/%S/regions.esf",
  theatres_and_region_keys / region_keys): hashes all 256 palette colours -> index, then for each region key looks
  up the REGION_RECORD rgb (record+0x1c) and stores its palette index, or -1 when the colour is not in the palette
  (explicit branch). So a region absent from the lookup is a designed case, which matches the probes. (2) 0xA41DE0 =
  the campaign_map_playable_areas / transition_areas loader (same colour -> index map, for theatre/transition
  areas). (3) 0xEE5E00 = generic 8-bit image -> 32-bit colour buffer conversion.

### G4b: region-count stress test (2026-10-19)
- `world_regions.py build --wave w2 --stages lsv --stress-land N`: N land regions, the extras being 20 u dummy squares
  cut from the eur_map_east filler, owned by britain, with the full region recipe.
- Formats (lane F scan): region refs are 16-bit or wider (regions.esf region<<16|area, pathfinding signed 16-bit
  region list, u16 path table); no region-sized u8 anywhere in startpos/sea_grids/poi/trade_routes. The startpos
  REGIONS_ARRAY / REGION_OWNERSHIPS hold settled land regions (land - 4). The real outer limit is the 10-bit pathfinding
  domain id (1023 = none, about 1022 domains; the dummies use about 2.9 each, so N reaches it near 390 land).
- N=270 (270 land, 266 settled, 62 sea, 1 river = 333 regions; 663 pathfinding domains; lookup palette full, 1 region
  without a colour): loads and runs 3 AI turns (106/132/92 s, patched exe), Napoleon.exe peak RSS about 1990 MB.
  No u8 region cap. The minimap shows the dummies (Siberia, British red).
- So the region budget is set by turn time, memory and pathfinding domains, not by 256; the 252-colour lookup
  palette only limits which regions get a minimap colour (minimap_parent for small regions).

### W3 Africa (2026-10-19)
- `--wave w3`: regions.json idx 61-99, 226 regions in total, 70 factions (23 generated from oldenburg's CAI data), the
  Sahara mask with 5 corridors (routes.json, width 0.8 deg). 4 AI turns ok (107/95/67/66 s), peak RSS 2.0 GB.
  70 factions (more than 64) work.
- The first run's turn 3 was "stuck" on a Battle Deployment dialog: a Dutch fleet attacked Britain in the Channel.
  That's normal play, not a mod fault. `ntw.sh turns` now detects the pre-battle panel (both side panels flat grey
  and identical) and clicks auto-resolve (997,1027). The check runs before the date read, because the dialog covers the date.

### W4 Middle East (2026-10-19)
- `--wave w4`: idx 100-126, 253 regions, 73 factions (32 generated), 184 of the 252 palette colours used. Arabian
  and Persian desert masks; the Nile and Forty Days Road corridors. 4 AI turns ok (107/81/94/135 s), peak 2.0 GB.
  So 73 factions (more than 64) work too.
- New land never shares an edge with vanilla land (a 2 u filler strip). Pathfinding doesn't join them, and a
  shared edge merged the CAI pass groups of Africa + Middle East with Europe's, which would be a false belief that
  armies can walk across. Joining them for real is open work (Russia to the Volga, Crimea to the Caucasus).

### W5 Asia and the pathfinding word limit (2026-10-19)
- The first w5 build crashed at load, after "Created CDIR_INTERFACE": a read of 0x657C at VA 0xB108F5.
  - FUN_00b79da0 -> FUN_00b108d0 looks up a pathfinding boundary's polygon. Bit 21 (0x200000) of the 22-bit
    offset means a dynamic polygon (index = id & 0x1fffff, 0x18-byte records, a table that is empty at load).
  - So the static polygon word stream must stay below 2^21 = 2,097,152 words. W4 had 2,079,053; the first W5 build had
    2,235,245, and the faulting word was 2^21 + 1082.
  - The guards (pathfinding_model.STATIC_LIMIT, the pf_gen assert, the world_regions check) now use 2^21, not 2^22.
- The fixed w5 build (coarser new-land and band simplification, an Arctic mask at 66.5-82 N / 43-180 E, lazy
  composite domains) has 2,084,200 words. 283 regions, 92 factions, 780 domains. 4 AI turns ok (134/121/121/96 s),
  peak 2.0 GB.
- This word budget, not region count or memory, now limits further waves. The base sea polygons (about 695K words)
  and off-map polygons (about 747K) are the place to cut.

### Base pathfinding reduction and W6 East Asia (2026-10-20)
- pf_gen: the generated coastline is simplified by 0.25 u (topology-preserving, only original vertices kept), which takes the
  base from 1,673,846 to 1,060,973 words. All 51,747 kept vanilla cells are byte-identical. W5 rebuilt on it has
  1,472,379 words and passes 4 AI turns.
- w6: 323 regions, 697 domains, 1,565,825 words, 249/252 palette colours (5 full_only regions use
  minimap_parent). 4 AI turns ok (133/147/134/120 s), peak 2.2 GB.
- Harness: after auto-resolve the Battle Results panel needs its tick (920,972); ntw.sh resolve() clicks it.

### W7 Oceania: the whole world (2026-10-20)
- w7: 330 regions, 106 factions, 927 of the 1023 domain ids, 1,587,715 words. 4 AI turns ok (134/147/159/80 s),
  peak 2.3 GB. A naval battle auto-resolved and the results panel closed (ntw.sh).
- Budgets now: domain ids (927/1023) are tighter than words (509K spare). Denser Europe and ports have to fit both.
- The minimap shows every generated faction in one dark red. factions.json colours reach db faction_uniform_colours,
  but the map colour comes from somewhere else (under investigation).
- Faction map colour (fixed 4bb4ee4): the minimap reads the db factions table colour columns (primary/alt
  primary/secondary/alt secondary/uniform/alt uniform r,g,b). The startpos FACTION_FLAG_AND_COLOURS 9 u8 values
  (three RGB trios) were also cloned from oldenburg. Fixing only the startpos left the minimap unchanged; fixing the
  db too gave each faction its own colour.

### Port probe: New York (2026-10-20)
- tools/port_probe.py: one port slot (Waterford footprint, nap_eur_port), a campaign_map_towns_and_ports row + loc,
  kind-7 pathfinding on both halves (land on the region's domain, sea on the sea domain; kind 6 is road), trade
  PORTS/PORT_INDICES renumbering, spline-less node routes, a CAI building slot. +67 words, domains unchanged.
- 6 AI turns ok. The game autosaves to AppData/Roaming/The Creative Assembly/Napoleon/save_games/auto_save.save
  (esf.load reads it: 108 MB, about 1.4 GB RSS). After 6 turns united_states had recruited 13 militia and queued a
  Frigate_32 in the New York port, so the AI uses generated ports.

### All ports and the pfgrid overflow (2026-10-20)
- port_probe.add_ports (world_regions stage p): 126/129 ports, +9,486 words, domains unchanged. Toronto, Baku and
  Astrakhan are deferred (the lake and the Caspian have no sea domain).
- The first all-ports run crashed in AI turn 6 at 0xAED830. FUN_00b44740 (pos -> pathfinding cell) and its copy
  inlined in FUN_00b575a0 take dx = pos - origin in 2^20/u fixed point with a signed max(0, dx). With the world
  origin at x = -1910 u, dx overflows int32 for x >= 138 u and clamps to column 0. An AI force rect over Anatolia
  came out (1019,548)-(1,555); FUN_00b0c3a0 -> FUN_00aed7d0 allocated a negative cell count. The bug was there since
  W5 and only turned fatal when the ports changed AI plans. exe_patch group pfgrid: an unsigned clamp at 5 sites.
- With pfgrid: 8 AI turns ok, peak 2.46 GB. The AI queued frigates at all 34 generated shipyard ports, counting
  down normally (2 turns left at turn 6, 1 at turn 8).
- 10 turns ok (peak 2.43 GB). By turn 10 all 34 had launched: 42 factions have a NAVY (8 in the turn-8 save, all
  vanilla), and the second round of queues is 18 Small_Brig and 9 Small_Sloop. (Ship movement after launch not checked yet.)
- The ntw.sh turns loop also answers "Surrender demanded" popups (the tick at 1636,530), which otherwise block the AI turn.

### W8 Russian filler (2026-10-20)
- New regions asi_olonets, asi_vologda and asi_voronezh, owned by Russia, appended to regions.json, so w7 indexes and
  colours are unchanged. Northern Norway, Sweden and Finnish Lapland stay filler (Swedish/Danish in 1805).
- Domains 939/1023 (+12). Words 1,615,468 with ports (+18.3k). The estimate was 5-7k; part of the overshoot is the
  adaptive land simplification below.
- world_regions fixes this wave exposed:
  - carve looks up edges of filler areas that were already carved whole;
  - Douglas-Peucker halves its tolerance when a corner cut would breach the off-map margin (Fiji cut 0.61 u, which
    was latent in w7);
  - areas that shared a removed area's face blob get re-triangulated (eur_map_east 1-9).
- 6 AI turns ok, peak 2.37 GB. ntw.sh turns now also ticks the diplomacy "War Declared" panel (960,716).
- Weld step 2 inputs (lane F, work/scratch/weld8_sides.pkl): 465 cells to edit, 458 sides against cells left
  unedited. 222 of those sides face vanilla cells and their side_intervals must be reproduced exactly; pf_gen.weld
  asserts on any mismatch.

### Weld step 2: new land joined to vanilla (2026-10-20)
- Stage j: 7 of 9 joins welded (Olonets/Finland and Olonets/Novgorod have no vanilla pathfinding land near them).
  630 weld cells and 542 inserted vertices. 16 vanilla polygons gained vertices; 139 got middle20 links to new land.
- Everything outside the weld cells is unchanged, apart from new-land neighbours' middle20 bits and new-region border
  vertices (under 1e-5 u). w8 without j still rebuilds byte-identical.
- Adjacency changes:
  - CAI_REGION field [8] is a coastal flag, not "valid"; it is off on inland Moscow and Belgorod, so welded pairs
    bypass it, and only welded pairs. Applying the bypass to every land pair (review B1) gave 16 bogus
    boundaries to the filler regions.
  - 9 impassable areas with a shared non-walk group spanning separate pieces were split into fresh ids.
  - 7 vanilla-new land trade routes (363 total).
- A Moscow to Kazan army walk over pathfinding links succeeds (74 polygon steps); the same walk fails without j.
- 8 AI turns ok, peak 2.37 GB.
