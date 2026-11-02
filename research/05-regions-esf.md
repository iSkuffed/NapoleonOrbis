# 05 - regions.esf (campaign map region geometry)

Scope: what every field in `data/campaign_maps/<map>/regions.esf` means, which fields can be derived and which are authored, and what a from-scratch generator has to supply. Ground truth: the 5 vanilla maps (nap_europe, nap_egypt, nap_italy, nap_spain, nap_tut), parsed read-only with `tools/esf.py`. Code: `tools/regions_model.py` (extract / rebuild / resize, plus a self-check).

Tags: **[V]** checked by code on all 5 maps (most of these are asserts in `regions_model.py`). **[V-eu]** checked on Europe (and tut) only. **[I]** inferred from data patterns, not proven. **[?]** unknown.

## 0. Conventions

- World units, x east, y north. Europe/tut world box (-640,-320)..(640,320). Egypt/Italy/Spain (-320,-320)..(320,320). [V]
- **Area code** = `region_index << 16 | area_index`, with indices into `region_data/regions` and that region's `areas`. It is used in connectivity, in quadtree cells and in quadtree edges. `0xFFFFFFFF` means none (an edge on the world border). [V]
- Vertex pool: `region_data/vertices` xy[], float32, shared by every area. All geometry is indices into it. No vertex is unused. [V]
- Rings: an outline's u32[] is a closed ring of pool indices with no repeated last vertex. The outer ring is CCW (positive area) and holes are CW. [V]
- Faces: u32[] read as triangles (3 indices each), all **clockwise**. [V]
- The areas tile the world box exactly: no gaps, no overlaps, every directed edge owned by exactly one area. The sum of the area polygon areas equals the world area on all maps. [V]

## 1. Top level

| record | content |
|---|---|
| `theatres_and_region_keys` x1 | theatre: utf16 key (numeric string, e.g. '1244818741'), xy min, xy max, bool (always False) [V]; `region_keys` x N: (utf16 region name, xy settlement position). N = the playable regions: Europe 72, Egypt 30, Italy 25, Spain 31, tut 8. The xy equals `settlement_and_slots` pos exactly. [V] |
| `theatres` x1 | the same 4 theatre header fields, then `climate_map` (land), `climate_map` (sea), `wind_map`, `transition_areas` (always x0). [V] |
| `black_shroud_outlines` | x0 except tut x9: (utf16 'shroud_map_1_3', xy[] polygon). These are the tutorial's fog polygons. [V] |
| `region_data` | vertices, xy world min, xy world max, `regions`. See section 2. |
| `mountain_data/MOUNTAIN_OUTLINES` | `OUTLINE_BLOCK` x M (xy[] polygon, CCW, not closed) plus a parallel `BOUNDS_BLOCK` x M (xy min, xy max). M: eu 13, egy 31, ita 48, spa 23, tut 16. The bounds can be derived. [V] |
| `climate_indices` | `land_indices` x23 and `sea_indices` x10: (utf16 climate key, u8 value). These are the value tables for the two climate maps. The set is the same on every map and still includes the Empire `lc_am_*` keys. [V] |
| `query_info` | point-to-area quadtree over region_data. See section 3. |
| `groundtypes` | its own `region_data` (no faces) plus its own `query_info` plus `groundtype_indices_list/groundtype_index` x K (utf16 names, same order as its regions). See section 4. |
| `map_heights/MAP_HEIGHT_AREA` | x0 on all 5 maps. Item layout [?]. |
| `trade_nodes` (v1) / `trade_nodes` x T | (utf16 key like 'eur_black_sea_02', xy). eu 19, spa 5, others 0. [V] They are sea trade node positions; they probably cross-reference `trade_routes.esf` [I]. |
| `bridges` | xyz[B] = (x, y, rotation in radians). eu/tut 149, egy 12, ita 13, spa 19. The third component holds values like 0.1745 (10 degrees), so it is an angle, not a height [V-values]. One Egypt bridge has y = 363.6, outside the world, so it is junk. |

