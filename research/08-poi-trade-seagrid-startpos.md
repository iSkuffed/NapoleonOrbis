# 08 - poi.esf, trade_routes.esf, sea_grids.esf, metadata.dat, startpos coordinate inventory

Status: all formats below were decoded from the vanilla files and every writer in `tools/campaign_misc.py` reproduces the vanilla bytes exactly (5 maps x 4 files, 3 startpos files). Labels: [V] verified by byte-exact parse or numeric check, [I] inferred, [?] unknown.

Coordinate conventions seen in these files:
- `fixed` = i32, world = value / 2^20 (poi.esf, startpos slots/characters/CAI).
- `xy`/`xyz` = ESF tags 0x0c/0x0d, f32 world units (trade polylines, sea grid, LINE_OF_SIGHT bounds).
- y is north-up everywhere (metadata.dat row 0 = north).

## 1. poi.esf (CAI_POI_ROOT)

Root record `CAI_POI_ROOT v0`, no sub-records: a flat stream of scalar Vals. [V] parses to exactly the end of file in all 5 maps.

```
u32  node_count
node* :
  u32  id                  0..count-1, sequential
  i32  kind                1..8 (below)
  bool flag                True for kinds 1-4, False for 5-8
  i32  x, y                fixed point world position
  str  region              region key ('eur_spain'), '' for kind 8, sea key for kind 6, 'all'/'eur_map_west' ... for kind 7
  u32  area                4 = ordinary land region, 6 = sea, 7 = off-map filler, 0 = border; other values (17..428 in Europe)
                           are sub-area ids inside a region (155 distinct groups) [I]
  str  region2 ; u32 area2 identical to region/area in every node of all 5 maps [V]
  f32  dist                distance to the node's own region settlement (kind-4 node); 0 for kinds 4,6,8 [V 93%]
  u32  n1 ; n1 x (str neighbour_region, f32 dist)    kinds 1,2,4,5,7: distance from the node to each adjacent region
                           (<= distance to the nearest POI of that region, so it is distance to the region polygon) [I]
  f32  min_dist            min of the n1 distances, -1.0 when n1 == 0 [V]
  u32  n2 ; n2 x (str region, f32 dist)              kind 3 only (1 or 2 entries): coast/port tie to a neighbouring region [I]
  u32  n3 ; n3 x u32 poi_id                          kind 6 only (1-4): sea node -> coastal land POI ids (kinds 1,2,3,5,8) [V ids exist]
  u32  edge_idx            kind 8 border nodes carry a small sequence number, 0 elsewhere
  bool last                kinds 5: always True; 1,2,3: mixed; 4,6,7,8: False (mostly) - purpose [?]
```

Europe: 5513 nodes. Kinds: 1=416, 2=1230, 3=1017, 4=72, 5=1635, 6=550, 7=554, 8=39. World x range -391..325, y -179..178 (theatre -410..340 x -190..195).

Kind meanings [I, from positions]:
| kind | count (Eur) | meaning |
|---|---|---|
| 4 | 72 | exactly the region's SETTLEMENT position (startpos `SETTLEMENT/SIEGEABLE_GARRISON_RESIDENCE` i32 pair), distance 0.00 for all 72 [V]. One per region. |
| 1,2,5 | 416/1230/1635 | land grid samples inside a region (1 = nearest to something special, 5 = plain), quarter-unit aligned. Nearest-POI of the settlement/town/resource slots are mostly kinds 2/5/3. |
| 3 | 1017 | off-grid (non quarter-unit) coastal/border samples, carry `near` list |
| 6 | 550 | sea-region samples (area 6) with `links` to coastal nodes |
| 7 | 554 | samples in off-map filler regions (`eur_map_west`, `eur_map_east`, `all`) outside the playable area |
| 8 | 39 | map-border ring points, region '' (Europe 39, Egypt 27, Italy 7, Spain 28, Tut 39) |

