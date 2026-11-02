# 06. Napoleon campaign pathfinding ESF

Status: **partial**. The container, cell compression, polygon geometry, path-domain
mapping, geometric contact flags, and a concrete startpos dependency are decoded.
The implementation round-trips all five files byte for byte. It rebuilds polygon
placement, polygon-stream offsets, trait counts, contact flags, and compressed
cell runs for the four readable geometries. A general map generator remains
blocked by the boundary word's middle 20 bits, exact movement-cost generation,
Spain's scrambling, and parts of the startpos obstacle lifecycle.

All game inputs were read only. No game, launcher, Wine, Proton, Steam, or
Gamescope command was invoked. No git commands were used. Scratch artifacts are
in `work/scratch_pathfinding/`. The codec `tools/esf.py` was imported unchanged.

## Evidence and reproduction

Ground truth is the five loose files under:

```
~/.local/share/Steam/steamapps/common/Napoleon Total War/data/
  campaign_maps/{nap_europe,nap_egypt,nap_italy,nap_spain,nap_tut}/pathfinding.esf
  campaign_maps/<same>/regions.esf
  campaign_maps/nap_europe/metadata.dat
  campaign_maps/nap_europe/display/heightmap/heightmap.tga
  campaigns/mp_eur_napoleon/startpos.esf
```

The ESF record paths and array indices below identify binary evidence more
precisely than text line numbers in a truncated tree dump. The executable
assertions are in `tools/pathfinding_model.py`, especially `rebuild_spatial_grid`,
`inspect_startpos`, and `correlate_wind_costs`.

Run:

```sh
.venv/bin/python tools/pathfinding_model.py
```

Actual successful output:

```text
nap_europe: semantic round-trip OK (4,779,048 bytes); grid rebuild OK; cells=72375, polygons=49124, masks=34717
nap_egypt: semantic round-trip OK (1,733,204 bytes); grid rebuild OK; cells=57200, polygons=15713, masks=12100
nap_italy: semantic round-trip OK (1,087,198 bytes); grid rebuild OK; cells=20340, polygons=12477, masks=8603
nap_spain: semantic round-trip OK (1,956,614 bytes); opaque geometry preserved; expanded cells=41688
nap_tut: semantic round-trip OK (3,636,403 bytes); grid rebuild OK; cells=72375, polygons=36462, masks=22790
wind/cost correlation: {"east_west_windx_correlation": 0.998651, "north_south_windy_correlation": 0.998959, "samples": 19705, "wind_scale": 0.007174910977482796}
startpos: {"base_nodes": 12951, "boundary_manager_entries": 324, "characters": 103, "grid_paths": 7282, "matched_base_nodes": 12951, "overlay_cells": 22004, "overlay_references": {"dynamic": 8988, "static": 37217}, "path_domain_flags": 222, "path_domain_float_count": 222}
mutation check OK; raster geometry draft OK
diagnostics: work/scratch_pathfinding/europe_mesh_verified.png
PASS: static checks only; middle20/costs8/Spain cipher and runtime acceptance remain unresolved
```

`work/scratch_pathfinding/self_check.json` records full SHA-256 hashes, byte sizes,
and counts. `self_check.log` contains the captured run. The self-check builds a
fresh ESF tree from dataclasses, reparses it, and compares complete file bytes.
It also changes a semantic cell byte, encodes and reparses, and checks that the
change survives. This is not an original-byte passthrough masquerading as an
encoder. Retained unresolved fields are explicitly named or marked opaque.

The diagnostic `europe_mesh_verified.png` was rendered and visually inspected.
It overlays the decoded cell polygons on the original 4096×2048 heightmap.
Green is type 0, blue type 1, red type 2, purple type 3, yellow/orange types 4/5,
pale yellow type 6, and pink type 7. Coastlines, rivers, roads and interior
partitions align. The generator produces this PNG on every self-check run.
Earlier scratch plots are exploratory; `europe_faces.png` in particular omits
implicit corners and is not the verified reconstruction.