## 2. region_data

`vertices`, `xy min`, `xy max` (= min/max of the vertex pool, derivable [V]), then `regions` x R (eu 101, egy 36, ita 32, spa 37, tut 101).

### 2.1 Region item

| # | type | meaning |
|---|---|---|
| 0 | utf16 | region key. Keys with settlements match the DB/startpos keys. Filler/sea/river keys: 'eur_map_west', 'eur_map_east', 'all', 'west', 'ita_outere'... |
| 1 | ascii | kind: `land`, `sea` or `river`. Every map has exactly one `river` region (Europe 'all', 211 areas) that holds every river polygon. [V] |
| 2,3 | xy | bounds = min/max over all of its outline vertices (derivable [V]) |
| 4 | `areas` | see 2.2 |
| 5 | i32 | 0 if the region has a settlement (and is in `region_keys`), else -1. Read as the theatre index. [V] |
| 6 | `settlement_and_slots` | present only when i32 = 0. See 2.4. |

### 2.2 Area item

| # | type | meaning | derivable? |
|---|---|---|---|
| 0 | bool `crossing` | Sea area that armies can cross on foot, i.e. a strait. Europe: Ionian#1 (Mallorca-Menorca), Ionian#2 (Messina), Irish#1 (North Channel, Ireland-Scotland), Kattegat#2 (Great Belt), Kattegat#3 (Oresund), Gulf of Finland#4. Never set on other maps. [V] | authored |
| 1 | bool | always False on all 5 maps [V] | [?] |
| 2 | bool `passable` | True for every sea area and for walkable land. False for filler/outside-theatre land, impassable land (mountains, lakes as land) and every river area. [V] | authored (with heightmap/pathfinding) |
| 3,4 | xy | bounds of all of its ring vertices | yes, byte-exact [V] |
| 5 | u16 `pass_group` | Passable areas: the id of their connected component. Passable land joins land across shared edges and across crossing seas; sea joins sea. Ids run 0..k-1, numbering order [?]. Impassable areas: unique ids k, k+1, ... in file order. [V partition and sequence] Europe: 0 Balearics, 1 Sardinia, 2 Moscow exclave, 3 Britain+Ireland, 4 mainland (+Sicily, Zealand...), 5 Corsica, 6 all sea. Egypt: each lake is its own group. | partition yes; passable numbering no |
| 6 | `faces` | u32[] CW triangles. **The whole blob is shared**: every area of a "face group" stores an identical copy of the triangulation of the union of that group. The group is always inside one same-region edge-connected component [V], but a component sometimes holds several blobs (for example eur_map_west areas {0,1} vs {9}, eur_spain {0-5} vs {6}). So the grouping comes from authored source polygons [I]. Many blobs (eu 180/406, egy 38/55, ita 44/58, spa 42/68) use **interior Steiner vertices** that lie on no outline: a jittered lattice of about 7-8.5 units (eu 7.0, egy 8.5, ita 7.0, spa 8.0), 6932 of the 33073 Europe vertices. [V] | coverage yes; exact triangles/Steiner points no |
| 7 | `outlines` x n | rings, see 2.3 | authored geometry |
| 8 | u16 `nonwalk_group` | For everything that is not passable land (impassable land, river, sea): the id of its connected component across shared edges. Passable land = 0xFFFF. The open sea shares the id of the outer filler (eu 193 = max). Egypt lakes get their own ids. [V partition] | partition yes; numbering no |
| 9 | u16 `landmass` | Land+river areas: the id of their connected component (the physical island) across shared edges. Sea = 0xFFFF. Europe mainland is 34 and Great Britain 27. Egypt, Italy and Spain have essentially one value. [V partition] | partition yes; numbering no |

The ids look like links into pathfinding (passable components, obstacles). That fits but has not been cross-checked with `pathfinding.esf` [I].