Generation: not stored with edges; it is a point cloud tagged by region polygon membership plus distance-to-region-border values. Derivable from regions.esf polygons + settlement positions + a sampling rule (grid ~5 units for land, coastal refinement, sea samples). Exact vanilla sampling pattern not reverse-engineered; a regular grid with correct region tags/dists is the practical regeneration target [I]. Coordinate fields: `x`,`y` only (all node kinds); `dist`/`neighbor dist`/`min_dist`/`near dist` are lengths (scale with the map scale, -1.0 sentinel). Region key strings and ids (`links`) are map-dependent keys, not coordinates.

Reader/writer: `read_poi`/`write_poi` (`PoiNode` dataclass). Transform: `_transform_poi` (x,y via fn; lengths via `scale`).

## 2. trade_routes.esf

Root `root v0` with five record arrays (all v0). [V] byte-exact.

```
SPLINES x N     item: xy[] polyline (f32 world xy points), bool flag      Europe N=766 (444 True / 322 False)
PORTS x P       item: str 'port:eur_england:chatham'                       Europe 39, Egypt 11, Italy 0, Spain 13, Tut 4
SETTLEMENTS x S item: str region key                                       Europe 72, Egypt 30, Italy 25, Spain 31, Tut 8
ROUTES x R      item: u32 node_a, u32 node_b, u32[] spline_refs, f32 length   Europe 912
TRADE_NODE_ROUTES x (1+T)
   item 0: xy[T]                                   trade node positions (Europe 19)
   item 1..T: str 'trade_node_N', ROUTES x P       per node: (u32 port_index+1 (1..P), u32[] spline_refs, f32 length)
```
- Node index space for ROUTES a/b is ports then settlements: 0..P-1 ports, P..P+S-1 settlements (Europe 0..110). Routes: 732 port-port, 39 port-settlement, 141 settlement-settlement [V].
- `spline_ref = 2*spline_index + reversed_flag` (max ref 1531 = 2*766-1 in Europe) [V].
- `length` = sum of the referenced polyline lengths, max relative error 0.3% (Europe), 1e-7 (Italy), 1e-4 (Spain). Egypt/Tut contain vanilla inconsistencies (error up to 85%/74%) so treat length as derived-but-not-enforced [V].
- Empty `spline_refs` (38 in Europe) = sea lane / adjacency with only a length.
- The 766 polylines are copied verbatim into startpos `CAMPAIGN_TRADE_MANAGER/TRADE_SEGMENTS` (xy leaves) [V counts: 766 segments, 26220 xy points]. The 19 trade-node xy (item 0) are startpos `TRADE_NODES` xy + `CAI_TRADING_POST` (i32 fixed copies) but the node ORDER and port/settlement INDEX numbering differ between the two files (startpos PORT_INDICES start at 1, SETTLEMENT_INDICES e.g. courland=39) [V]; they must be regenerated together, not transformed independently.
- Europe trade nodes lie on the theatre edge (x -390..-345, y -176..177, plus 302,-82 / 283,-101 ...): they are off-map exits (India/Americas). In a world map they become real in-map ocean nodes.

Coordinate fields: all polyline points, `node_pos`. Lengths: ROUTES.length, TRADE_NODE_ROUTES.length. Reader/writer: `read_trade_routes`/`write_trade_routes`.
Derivation: polylines are road/sea routes between settlement/port locations (pathfound); regenerate with A* over the new pathfinding mask, then lengths = polyline sums.

## 3. sea_grids.esf (CAI_SEA_GRID_ROOT)