Public corroboration: [taw/etwng's semantic converter](https://github.com/taw/etwng/blob/master/esfxml/lib/esf_semantic_converter.rb),
particularly `convert_rec_grid_data`, `convert_rec_pathfinding_areas`,
`parse_path_boundary_data`, `convert_rec_grid_cells`, `convert_rec_boundaries`,
`convert_rec_PATHFINDING_GRID`, and `convert_rec_OBSTACLE_BOUNDARIES`.
That code identifies length-prefixed contours, region/path tables, empty-cell
runs, type names, and startpos reference fields. It leaves the middle 20 bits
unknown and calls the high byte `passable_part`. This investigation establishes
that the high byte is an eight-direction geometric contact mask. Its bit meaning
is verified independently against every readable-map traversable polygon.
The raw public sources inspected are saved in scratch. `pgm.rb` only reads and
writes PGM images; it is not a pathfinding generator.

## Container and root records

All five use the ABCE ESF container documented by `tools/esf.py`. Keep the
original timestamp, name-table order, record versions, scalar tags, array tags,
and child order to reproduce file bytes.

Normal root layout:

```text
root v0
  pathfinding_areas v0 ARRAY, one item
    vertices v0 ARRAY
    u32[] polygon stream
    grid_data v0 RECORD
```

Spain prepends `obstacles v0`, containing `u8[1024]`. Tutorial appends
`barriers v0 ARRAY`, with nine named items. These are real schema differences.
A root's children cannot safely be addressed by ordinal zero across all maps.

## Vertices and polygon stream

`root/pathfinding_areas[0]/vertices[i]` contains exactly two i32 scalars, x and y.
Decode each as `integer / 1048576` world units. Keep the integers in a writable
model; float conversion is unnecessary for encoding.

In the four readable maps, entries 0, 1, 2, 3 all store
`(-2147483647, -2147483647)`. They are **cell-local corner placeholders**, not
separators between polygons. Their resolved coordinates for cell `(column,row)`
with lower corner `(x,y)` and side length `s` are:

| Vertex ID | Position |
|---|---|
| 0 | `(x,y)`, southwest |
| 1 | `(x,y+s)`, northwest |
| 2 | `(x+s,y)`, southeast |
| 3 | `(x+s,y+s)`, northeast |
| 4 and above | Absolute fixed-point coordinates from the vertex table |

The next u32 array is a concatenation of polygons:

```
N, vertex_id[0], ..., vertex_id[N-1], N, vertex_id[0], ...
```

Its offsets are **u32 element offsets**, measured from the first length word,
not byte offsets or polygon ordinals. Offset zero is always
`4,0,2,3,1`, the full-cell quadrilateral. Every other polygon is referenced once
by a cell boundary record in the four readable files. There is exactly one more
polygon than explicit boundary records. There are no triangle strips or edge
pair records in this array. Europe polygon lengths range from 3 to 38.

The real geometry is a subdivision of each spatial tile into polygons. Many
polygons use both real vertices and implicit tile corners. The cell is part of
the geometric interpretation. Treating the first four vertices as points at
infinity, skipping them, or drawing one global unbounded mesh loses most faces.

For example, Europe's first explicit nonuniform cell is linear cell 1566,
column 66, row 4, lower corner `(-278,-182)`. Its two contours begin at u32
stream offsets 5 and 12:

```
5:  6,5,8,17,1,0,2
12: 4,3,17,8,5
```

Real vertices 5, 8, 17 run along that tile's coastline/transition boundary.
Resolving the corners makes both polygons lie exactly within the 2×2 tile.
The self-check asserts this containment for every explicit boundary in all
four readable maps, and derives each tile assignment from the polygon bbox.
Every explicit polygon has positive counterclockwise signed area. Summed signed
polygon areas equal the full tile area exactly, using integer arithmetic, for
all 17,935 Europe, 6,279 Egypt, 4,989 Italy and 14,354 Tutorial nonuniform cells.

## `grid_data` field order

These are actual ESF child indices. The origin uses two separate i32 values.

| Index | ESF type | Europe value | Meaning / confidence |
|---|---|---|---|
| 0 | i32 | -429916160 | Grid origin x, fixed-point, verified |
| 1 | i32 | -199229440 | Grid origin y, fixed-point, verified |
| 2 | u16 | 115 | Starting x cell relative to enclosing map grid; exact odd-origin rounding unresolved |
| 3 | u16 | 65 | Starting y cell relative to enclosing map grid; same limitation |
| 4 | i32 | 2097152 | Cell side length, fixed-point, verified |
| 5 | u32 | 375 | Columns, verified |
| 6 | u32 | 193 | Rows, verified |
| 7 | u32 | 103563 | Total traits across expanded cells, verified formula below |
| 8 | u16 | 72 | Passable-region count per public decoder; equals index 9 in these four maps |
| 9 | u16 | 72 | Number of listed region indices, verified |
| 10 | i16[] | length 72 | Zero-based indices into `regions.esf/region_data/regions`, verified |
| 11 | u16[] | length 540 | Path-domain table, decoded below |
| 12 | `grid_cells` array | 22242 serialized items | Compressed row-major cells, decoded below |

A cell's lower corner is:

```
x = origin_x + column * cell_size
y = origin_y + row * cell_size
linear_index = row * columns + column
```

Grid origin matches the lower theatre bound in `regions.esf/theatres/theatre`.
Columns/rows cover the theatre, rounded up to whole cells. Europe height is 385
units, requiring 193 cells and a one-unit excess at the top. Italy height is 225,
requiring 113 cells. The enclosing `region_data` world box is separate.

Europe starting offsets fit `(-410 - -640)/2 = 115` and
`(-190 - -320)/2 = 65`. Italy x is `(-185 - -320)/2 = 67.5`, while stored x is
68. These values do not mean a 115×65 grid, as earlier notes suggested. Do not
infer a fully established rounding rule from the even-origin cases.

### Region indices and path domains

The i16 table maps one-based local region references to zero-based region-array
indices. Europe begins `11,8,9,14,...`, resolving to `eur_gibraltar`, `eur_spain`,
`eur_greece`, `eur_sicily`, and so on. Tutorial includes a different region set
and ordering. This is a static geography reference, not a faction-owner number.

Read the u16 path table as:

1. A sequence of one-based references into that i16 table, terminated by zero.
   Each creates a single-region path domain, in sequence, with zero-based IDs.
2. The zero creates the sea domain, an empty region tuple.
3. Remaining words are length-prefixed sets: `N, local_region_ref[N]`.
   Each creates one further domain containing those regions.

Europe has 72 singleton domains, sea at ID 72, and composite domains through
ID 221. A singleton ordering swap matters: domain ID is not necessarily the
same as local-region-reference minus one. Composite entries refer directly to
the i16 region table, not to the singleton permutation. `Grid.path_domains()`
implements this distinction.

Path ID 1023 is reserved for transition/outside geometry. It is not an index
into the table. Every other explicit and uniform trait ID in the four readable
maps resolves through the decoded table.

### Cell records, compression and trait numbering

A nonuniform serialized item has:

```
u8[8] directional data
boundaries v0 ARRAY
  repeated {u32 attributes, u32 path_and_polygon_reference}
```

A uniform serialized item has:

```
u8[8] directional data
boundaries v0 ARRAY, zero items
u32 attributes
u16 path_id
u8[] following_uniform_cells
```

The blob is **uncompressed fixed-size records**, each exactly:

```
8 bytes directional data
u32 attributes, little endian
```

Each represents the next row-major cell, inheriting the uniform starter's
`path_id`. It is not a bitmask, zlib stream, per-cell polygon list, or data for
only the starter cell. A blob may have zero length. Runs can cross row ends.
The starter has its own attributes; following records can have different
attributes and costs, but retain its path ID.

The vanilla encoder uses maximal consecutive runs of uniform cells with the
same path ID. Expanding into semantic `Cell` objects and independently grouping
by this rule reproduces the serialized bytes of all five maps, including Spain.
Europe's first 18,780-byte blob is 1,565 following cells. Including the starter,
it occupies cells 0 through 1565; the next serialized record is cell 1566.

Each nonuniform cell contributes `len(boundaries)` traits. Each uniform cell,
including every expanded blob record, contributes one. Thus:

```
trait_count = sum(max(1, boundary_count(cell)) for cell in expanded_grid)
base_trait_offset(cell) = cumulative trait_count before that cell
```

This yields Europe's header count 103563 exactly. It is also the numbering
scheme used by startpos base-grid nodes.

### Boundary words

First u32:

| Bits | Meaning |
|---|---|
| 0–3 | Path type |
| 4–23 | `middle20`, unresolved packed connectivity data; preserve exactly |
| 24–31 | Eight-direction geometric contact mask, decoded and rebuilt |

Second u32:

| Bits | Meaning |
|---|---|
| 0–21 | Polygon-stream u32 element offset |
| 22–31 | 10-bit path-domain ID, with 1023 reserved |

Type names from taw's public converter, with local geometry supporting the
coast/river/road distinctions, are:

| Value | Name | Europe explicit traits |
|---|---|---|
| 0 | Passable area | 23132 |
| 1 | Sea boundary | 4899 |
| 2 | Transition area | 10165 |
| 3 | River | 4241 |
| 4 | Land bridge area | 73 |
| 5 | Land bridge transition area | 71 |
| 6 | Road | 4585 |
| 7 | Slot | 1957 |

Type 1 is also used for uniform sea cells. Type 2 includes outside/impassable
coverage. No type here is established as a distinct mountainous-impassable code.
Height or land/sea alone cannot distinguish all these categories. River crossing
cannot be generated by painting river pixels passable: types 3, 4 and 5 distinguish
river polygons and bridge-related areas, and startpos has further obstacles.

The high-byte bits, from least to most significant, mean contact with:

| Bit in word | Contact |
|---|---|
| 24 | East side |
| 25 | Northwest corner |
| 26 | North side |
| 27 | Northeast corner |
| 28 | Southwest corner |
| 29 | South side |
| 30 | Southeast corner |
| 31 | West side |

For a side, at least two distinct polygon vertices lie on it. For a corner,
the polygon contains the exact corner point. Types 2 and 3 always have zero
contact mask, irrespective of geometry. Every other type matches this geometric
rule in all four readable maps: 34,717 + 12,100 + 8,603 + 22,790 polygons.
This rules out the older interpretation of the byte as a passable percentage.

The middle 20 bits split into five nibbles: from the lowest, **S, W, same-cell, E, N** connectivity
masks (2026-10-18, `probe_g3.middle20`). Bit j of a side nibble is set when this polygon shares an edge
segment on that side with the j-th polygon of the neighbouring cell, counting only neighbour polygons of
the same passable class. A polygon is passable unless its kind is 2 or 3; its class is sea if its path
domain is the grid's sea domain (`path_domains().index(())`: Europe 72, Egypt 30, Italy 27), else land.
A uniform neighbour counts as one polygon (bit 0). The same-cell nibble uses the same rule within the cell.
Polygons of types 2 and 3 store 0. Full uniform sea and land are `0x11011`.

Exact-match rate for the whole 20-bit field across all passable polygons: Europe 92.6% (sea 96.8%,
land 93.7%), Egypt 94.0%, Italy 93.4%. The misses are mostly roads (type 6, ~87%), slots (7) and
bridge transitions (5). Ordinal readings that index *all* polygons, or all passable polygons
regardless of class, give only ~85%; the class split is what makes it work. This is good enough to
generate sea/coast/off-map cells. Roads and bridges still need work.

**Welding invariant.** In every readable vanilla grid, two cells sharing a side split it into identical
intervals with identical vertices; classes are sea, land and blocked (types 2/3). So a domain
boundary never runs along a cell side, and there are no T-junctions. `tools/pf_check.py` checks
this. Vanilla scores 0 mismatches. A G3 build with 733 sea/off-map shared sides crashed in game (an
outline trace looping until a 1 GiB allocation failed, research/00 G3). The welded rebuild plays.

### Eight cell bytes

The direction order is consistent with the contact-mask order:
`E,NW,N,NE,SW,S,SE,W`. These are strongly supported as directional movement-cost
bytes, with wind dependence on sea. Their precise numeric scale, terrain formula,
interpolation and special values remain unresolved.

Independent correlation uses the Europe `regions.esf` theatre's `wind_map`:
`u32 width=300`, `u32 height=154`, f32 scale `0.007174910977482796`, and interleaved
signed i8 x/y samples. Map cell centres into that theatre raster without a y flip.
For 19,705 uniform sea cells without byte 255, Pearson correlations are:

```
(cost[E] - cost[W]) with wind_x: 0.998651
(cost[N] - cost[S]) with wind_y: 0.998959
```

A nearest-sample regression is approximately
`cost[d] = 20 + 20 * wind_scale * dot(wind, unit_direction[d])`.
Residuals remain around 0.4–0.7 byte units in exploratory fits, so this is not an
exact encoder formula. Land interiors commonly have eight copies of 31;
some have repeated 121 or 171. Boundary/outside cells often include 255 and 1.
The hypothesis that 255 is an unavailable/blocked direction is plausible, but
its complete contract was not tested. No defaults are silently substituted.
Uniform outside cells store `1f ff 1f ff ff 1f ff 1f`: 0x1f on the four sides, 0xff on the diagonals.
Sea polygons whose neighbour is blocked carry the same bytes in that direction, so the G3 rims write
0x1f / 0xff toward uniform off-map neighbours. Byte 0x01 marks a direction that leaves the grid.

## Cross-map results and special cases

| Map | Vertices | Serialized cells | Expanded cells | Explicit polygons | Columns×rows | Traits | Path domains |
|---|---:|---:|---:|---:|---:|---:|---:|
| Europe | 93380 | 22242 | 72375 | 49123 | 375×193 | 103563 | 222 |
| Egypt | 18868 | 8458 | 57200 | 15712 | 220×260 | 66633 | 113 |
| Italy | 16092 | 6299 | 20340 | 12476 | 180×113 | 27827 | 92 |
| Spain | 31324 | 9974 | 41688 | 19391 | 216×193 inferred | 53464 derived | unresolved |
| Tutorial | 58799 | 18205 | 72375 | 36461 | 375×193 | 94482 | 236 |

Add one shared full-cell polygon to the explicit count to get polygon-stream
record counts for the readable maps. Europe and Tutorial share geography but
have substantially different topology, roads/slots and region domains. Neither
file's IDs can be reused as the other's numbering.

Spain's scalar values in vertices, polygon u32 stream, grid header and region
lookup arrays look scrambled; its cell structure, attribute words, references
and run blobs retain the normal form. Its extra 1024-byte `obstacles` payload
is retained opaque. A repeating XOR/add/subtract key directly taken from that
payload does not explain the first four presumed sentinel vertices. This is
not a successful cipher recovery. The implementation conservatively marks the
area obfuscated whenever the root has `obstacles`, reproduces all wire fields,
and rejects geometric rebuild/domain interpretation.

Spain `regions.esf` gives theatre `(-213,-179)..(219,206)`. At 2 units per cell,
that implies 216×193 = 41688, exactly the independently expanded cell count.
This supports those dimensions but does not decrypt the stored header or vertex
coordinates. The derived 53464 traits also has not been matched to its scrambled
header. Avoid interpreting cipher integers as coordinates near ±2048.

Tutorial `barriers` has nine named entries such as `shroud_map_1_3`. Each has nine
u32 arrays. Reinterpreting pairs as signed fixed-point coordinates yields polygon
outlines. The model decodes and re-encodes these pairs losslessly. The role/order
of the nine outlines and their relationship to changing tutorial shroud/clearance
have not been established; they are not grid-cell IDs.

## Relationship to other map inputs

`regions.esf/region_data/regions` is the confirmed region-index target.
`theatres/theatre` supplies the confirmed active bounds, and its `wind_map`
explains much of the directional byte variation. Region ownership itself is a
campaign/startpos property. A composite path domain can span several static
regions; its presence is not evidence that those regions share an owner.

The Europe heightmap registration used by the diagnostic is:

```
image_x = (world_x + 640) * 3.2
image_y_from_top = 2048 - (world_y + 320) * 3.2
```

Pillow already exposes top-oriented image rows; the formula accounts for the
original TGA's bottom-left origin. Do not flip the image a second time.
Mesh geometry contains coastline buffer/transition strips and subdivision not
recoverable by taking nonzero-height contours alone.

Europe metadata is `MTGI`, width 2048, height 1024, then one u8 per pixel.
Observed histogram is 0:1631741, 1:5, 6:465406. Sea code 6 agrees with the supplied
input description and recognizable geography. A reliable world-to-metadata
transform was not established in this lane. Naively mapping it onto the full
heightmap world box gives poor correspondence, so no metadata-to-mesh generator
is claimed. `metafit.py` under scratch records exploratory registration attempts.

## Startpos `CAMPAIGN_PATHFINDER`

The exact input checked is **mp_eur_napoleon**, not the single-player startpos.
Its record is at:

```
CAMPAIGN_STARTPOS/CAMPAIGN_ENV/CAMPAIGN_MODEL/CAMPAIGN_PATHFINDER v5
```

It contains `PATHFINDING_GRID v4 ARRAY` with one item, followed by bool true and
an empty bool array. The grid item fields are:

| Index | Type / record | Observed contents and status |
|---|---|---|
| 0 | u32 | 7282, number of dynamic grid polygons, verified |
| 1 | u32[] | 131066 words, dynamic polygon stream, decoded below |
| 2 | `OBSTACLE_BOUNDARY_MANAGER v1` | `OBSTACLE_BOUNDARY v1 ARRAY`, 324 items, each an even-length u32 array; management semantics unresolved |
| 3 | `OBSTACLE_BOUNDARIES v1` | u32[158422], per-cell overlays, decoded below |
| 4 | `OBSTACLE_BASE_GRID_NODE v1 ARRAY` | 12951 nodes, static trait offsets/counts verified below |
| 5 | u32[] | 25902 words, packed coordinate -> base-node-index pairs, verified |
| 6 | `OBSTACLE_LISTS v1` | Parallel ID arrays and barrier/character/fort obstacle arrays; 0/103/0 entries |
| 7 | u32[] | Empty; purpose unresolved |
| 8 | bool[] | 222 entries, one per path domain, exact policy unresolved |
| 9 | bool | True; purpose unresolved |
| 10 | u32[] | Empty; purpose unresolved |
| 11 | f32[] | 222 values, one per domain, mostly approximately 0.67 with some 0.5; exact policy unresolved |
| 12 | `BARRIER_NAMES v0 ARRAY` | Empty in this startpos |

### Dynamic polygon stream and overlay references

The dynamic stream is:

```
N, x0, y0, ..., x[N-1], y[N-1], trailing_u32
```

Coordinates are i32 fixed-point bit patterns carried in a u32 array. This stream
stores its own coordinates, not static vertex IDs. It parses completely into
7282 polygons. The trailing word takes values 1,2,3,4,6,7 here. Taw calls it
`repetitions`; the exact meaning remains unverified.

The `OBSTACLE_BOUNDARIES` stream is:

```
N, (attributes, reference)[N], packed_cell, 0
```

`packed_cell = (row << 16) | column`, relative to the static pathfinding grid.
All records parse with their trailing zero and in-bounds coordinates.
There are 22004 cell overlay records and 46205 references.

Overlay reference packing differs from the static file:

| Bits | Meaning |
|---|---|
| 0–20 | Index payload |
| 21 | Dynamic polygon selector |
| 22–31 | Path-domain ID, signed 10-bit in taw's interpretation |

With selector zero, the payload is a **static polygon-stream word offset**.
All 37217 such references match real static polygon starts. With selector one,
it is a **dynamic polygon ordinal**, not a word offset. All 8988 such references
are in `0..7281`. Confusing the two numbering schemes fails immediately, for
example dynamic index 62 is not generally the offset of polygon 62 in either
stream. Additional path types 8–11 are named move area, unit, garrisoned unit,
fort in the public converter; their complete runtime semantics are unverified.

### Base-grid nodes: verified static coupling

The first two fields of each base node are:

```
u32 first_static_trait_offset
u32 static_trait_count_in_this_cell
```

Next are two `MANAGED_OBSTACLE_BOUNDARY v1` arrays. The first array's items have
`u32,u32,bool,u32[]`; the second's have `bool,u32[]`. Their management lists and
lifecycle are retained as an open question, not synthesized. Boundary-manager
payloads are variable-length pairs, for example `[748116830,0,749173606,0]`
and `[749183518,1]`; they must not all be treated as four-word quads.

Index 5 of the grid item is a sequence:

```
packed_cell, base_node_index, packed_cell, base_node_index, ...
```

Every one of the 12951 node indices occurs once. For each coordinate, the node's
first field equals the static grid's cumulative trait offset and its second
field equals that cell's expanded trait count. **12951/12951 match**, not just
selected examples.

Example: coordinate row 9, column 7 maps to base node index 4290. Its first two
values are `(3629,1)`, exactly the static trait offset and count of that cell.
The first base node in storage has `(45165,2)`; node storage order therefore is
not row-major cell order. Regenerating polygon order changes these IDs even if
the shape of the world remains similar.

Character obstacles contain an `OBSTACLE v4`, separate character-related IDs,
multiple `BOUNDARIES v0` arrays, managed-boundary arrays, fixed-point world
bounds, and four u16 coordinate pairs. These are map-local dynamic state.
Their complete construction and linkage to character IDs were not decoded here.
The base-node lookup is not a substitute for rebuilding them.

### Required agreement for a new startpos

At minimum, regeneration must keep all of these consistent:

- Grid dimensions/origin/cell size and every packed overlay/node coordinate.
- Expanded static trait ordering, each base-node offset, and its static count.
- Static polygon offsets in overlay references, including the shared full quad.
- Dynamic polygon ordinals and their coordinate frame.
- Path-domain ID order, region-index targets, per-domain bool/float arrays.
- Character/slot/fort/barrier placements and managed-obstacle references.

It is not established that all obstacle records can safely be emptied and rebuilt
by the engine on load. No such shortcut is used or claimed. Reusing the old
`CAMPAIGN_PATHFINDER` after replacing geography is known to retain wrong static
references; whether it crashes, silently misroutes, or gets repaired requires
an authorized runtime test outside this lane.

## What is rebuildable, and what a generator still needs

`PathfindingModel` exposes semantic `Area`, `Grid`, `Cell`, `Boundary`, `Trait`
and `Barrier` objects. `encode()` constructs new `Rec`/`Val` objects with the
original container metadata. The model stores the currently unresolved fields
rather than claiming a fully understood generator contract.

`rebuild_spatial_grid(area)` resolves implicit corners, recomputes tile placement
from absolute polygon bboxes, validates containment, regenerates contact masks,
builds a fresh row-major polygon stream and offsets, and recomputes trait count.
The encoder then independently packs maximal uniform runs. All these outputs
compare exactly to vanilla for Europe, Egypt, Italy and Tutorial.

The rebuild intentionally retains uniform-cell coverage, boundary order within
a tile, middle20, costs8 and domain membership. It does not reconstruct unknown
values from geometry. Because implicit corners need their source tile to be
resolved initially, it also is not a generic polygon clipping engine. A generator
starting from arbitrary global polygons must first clip them to tiles and assign
that context itself.

`generate(raster, origin, cell_size)` is a clearly marked geometry-only sketch.
It accepts a bottom-up 0=land, 1=sea, 2=blocked raster and returns fixed-point
full-tile quads with a list of required missing fields. It deliberately returns
no deployable ESF and does not pick guessed defaults.

A complete from-scratch compiler needs these stages:

1. Establish active bounds, fixed-point coordinates, grid size and starting-cell
   rounding. Preserve the separate enclosing heightmap world box.
2. Build classified region/coast/impassable/river/bridge/road/slot geometry.
   Ownership does not replace the static region indexing.
3. Clip the combined subdivision to each spatial tile. Weld real vertices,
   insert the four implicit corner IDs, and encode each tile's polygons.
4. Build the region index table and ordered singleton, sea and composite path
   domains. Allocate reserved IDs and update all trait domain references.
5. Generate middle20 with the S/W/same-cell/E/N class-mask rule above. It is about 93% exact and
   97-99% for sea. Roads, slots and bridges remain open.
6. Generate directional costs from terrain, wind and accessibility with the
   engine's quantization and boundary rules. Correlation alone is insufficient.
7. Compute contact masks, offsets, trait counts, uniform-cell runs and serialize.
   These stages are implemented and checked against vanilla.
8. Build the startpos dynamic polygons, overlays, base nodes, lookup tables,
   managed obstacle graph and per-domain arrays for actual campaign placements.
   Only the static coupling and parts of the serialized geometry are decoded.
9. Run independent parser checks, geographic diagnostics and eventually a
   permissioned runtime route test for land, sea, impassable edges, rivers,
   bridges, roads, slots and changed ownership.

The result removes several structural unknowns but does not clear the original
from-scratch campaign-pathfinding blocker. There is no runtime acceptance claim.