### 2.3 Outline item

| # | type | meaning |
|---|---|---|
| 0 | bool | True = outer ring (exactly one per area) [V] |
| 1,2 | xy | ring bounds (derivable, byte-exact [V]) |
| 3 | u32[] | the ring: pool indices |
| 4 | `connectivity` x m | (u32 neighbour area code, u32 first edge, u32 last edge). Edge k = ring[k] to ring[k+1]. These are maximal runs of consecutive edges whose twin edge (reversed) belongs to the same area. They start at edge 0 and are **not** merged across the wrap. 0xFFFFFFFF = no twin (world border). **Derivable, byte-exact** [V]. Region adjacency = union of the codes; eu has 380 region pairs. |

### 2.4 settlement_and_slots

`xy` settlement position (= region_keys xy), `xy[12|14|16]` settlement footprint polygon (size grows with settlement level [I]), `slot_descriptions` (v1) x S, then `roads`, `railways`, `canals`, each `links` x0 on all maps.

Slot item: utf16 slot key (`settlement:eur_spain:madrid:settlement_4_slot:1`, `port:eur_spain:la_coruna`, `town:...`, `gold:...`), utf16 slot type (`settlement_fortification`, `settlement_4_slot`, `settlement_road`, `port`, `town-industrial`, `horses`, `wine`...), xyz (x, height, y) building position, xy 2D position (equal to xyz for land slots, the dock/sea point for ports), angle u16 (65536 = 2 pi), bool (True = part of the settlement itself), utf16 model key (`nap_eur_port`, `nap_eur_town_ind`, '' for resources), xy[] land footprint, xy[] sea footprint (ports only, else empty), xy[] combined outline. [V-eu, layout V on all maps by dump]

## 3. query_info (point -> area quadtree) - fully derivable except edge order

- Header `u32 a, u32 b` = (total node count, leaf count). b = (3a+1)/4. Europe 1937/1453, egy 229/172, ita 341/256, spa 605/454, tut 1817/1363. [V]
- `node`: xy min, xy max, then either 4 children `bottom_left, top_left, bottom_right, top_right` (exact halves, same layout) or one `cell`. The root is the world box (not square in Europe; cells are 2:1). [V]
- **Split rule**: a node splits while it holds **more than 50 edges**. An edge belongs to a node if the segment meets the box **interior**; touching only the box border does not count (shapely `intersects and not touches`). There is no min/max depth (observed leaf depths 1..8). [V, exact on all 10 trees]
- Edges = every undirected outline edge (each shared edge once). The 6 world-border edges never meet an interior.
- `cell`:
  - `xy` sample point S. It is the cell's min corner unless the corner lies within d (d^2 < 1e-5, so d < 0.00316) of the *line* through any of the cell's edges. In that case S = (min.x, mid.y), the midpoint of the left side. The threshold fits all 36 shifted and all unshifted leaves (0.00311 < d < 0.00338 is the observed gap). [V]
  - `u32` = area code containing S. [V]
  - `u32[]` = 4-tuples `(v0, v1, right_area, left_area)`. Each is oriented so that **S lies to the left of the line v0->v1**. right_area owns v1->v0, left_area owns v0->v1. [V, all edges]
- Lookup semantics (our reading; implemented as `query_point`, which agrees with polygon containment on random points for vanilla and rebuilt trees): go down to the leaf. If S->p crosses no edge, the answer is the cell code. Otherwise it is the **right_area** of the crossed edge nearest p (S starts left of every line, so p is always on the right side of the last edge crossed). left_area is therefore redundant for point queries, and the groundtypes tree leaves it out (section 4).
- **Rebuild result** (`build_query_info`): identical header, tree shape, bounds, sample points, cell codes and per-cell edge sets on all 5 maps x 2 trees. The serialized size is the same. **Not byte-exact**: the order of the 4-tuples inside a cell differs. Vanilla's order is chain-like (it walks consecutive boundary edges) but is not a global order (precedence cycles even between sibling leaves), not outline order, not triangle order and not any tested distance/angle sort. About half of the leaves match by chance (the empty/short ones). For a point query the order does not matter.