[V] byte-exact, flat Val stream:
```
u32  version (=1)
str  grid_id  '1244818741' (decimal, appears in startpos DOMESTIC_TRADE_ROUTE strings) - purpose [?]; equals nothing derivable
xy   bmin, bmax         theatre box, Europe (-410,-190)..(340,195)
f32  cell               75.0
u32  cols, rows         cols = floor(w/cell)+1, rows = floor(h/cell)+1   (11x6 Europe; verified 5 maps) [V]
cell geometry x (cols*rows):  u32 cx, u32 cy, xy min, xy max          row-major, cell k = cy*cols + cx; grid overhangs bmax
cell info x (cols*rows):      u32 k,
                              u32 n, n x str land-region keys (regions overlapping the cell, incl. 'all'/'eur_map_*'),
                              u32 n, n x str sea-region keys,
                              u32 n, n x str 'port:...' keys located in the cell,
                              u32 n, n x u32 poi node ids (cell reach list; not cell-local: ids spread across the map - exact rule [?])
u32  edge_count
edge x : u32 cell_a, u32 cell_b, f32 cost
```
- Edges = every unordered pair of cells that list at least one sea region (Europe 39 cells -> 741 edges; Spain 28 -> 378; Egypt 27 -> 351; Italy 7 -> 21) [V]. Cost = sea path distance between the cells (Europe 703 of 741 non-zero); 0.0 = no path/not reachable; Egypt uses -1.0 (182) and 0.0 (169) [I].
- Region lists = regions whose polygon intersects the cell (superset of the POI-node-derived sets; node-derived sets match 32/66 land, 39/66 sea cells exactly in Europe) [V]. So they must come from regions.esf polygons.
- Other maps: Egypt (-220,-260)..(220,260) 6x7; Italy (-185,-120)..(175,105) 5x4; Spain (-213,-179)..(219,206) 6x6; Tut == Europe grid.

Coordinate fields: bmin, bmax, every cell min/max (axis-aligned only), cell size (length), edge costs (lengths, positive ones). Regenerate: `make_sea_grid_cells(bmin,bmax,cell)` (verified == vanilla for all 5 maps); lists from regions polygons; costs from sea-lane pathfinding between cell centres.
Reader/writer: `read_sea_grids`/`write_sea_grids`.

## 4. metadata.dat

```
bytes 0..3   'MTGI'  (u32 0x4947544d)
u32 width, u32 height   Europe 2048x1024, Egypt 4096x4096, Italy/Spain 2048x2048
u8 data[height*width]   row-major, row 0 = NORTH (top)            [V by fit below]
```
[V] writer byte-exact for all 4 existing files (Tut has no metadata.dat). Europe values: 0 (1,631,741 px) and 6 (465,406 px) plus 5 stray px of value 1 at (812..813,194) and (964..966,430). 6 = sea. Egypt uses {0,6,1,10,2,4,3}, Italy {0,4,1,6,3,2,8}, Spain {0,6,4,1,2}: the other codes are unidentified [?] (not needed for Europe-like generation: use 0/6).

### Europe extent / origin / orientation (answer to the coordinator's question)
metadata.dat does NOT use the +-640 x +-320 box. Fitting the POI point cloud (550 sea nodes must land on code 6, 4370 land nodes must not) with a random-search affine gives 99.7% agreement:

    col = wx * S + OX        row_from_top = OY - wy * S
    S  = 2.2826 (x) / 2.2895 (y)  ->  use S = 16/7 = 2.2857 px/unit (2048/896, 1024/448)
    OX = 1043 +- 1 px,  OY = 526 +- 1 px     (fixed S=16/7 grid search: best 1043.5/526.0, plateau +-1 px)

i.e. the 2048x1024 raster covers world x [-456.3, +439.7], y [-217.9, +230.1] (896 x 448 units, aspect 2:1, square pixels, origin top-left = (-456.3, +230.1), y flipped). Independent check against the verified heightmap mapping (px=(wx+640)*3.2, row=(320-wy)*3.2): with this affine only 0.0004% of heightmap>20 pixels (247,561 px) fall on sea code 6; with the naive +-640 x +-320 / 1.6 px/unit mapping 17% do [V]. The sea mask itself spans px x 146..1746, y 114..938, which maps to world x -392.8..308.1, y -180.2..179.7 (the sea regions; it is not the theatre box, the east side is land). Sub-pixel accuracy is limited by the POI sampling (+-0.5 px ~ +-0.25 units); the nominal extents above are a fit, not a stored field. There is no extent field in the file; the engine must hard-code or look it up elsewhere (not found; heightmap/regions are the source of truth) [?]. Egypt's affine could not be fitted with the same method (agreement 0.79: its codes are not just sea/land); Italy has no sea POI nodes. Not fitted: Egypt/Italy/Spain.

Generation: derivable. Rasterise sea regions (regions.esf polygons or the new world land mask) into the chosen extent; value 6 = sea else 0. `meta_px()` applies the Europe affine; `resample_metadata()` does nearest-neighbour remap. For a new map pick any 2:1 extent and keep the file self-consistent with the heightmap; the engine consumer's expected extent is the unknown risk (see Risks).

## 5. startpos.esf coordinate / map-dependent inventory

Files: `mp_eur_napoleon` (32.3 MB, 878 distinct record paths) and `eur_napoleon`; `tut/egy` use the same schema (the same rules applied in the self-check on tut and egy with all tag assertions passing). Paths below are relative to `CAMPAIGN_STARTPOS/CAMPAIGN_ENV/CAMPAIGN_MODEL` (CM). "Leaf i" = index among the record's children (Recs and Vals both counted). Counts are for mp_eur_napoleon. `T` = handled by `transform_coords`.

### 5.1 Plain world coordinates (all T)
| Path (CM/...) | leaves | encoding | n | example | note |
|---|---|---|---|---|---|
| WORLD/REGION_MANAGER/REGIONS_ARRAY/REGION/SETTLEMENT/SIEGEABLE_GARRISON_RESIDENCE | 10,11 | i32 fixed x,y | 72 | (-248.47,-56.52) | settlement position; == POI kind-4 node |
| .../REGION/REGION_SLOT_MANAGER/REGION_SLOT_ARRAY/REGION_SLOT | 6,7 | i32 fixed | 337 | (-333.15,43.1) | resource/town/port slots; leaf 3 is the key 'port:eur_ireland:waterford' |
| .../REGION_SLOT_MANAGER/ROAD_SLOT/REGION_SLOT | 6,7 | i32 fixed | 72 | | road slot ('settlement:...') |
| .../REGION_SLOT_MANAGER/FORTIFICATION_SLOT/REGION_SLOT | 6,7 | i32 fixed | 72 | | |
| WORLD/FACTION_ARRAY/FACTION/CHARACTER_ARRAY/CHARACTER/LOCOMOTABLE | 0,1 and 2,3 | i32 fixed pos + destination | 539 | (-146.08,-12.2) | (0,0) = inside a force / off map, skipped. Leaves 8,9 are i32 26/30-type small ints (23..31), not coordinates (region/area-like index [?]) |
| CAI_INTERFACE/CAI_WORLD/CAI_WORLD_REGION_SLOTS/CAI_SITUATED | 0,1 | i32 fixed | 195 | | |
| .../CAI_WORLD_REGION_SLOTS/CAI_REGION_SLOT/CAI_SITUATED | 0,1 | i32 fixed | 39 | | |
| .../CAI_WORLD_RESOURCE_MOBILES/CAI_SITUATED | 0,1 | i32 fixed | 241 | | armies/fleets as AI objects |
| .../CAI_WORLD_SETTLEMENTS/CAI_SITUATED | 0,1 | i32 fixed | 72 | | |
| .../CAI_WORLD_TRADING_POSTS/CAI_TRADING_POST | 1,2 | i32 fixed | 19 | (301.98,-82.35) | == trade node xy |
| .../CAI_WORLD_REGION_HLCIS/CAI_REGION_HLCI | 3,4 | i32 fixed | 520 | | 2 outliers (x=-527.6, 490.9, y=1.3) look like sentinels/garbage but are mapped too [?] |
| .../CAI_WORLD_REGIONS/CAI_REGION | 4,5 | f32 pair | 101 (96 mapped) | (-361.59,0.82) | region centroid; (0,0) for off-map regions skipped |
| CAI_INTERFACE/CAI_INTERFACE_MANAGERS/.../CAI_BDI_POOL_INTENTIONS/CAI_BDIM_MOVE_TO_POSITION | 1,2 | i32 fixed | 35 | | |
| .../CAI_BDIM_WAIT_HERE | 0,1 | i32 fixed | 200 | | |
| .../CAI_HIGH_LEVEL_PATH/CAI_HIGH_LEVEL_PATH_PATH_INFO/CAI_HLPP_INFO | 1,2 | i32 fixed | 24 + 9 | | both under CAI_BDI_POOL_BELIEFS variants |
| .../CAI_BORDER_PATROL_ANALYSIS/.../CAI_BORDER_PATROL_ANALYSIS_AREA_SPECIFIC | 3,4 | i32 fixed | 97 | | |
| .../CAI_BORDER_PATROL_ANALYSIS_AREA_SPECIFIC_PATROL_POINTS/CAI_BORDER_PATROL_POINT | 0,1 | i32 fixed | 17702 | (-313.63,180.09) | patrol points along borders; these ARE a region-border derived list (regenerate for new borders) |
| .../CAI_BASIC_REGION_GROUP_ANALYSIS | 7 | xy | 36 | (-187.6,0.0) | |
| CAMPAIGN_TRADE_MANAGER/TRADE_SEGMENTS | direct xy leaves | xy x26220 | 766 | | = trade_routes.esf SPLINES; also u32 count leaf |
| CAMPAIGN_TRADE_MANAGER/TRADE_NODES | leaf 0 | xy | 19 | | node order != trade_routes.esf order |
| CAMPAIGN_TRADE_MANAGER/DOMESTIC_TRADE_ROUTES/.../DOMESTIC_TRADE_ROUTE | 3 xy leaves | xy | 10 | (282.95,-100.98) | plus str '1244818741' = sea grid id |
| CAMPAIGN_TRADE_MANAGER/INTERNATIONAL_TRADE_ROUTES/.../INTERNATIONAL_TRADE_ROUTE | many xy | xy | 36 | (0,0) mostly | zero placeholders skipped |
| CAMPAIGN_TRADE_MANAGER/TRADE_ROUTES | 3 | f32 length | 1653 | 8.74 | scaled with `scale`; 1653 != 912 entries of trade_routes.esf (both directions/more), numbering differs |
| WORLD/FACTION_ARRAY/FACTION/CHARACTER_ARRAY/CHARACTER/LINE_OF_SIGHT, REGION/LINE_OF_SIGHT, SETTLEMENT/.../LINE_OF_SIGHT, TRADE_SEGMENTS/LINE_OF_SIGHT | leaf 1,2 | xy bbox (snapped to 1.25 units = 1280/1024 grid) | 539/72/66/766 | (-161.25,-27.5)..(-130,3.75) | followed by QUAD_TREE_BIT_ARRAY (below); bounds are mapped, bits are not |
| EPISODIC_RESTRICTIONS | 9..12 | f32 x0,y0,x1,y1 | 1 | (-640,-320,640,320) | world rect, mapped as corners |
| PENDING_BATTLE | 26 | xy | 1 | (0,0) | zero, skipped |
| CAMPAIGN_ENV/CAMPAIGN_CAMERA_MANAGER/CAMPAIGN_CAMERA | 2 | xyz | 1 | (-54.0, 0.0, 151.12) | NOT mapped. x,y is the same (-54,0) in all 6 campaigns, z varies per map (Eur 151, Egy 216, Ita 61, Spa 162, Tut 151): z = zoom/height, x,y a default; the engine recentres on the player [I]. Set z for the new map. |