## 4. groundtypes

Same `region_data` schema with K regions = ground types (eu: grassland, light_forest, hills, hilly_light_forest, dense_forest, hilly_light_forest_cold_att, light_forest_cold_att, grassland_cold_att). All kinds are 'land', the region i32 is -1 and there are no `faces`. Every area has bools False/False/False and all three u16 ids = 0xFFFF. The areas tile the world box. The first region (eu 'grassland') is one world-sized area with dozens of holes. Its own vertex pool (eu 16945). Its `query_info` follows the same rules except that **every tuple's 4th field is 0xFFFFFFFF** (only the right area is stored). Bounds, connectivity and quadtree rebuild the same way. [V]

## 5. Rasters in the theatre

- `climate_map` #1 = **land climate**, #2 = **sea climate**, u32 w, u32 h, u8[w*h]. Every pixel has a value in both maps. Values are the `climate_indices` u8. Land values 0..21 plus 32 (lc_am_us_central); filler value 15 (lc_am_desert) in Europe and Egypt. Sea values 22..31. Row 0 = south (Mediterranean rows low, north_humid rows high). [V]
- Climate resolution: **3.125 px per unit** over the *theatre* box (not the world): eu 750x385 -> 2344x1203, egy 440x520 -> 1375x1625, ita 360x225 -> 1125x703. Spain uses 1.6 px/unit (432x385 -> 691x616). Dims = round(size * res). [V]
- `wind_map`: u32 w, u32 h, f32 scale (0.0071749 on every map), i8[w*h*2] = per-cell (u, v) vector, value = i8 * scale. |v| <= 0.93, so these are near-unit directions with a strength factor. Cells are 2.5 units over the theatre (eu 300x154, egy 176x208, ita 144x90). Spain is 172x153 where 172.8x154 would be expected; it was apparently made for slightly different bounds. [V]
- tut reuses the Europe theatre size, but its climate maps use the full Empire climate set (the American climates are present).

## 6. mountain_data

The polygons are authored impassable mountain ranges. About 83% of them (96/115) equal (IoU 1.0) the union of one impassable-land `nonwalk_group` (eu 9/13, egy 28/31, ita 36/48, spa 23/23). The rest are stale or partial copies (IoU 0..0.9). Most points are in the region vertex pool (eu 262/276). The bounds can be derived. [V] Engine use [?]: probably mountain rendering/labels or AI. It is not needed for point lookup.

## 7. Derivable vs authored

| field | status | how |
|---|---|---|
| region_data bounds; region/area/outline bounds | derivable, byte-exact [V] | `rebuild_bounds` |
| connectivity runs | derivable, byte-exact [V] | `rebuild_connectivity` |
| query_info (both trees) | derivable apart from in-cell order [V] | `build_query_info` |
| pass_group / nonwalk_group / landmass | partitions derivable from topology + passable/crossing flags + kind [V]; numbering of the component ids not reproduced | `derive_area_groups` |
| impassable pass_group numbering | derivable: sequential after the passable ids, in file order [V] | |
| faces | coverage derivable (any CW triangulation of the group; `triangulate` uses shapely CDT with no Steiner points, area matches vanilla). Exact triangles, Steiner lattice and the face-group split are authored. | `triangulate` |
| mountain bounds, groundtype_index names | derivable [V] | |
| region_keys | derivable from settlement positions [V] | |
| vertices, rings, kinds, passable, crossing, names | **authored** (geodata) | |
| settlements, slots, footprints | **authored** (with DB/startpos) | |
| climate maps, wind map, groundtype polygons, mountain polygons, bridges, trade nodes | **authored** (generatable from geodata/climate data) | |

## 8. What a from-scratch generator needs