### 5.2 Coordinate-derived but grid-bound / opaque (not remapped except where stated)
| Path | encoding | size | notes |
|---|---|---|---|
| CAMPAIGN_PATHFINDER/PATHFINDING_GRID leaf 1 | u32[131066] = stream of obstacle polygons `[u32 n][n x (i32 x,i32 y) fixed][u32 kind 1..6]`, 7282 polygons / 58251 vertices, world range (-394,-180)..(312,182) | 524 KB | [V] parses exactly; leaf 0 = u32 7282 is the polygon count. Remapped only with `pathfinder=True`. |
| PATHFINDING_GRID leaf 5 | u32[25902] = 12951 x (u32 packed u16 cell x | cell y<<16, u32 node index); cells x 6..363, y 3..187 | 104 KB | grid cells relative to the theatre origin (-410,-190), 2.0 units/cell, 375 x 193 (same as pathfinding.esf grid_data). Regenerate, cannot be remapped by fn. |
| PATHFINDING_GRID/OBSTACLE_BASE_GRID_NODE x12951, OBSTACLE_BOUNDARY_MANAGER x324, OBSTACLE_BOUNDARIES u32[158422] | u32 indices/boundary refs | ~1.5 MB | opaque pathfinder acceleration structure, indices into the above. Regenerate with the pathfinder data. |
| PATHFINDING_GRID/OBSTACLE_LISTS/CHARACTER_OBSTACLE/OBSTACLE x103 | 4 x i32 fixed AABB (e.g. -78,-156,-52,-136) + u16 cell coords + `BOUNDARIES` u32[] | | AABB x0,y0,x1,y1 + cell indices; character blocking obstacles at start. Not mapped; armies at start positions - regenerate or empty the list (103 entries). |
| PATHFINDING_GRID leaf 8 b[222] / leaf 11 f32[222] (0.667) | barrier flags/weights | | 222 entries, meaning [?] |
| LINE_OF_SIGHT/QUAD_TREE_BIT_ARRAY (u32 1024, 512, 1024 + nested QUAD_TREE_BIT_ARRAY_NODE bitmask) | quadtree over a 1024x512 cell world grid (1.25 units per cell over 1280x640) | thousands of nodes | per character/region/settlement/trade-segment visibility footprints; fixed to the old world box. Valid under a translation that is a multiple of 1.25 only if the box origin matches; otherwise regenerate or `los='strip'` (sets LINE_OF_SIGHT to `b=False`, the form already used by 337 slot residences; not tested in game [?]) |
| WORLD/FACTION_ARRAY/FACTION/CAMPAIGN_SHROUD (5 factions x 3 QUAD_TREE_BIT_ARRAY) | same 1024x512x1024 quadtree | | fog/shroud revealed area; regenerate (empty = fully hidden) |
| SAVE_GAME_HEADER/MAPS: 'europe_main', u32 605, u32 300, i32 2420, u32[181500] | 605x300 RGBA (little-endian u32 pixels, e.g. 0xffdcd9ca) strategic map image, 2420 = row bytes | 726 KB | the "stratradar" lookup/ campaign minimap image; derived from the map (see work/preview/stratradar_europe.png); regenerate |
| CAI_BDI_POOL_BELIEFS u32[23694]/CAI_ANALYSER/CAI_WORLD_RESOURCE_MOBILES u32[241]/CAI_MILITARY_REGION_GROUP_REGION_ANALYSIS i32[15081] | CAI object-id references and affect values | ~3 MB | opaque AI state keyed by CAI object ids/region group indices; no coordinates found; must be self-consistent with region/slot counts. Regeneration plan: re-create CAI tables from the new region set or copy the vanilla block structurally and rewrite keys [?]. |
| CAI_TAS_ANALYSIS (leaves 163,187,191 with +-120 range) | i32 fixed-looking | 433 / 78 | probably distances/offsets, not world positions [?]; not mapped |
| CAI_BDI_COMPONENT_PROPERTY_SET leaf 11 under INTENTIONS (25) | i32 fixed-looking single value (+-143) | | single scalar, not a pair [?]; not mapped |

### 5.3 Map-dependent keys / ids (strings and indices that bind startpos to the map data)
- Map paths: `CAMPAIGN_MODEL/CAMPAIGN_MAP_DATA` holds 'campaign_maps/nap_europe', 'campaign_maps/nap_europe/display', 'nap_europe' (one each); `CAMPAIGN_PREOPEN_MAP_INFO` holds 'nap_europe'; 'europe_main' (theatre key) appears in `SAVE_GAME_HEADER/MAPS` and `CAMPAIGN_PREOPEN_MAP_INFO/REGION_OWNERSHIPS_BY_THEATRE`; every `REGION` carries the string 'europe' (72). The campaign key 'eur_napoleon' is not in the file. NOTE: on 2026-10-18 14:06 someone else's deploy rewrote the installed `campaigns/mp_eur_napoleon/startpos.esf` to 'nap_world'; `eur_napoleon` still has the vanilla 'nap_europe' values. Helper: `replace_strings`.
- Region keys: 72 `REGION` records keyed 'eur_*' (+ `REGION_OWNERSHIPS_BY_THEATRE`, `CAI_REGION` 101 incl. sea regions, `FACTION_*` ownership blocks, `CAMPAIGN_VICTORY_CONDITIONS/REGION_KEYS`, `CAI_BDI_*` region targets) - must equal the regions.esf keys of the new map.
- Slot keys: 'settlement:eur_aquitaine:bordeaux' style in REGION_SLOT (leaf 3 str and the matching u32 slot id), 'port:eur_england:chatham' (39 ports), resource slots 'wine/wheat/timber/iron/gold/pasture/town'; these correspond 1:1 to regions.esf settlement slots and poi/trade_routes keys.
- Trade manager indices: PORT_INDICES (39, indices 1..39), SETTLEMENT_INDICES (72, e.g. courland=39), THEATRES (0), TRADE_NODES (19) - ordering differs from trade_routes.esf; regenerate both from one source.
- CHARACTER locomotable small ints (26/30...) and `CAI_*` sea-grid analysis (`CAI_FACTION_SEA_GRID_ANALYSIS`, 208 cell values/23 factions, `CAI_SEA_GRID_CELL_VALUE_TOTALS`) are indexed by sea_grids cell k = cy*cols+cx (66 cells Europe) - must be resized when sea_grids changes.
- Counts that must match poi/sea grid/trade files: 41 factions (40+rebels), 72 regions, 39 ports, 19 trade nodes, 766 trade segments, 66 sea cells.