1. A planar partition of the world box into **areas**, each a polygon with holes, grouped into regions (kind land/sea/river). Vertices must be shared exactly between neighbours (shared rings, twin edges). Outer rings go CCW, holes CW. Areas must tile the box with no gaps (the quadtree and lookup depend on it).
   Typical split: per region one passable main area, plus impassable patches; rivers as areas of the single `river` region cut out of the land; outer filler land regions for everything outside the theatre; seas as `sea` regions.
2. Flags: `passable` per area, `crossing` on strait sea areas. Bool #1 False.
3. Then run: `rebuild_bounds`, `rebuild_connectivity`, the component ids (`derive_area_groups`, then any numbering), faces (`triangulate` per area or per group, CW, duplicated into every area of the group), and `build_query_info` for regions and groundtypes (`left_codes=False`).
4. The groundtypes partition (a second planar partition with its own pool) plus names.
5. Theatre key/bounds, climate maps at 3.125 px/unit over the theatre (land + sea index rasters), wind map at 2.5 units/cell, the climate index tables (copy vanilla).
6. Settlement records (positions, footprints, slots with keys that match DB/startpos), region_keys, mountain polygons (optional?), bridges (x, y, angle), trade nodes.
7. Unknowns to settle in-engine: whether the face-group split and Steiner points matter (rendering of region highlight on terrain?), whether the numbering of the component ids must match pathfinding.esf, and whether in-cell edge order matters (it should not for point queries).

## 9. resize_world

`resize_world(esf, new_min, new_max)` (in place) does the following:

1. Pushes every vertex lying on the old world border onto the new border, in both region_data and groundtypes. Europe: 6 + 8 vertices, owned only by eur_map_west/east and grassland/grassland_cold_att. Egypt/Italy/Spain: 256 per pool, owned only by the outer filler regions ('west'/'east', 'ita_outere/w', 'spa_border*') and one groundtype.
2. Keeps a face blob if all its triangles stay CW; otherwise it re-triangulates that blob with `triangulate`.
3. Recomputes all bounds and sets the world bounds.
4. Rebuilds both quadtrees.

The theatre, climate/wind rasters and everything inside the theatre are untouched. The self-check doubles Europe and Egypt and checks the result: valid polygons, area sum = new box, CW faces, quadtree lookups = polygon containment, and a clean ESF round-trip. The output is written to `work/scratch_regions/<map>_resized_regions.esf`.

Untested and outside this file: whether the engine accepts a bigger world box. Other files are tied to the world box too: pathfinding grid origin/size, sea_grids, heightmap/supertexture/fogmask pixel scale (3.2 px/unit over the world), startpos. A bigger regions.esf alone may be rejected or rendered wrong. This is the experiment to run next.

## 10. Checks

`.venv/bin/python tools/regions_model.py` asserts the following on all 5 maps (and resizes Europe and Egypt):

- ESF round-trip.
- Bounds+connectivity rebuild byte-identical.
- Areas tile the box.
- Face blobs are CW, cover exactly their areas and stay inside one same-region component.
- The three id partitions hold, impassable ids are sequential, bool #1 is always False.
- Region i32 / settlement / region_keys agree.
- Groundtype names = region names.
- Quadtree header formula; rebuilt tree equal in structure/samples/codes/edge sets and in serialized size.
- Point lookup through vanilla and rebuilt trees = polygon containment.
- Resize validity.

## 11. Open questions

- Vanilla in-cell edge order (not reproduced) and the numbering order of the component ids. The source tool probably used hash/graph traversal.
- The face-group split rule and the Steiner lattice (density 7-8.5 units, jittered).
- Area bool #1, `map_heights` item layout, the theatre bool and `transition_areas` item layout: never non-empty or True in vanilla.
- Cross-references to `pathfinding.esf` (pass_group / nonwalk_group as obstacle/region ids?) and to `trade_routes.esf` (trade node keys).