## 6. Tool API (`tools/campaign_misc.py`)
- `read_poi/write_poi`, `read_trade_routes/write_trade_routes`, `read_sea_grids/write_sea_grids`, `read_metadata/write_metadata`, `make_sea_grid_cells`, `sea_grid_dims`, `meta_px`, `resample_metadata`.
- `transform_coords(esf_obj, fn, scale=1.0, pathfinder=False, los='keep')`: in-place; dispatches on root name (CAI_POI_ROOT, root (trade), CAI_SEA_GRID_ROOT, CAMPAIGN_STARTPOS). `fn(x,y)->(x,y)` in world units; `scale` multiplies length fields. Helpers `translate(dx,dy)`, `scale_about(sx,sy,cx,cy)`, `collect_coords(obj)` (identity transform that records pairs), `replace_strings(esf_obj, {old:new})`.
- Self-check: `.venv/bin/python tools/campaign_misc.py [--quick]` (about 30 s; `--quick` skips startpos).

## 7. Risks / unknowns
1. metadata.dat extent is a fit (+-1 px, S ~ 2.2857 +- 0.005), not a stored field. How the engine maps its raster to world (and whether the same hard-coded box is used for a different map) is unknown; only Europe was fitted. A world map likely needs a test that edits a known sea/land area and checks in game.
2. poi: kind semantics and the `last` flag, `area` ids and the sea-grid per-cell POI id lists are inferred or unresolved; POI generation rule is not reverse-engineered beyond kind 4 = settlement.
3. sea_grids edge costs semantic (0.0 vs -1.0 = unreachable) inferred; Egypt differs.
4. startpos: CAI tables (~3 MB) and the pathfinder acceleration structure are opaque; coordinates inside them were only identified where a column is a fixed-point pair of consecutive leaves. Pairs equal (0,0) are skipped as sentinels. HLCI outliers and CAI_TAS_ANALYSIS columns are unclassified. The in-game acceptance of `los='strip'`, an empty shroud and rewritten pathfinder polygons with stale grid cells has not been tested.
5. Remapping with non-affine functions (projection) distorts lengths: `scale` is a single factor; recompute lengths in the generator. Non-axis-aligned maps break sea_grid cells and the pathfinder grid.
6. Translate-inverse is byte-exact only for fixed-point fields (poi, startpos i32); f32 fields round to float32, drifting <= 1.5e-5 units after translate+inverse in the self-check (tolerance 2e-3).
