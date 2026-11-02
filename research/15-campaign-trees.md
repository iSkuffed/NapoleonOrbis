# 15 - Campaign-map trees outside Europe (research + prototype)

Question: everything we added outside Europe has no trees. Can the rest of the world get believable trees and forests?
Written 2026-10-21, read-only research. Prototype scripts and stats are in `work/scratch/trees/` (nothing in `tools/`, `data/` or the game folder was touched,
and no game or world build was run). Tags: [V] verified (script, decompile or file check), [I] inferred, [?] unknown.
Companion: research/07 section 2.5 (the file format).

## 0. Verdict

**Feasible, low risk, cheap.** It is a display-only file (`display/trees/campaign.rigid_trees`), with no regions.esf, pathfinding or startpos involvement.

- All 174 model files exist in `rigidmodels.pack`, and one shared texture atlas already contains every species (jungle, Indian, desert, cactus, palm, US, Mediterranean) [V].
- `w` is a plain uniform mesh scale, from the vertex shader [V].
- The loader has no instance, per-model or per-file cap. An instance costs 16 bytes of RAM [V decompile], so 100k instances is about 1.6 MB.
- A prototype produces a valid, round-trip-checked file with 41k / 65k / 102k total instances in 6 s and 1.3 GB RSS [V].
- The real unknowns can only be settled in game: how the unused species look, the visual density, and the frame rate when zoomed out over jungle.
- Recommended source: RESOLVE Ecoregions 2017 (CC BY 4.0, 149 MB, already downloaded), plus the BMNG darkness already in the repo for patchiness.
- Groundtypes: do not touch them in v1 (section 7).

## 1. What the world build writes today [V]

- `tools/world_build.py` line 111: `shutil.copytree(SRC, OUT, ignore=...('fogmask','snow','snowmask','supertexture','heightmap'))`, with `SRC = <game>/campaign_maps/nap_europe`.
  So `display/trees/campaign.rigid_trees` is **copied byte-for-byte from vanilla Europe**. Nothing regrids it and no other script writes trees (grep of `tools/`: only `display.read_rigid_trees` / `write_rigid_trees` exist).
- That is correct only because `tools/proj.py` is the identity on the vanilla theatre (-410,-190)..(340,195). All 8903 vanilla instances lie inside it (x -373.2..326.9, z -176.3..176.5), so they still sit on the right land.
- The world therefore has Europe's 8903 trees and nothing else.
- `snow/`, `snowmask/` and `fogmask/` are also dropped from the world map. Consequence for trees: [I] the shader blends winter colours by `campaign_snow(world_pos)`, so the winter look of new trees depends on what the missing snow data gives. Test it, and expect summer and autumn only.

## 2. Tree models

### 2.1 Existence [V]
- The file lists 174 `RigidModels/CampaignTrees/Campaign_tree_*.rigid_model` paths. **174/174 exist in `rigidmodels.pack`** (the pack holds 311 files under `rigidmodels/campaigntrees/`: the models plus `_low` LODs).
  Three `darkconiferous_largecluster_dense` also have `_lod02` files, but the loader only builds `_low.rigid_model` names (decompile), so `_lod02` is unused.
- `_low` LOD variants exist for 132 of the 174. The 42 **without** `_low` are the desert set (cactus, cactus_pear, deserttree, desertrock), `grass`, `savannahgrass`, `ustree2`, `indiantree_largecluster_dense`, and all `mediteranean01` dense and all `mediteranean02` clusters.
  Vanilla Europe uses the Mediterranean ones anyway (about 1000 instances), so a missing `_low` is fine [V]; the loader falls back to a default handle.
- Textures: only ONE atlas, `campaigntrees_diffuse0.dds` (2048x512), plus `_autumn_` and `_snow_` variants. The `.tai` atlas list holds coniferous 2-11, floridaconiferous, ind_tree 1-3, jungletree, desert_tree 1-3, cactus 1-2, palmleaf, oak, hornbeam and more.
  So every model renders without extra assets [V].
- Models are not Empire leftovers: they are in NTW's pack and CA's ETW-era `testdata/campaigntrees/campaign.rigid_trees` (in `data.pack`, 27,618 instances, 134 non-empty models, x -754..915) uses them for jungle, Indian, US, olive, cactus and palm. Egypt's vanilla file already uses palm and indianjungle models (1084 + 91 instances) [V].
- Format of the model: `rigid_model` v1 with magic 0x12345678, then streams, then u32 0, `nverts`, vertices of 20 floats, `nidx`, indices.
  Position = columns 0-2 (about +-0.03: the model is tiny and the instance scale `w` is about 36). My parser (`work/scratch/trees/mdl.py`) reads 162 of 174. The 12 failures are `desertrock01-03`, `grass_01-03`, `savannahgrass_01-03` and `ustree2_01-03` (smaller files, different stream/vertex layout) [?].

### 2.2 Models by biome (file name stem after `Campaign_tree_`; radius = x/z half-extent x 36, in world units; tris at full LOD)

| family (3 variants each) | kind | tris | radius u | Europe uses | CA test data uses | biome fit |
|---|---|---|---|---|---|---|
| `darkconiferous01-03` | single | 23 | 0.35 | 204 | yes (4331) | boreal / taiga, tundra fringe |
| `darkconiferous_smallcluster_dense / _sparse` | cluster | 200 / 100 | 0.75 | 1459 / 76 | yes | **boreal/taiga** (Europe's boreal is 70 % this) |
| `darkconiferous_largecluster_sparse` | cluster | 300 | 1.6 | 130 | yes | boreal |
| `darkconiferous_largecluster_dense` | cluster | **3000** (6.9k verts) | 3.5 | 28 | yes | boreal/Pacific NW, use very sparsely |
| `coniferous01-03` | single | 19 | 0.35 | 216 | yes | conifer, mixed |
| `lightconiferous_*` (small/large, dense/sparse) | cluster | 57-190 small, 200-630 large | 0.8-1.9 | 1773 | yes | **temperate conifer**, montane, mixed forest |
| `deciduous01-03` | single | 15-19 | 0.45 | 442 | yes | temperate broadleaf |
| `deciduousconiferous_*` | cluster | 57-114 small, 167-413 large | 0.9-1.8 | 2887 | yes | **temperate broadleaf/mixed** (Europe's main forest) |
| `darkdeciduous_*` | cluster | 57-342 | 0.9-1.9 | 6 | yes | dark broadleaf (east Asia, N. America), underused |
| `lightdeciduous01-03` | single | 19 | 0.45 | 0 | yes (304) | light broadleaf / woodland, unused |
| `mixedconiferous_*` | cluster | 100-900 | 0.8-2.1 | 7 | yes | conifer/broadleaf mix (PNW, Canada), underused |
| `mediteranean01_*` (sic) | cluster | 63-290 | 0.65-1.9 | 1189 | yes | **Mediterranean** (maquis/holm oak) |
| `mediteranean02_*` | cluster | 86-404 | 0.9-2.0 | 181 | yes | Mediterranean (pine/cypress) |
| `mediterranean01-03` | single | 22 | 0.2 | 46 | yes | Mediterranean |
| `olive01-03` | single | 30-39 | 0.7 | 0 | yes (431) | olive, Mediterranean farmland |
| `palm01-03` | single | 44-129 | 0.35-0.7 | 230 | yes (2203) | palms: Levant, Egypt, oases, tropical coast, mangrove |
| `jungle01-03` | single | 21-30 | 0.8 | 0 | yes (775) | tropical |
| `jungle_*` | cluster | 51-324 | 1.2-2.1 | 0 | yes | **Amazon, Congo, generic rainforest** |
| `indianjungle_*` | cluster | 48-288 | 1.1-2.3 | 0 | yes | **South and Southeast Asia rainforest** |
| `indiantree_*` | cluster | 83-826 | 0.9-1.9 | 0 | yes | Indian lowland, monsoon forest, tropical dry forest |
| `indiantree1_01-03` / `indiantree2_01-03` | single | 14-28 / 27-42 | 0.4-0.6 | 29 / 0 | yes | Indian subcontinent, savanna |
| `ustree1_01-03` | single | 16-20 | 0.5 | 0 | yes (366) | North America (broadleaf) |
| `ustree2_01-03` | single | ? (unparsed, 2.9 KB) | ? | 0 | ? | North America [?] |
| `deserttree01-03` | single | 20-22 | 0.55 | 0 | ? | desert scrub, acacia-like, savanna |
| `desertcactus01-03`, `desertcactus_pear01-03` | single | 94-114, 39-62 | 0.2 | 0 | yes (399) | Sonoran/Mexican desert, opuntia |
| `desertrock01-03` | single | ? (unparsed) | ? | 0 | ? | rock outcrops in desert [?] |
| `grass_01-03`, `savannahgrass_01-03` | single | ? (unparsed) | ? | 0 | ? | grassland/savanna tufts [?] |

Totals: Europe uses 78 of 174 models. Another 96 are free. The unused ones that matter are the whole tropical, desert and US sets.
Average cost in Europe: 160 tris per instance at full LOD (88 at `_low`), 1.43 M tris if every instance were drawn at once.

### 2.3 Clusters, not trees
Most instances are **patches** of trees (clusters), not single trees. A `smallcluster` is about 1.8 units across (about 10 km), a `largecluster` about 3.6 (`darkconiferous_largecluster_dense`: 7).
A "forest" is therefore a loose field of overlapping patches. Vanilla placement has nearest-neighbour spacing median 1.40 u, 5th percentile 0.86, 1st percentile 0.54 (below that, never).

## 3. What `w` means, and Europe's density

### 3.1 w is a uniform mesh scale [V]
`fx/campaigntree_vertex.fx_fragment` (in `data.pack`):
```
world_position.xyz = v.position.xyz * pos_scale.w + pos_scale.xyz;   // the instance float4 (x,y,z,w)
wind_power = min(10, world_position.y - pos_scale.y) * 0.05;
t = time_in_sec + pos_scale.w + pos_scale.y + pos_scale.x;          // w also de-phases the wind sway
```
- So `w` is the scale, and also a phase for the wind sway.
- Vanilla stats: uniform over [35, 38.5] (7-bin histogram 1380/1337/1351/1258/1194/1201/1182, mean 36.69), correlation with y -0.02, same for singles and clusters, 3177 distinct values. It is a random size jitter of +-5 %.
  Italy's hand-made file goes up to 51.5, so larger values are allowed.
- The shader technique is `campaign_tree_instanced_vs30_sm3` (hardware instancing, stream `POSITION1` = the 16 byte instance) with an SM2 fallback.
- **Ground height y** is not snapped by the engine. Fit on vanilla: `y = 0.01881 * heightmap_byte + 0.006` (correlation 0.98, residual 0.06 u), i.e. `y = h / 53.2`, with `h` taken from our world `heightmap.tga` at 3.2 px/u.
- In the file, the per-cell bbox (-1,-1,-1,1,1,1) and the header 1024.0 / 6 are **read and discarded by the loader** [V decompile of 0x966500]. The engine takes the bbox from the model itself.

### 3.2 Europe's density (vanilla, `work/scratch/trees/density.py`, `calib.py`) [V]
Theatre land = 191,048 one-unit cells (1 u^2 is about 47 km^2 at 50N in Europe: 5.5 x 8.5 km).

| measure | value |
|---|---|
| instances on land | 8663 (97 %); 0.045 per u^2 over all land = 1 per 22 u^2 = 1 per about 1000 km^2 |
| land with no instance within 3 u | 65 % (the open look) |
| forest patches (3 u window >= 0.15 per u^2) | 11 % of land, mean **0.28 per u^2** = 1 per 3.6 u^2; 99th percentile of the local density 0.35 per u^2 |
| other land with any tree (0.02-0.15) | 24 %, mean 0.059 per u^2 |
| by biome (RESOLVE) per u^2 over the whole biome | temperate broadleaf/mixed 0.049, **temperate conifer 0.141**, boreal 0.058, Mediterranean 0.041, tundra (Lapland) 0.090, temperate grassland **0.0007**, desert 0 |
| camera-scale local maxima | 10x10 u window: max 53 (99th percentile 31); 30x30: 213 (152); 60x60: 539 (398) |

- The vanilla biome-to-model mix agrees with the ecoregion map. Boreal is 70 % `darkconiferous_smallcluster_dense`, the Mediterranean is `mediteranean01/02` plus palms, temperate is `deciduousconiferous` plus `lightconiferous`, and steppe has no trees.
  CA authored forests by hand but followed the same logic, so a biome-driven generator reproduces the look.
- Within a biome, the patches correlate only weakly with anything measurable: BMNG darkness (Spearman 0.17 for temperate broadleaf, 0.38 for conifer and Mediterranean), slope (0.12-0.14), elevation (about 0). So patchiness = smooth noise + BMNG darkness, not a deterministic function.
- Keep-out: the nearest vanilla tree to a settlement is 0.87 u at minimum, 2.4 u at the 5th percentile, 5.3 u median (72 settlements). A keep-out of about 2.3 u around settlements and ports reproduces that.
- Scale: outside Europe the world is stretched to 9.6-10.7 u/deg (Europe 13.1), so 1 u^2 is about 100-115 km^2 in the tropics. Match **per-u^2 density** (the on-screen look), not per-km^2.

## 4. Land-cover source

| source | what | licence | size / resolution | verdict |
|---|---|---|---|---|
| **RESOLVE Ecoregions 2017** (Dinerstein et al.) | 847 potential-vegetation ecoregions in 14 biomes (moist/dry tropical forest, temperate broadleaf, conifer, boreal, savanna, steppe, montane, tundra, Mediterranean, desert, mangrove) | **CC BY 4.0** (`LICENSE` field in the .dbf, row 1) [V] | zip 149,248,653 B (shp 243 MB), vector polygons. URL `https://storage.googleapis.com/teow2016/Ecoregions2017.zip` (HTTP 200 checked). **Downloaded** to `work/geodata/ecoregions/Ecoregions2017.zip` | **recommended**: natural vegetation, so no 2020s cropland or deforestation to undo (research/04 reached the same choice) |
| BMNG July 2004 (already in `work/geodata/bmng`) | 21600x10800 imagery, 1.85 km/px | NASA, not subject to US copyright | 21 MB | **use only as the patch modulator** (darkness); it shows summer crops as green, so it cannot give forest vs crop alone |
| ESA WorldCover 2021 | 10 m 11-class | CC BY 4.0 | one 3 x 3 degree tile = 74 MB (`.../v200/2021/map/ESA_WorldCover_10m_2021_v200_N48E000_Map.tif`); global about 120 GB | no: modern, huge. Anachronistic cropland and deforestation |
| ESA CCI Land Cover 300 m | 300 m, 22 classes | CC BY 4.0 | about 2+ GB per year NetCDF (not checked) | too big, modern |
| MODIS MCD12C1 (0.05 deg) | 5.6 km classes | NASA public domain | tens of MB per year | needs Earthdata login, modern; fine as a fallback |
| WWF TEOW (Olson 2001) | the older version of the same ecoregions | not confirmed; the download returned 403 | about 20 MB | skip, RESOLVE supersedes it |
| Natural Earth (already in geodata) | land, lakes, glaciers, regions | public domain | | no forest layer; used for land, lakes and the ice mask |
| HYDE 3.3 (cropland 1800) | 5 arc-min | licence unconfirmed (research/04) | about 10 km | the correct way to model 1805 clearing; v2 (see plan) |

- Natural vegetation is right for 1805, because most of the world was far less cleared than today. Europe is already authored by CA and stays as is.
  For India and China, where 1805 cropland was dense, use an explicit "cleared" factor (HYDE 1800 later). The prototype uses placeholder boxes (India 0.35, China 0.35, Japan 0.5, Java 0.3) and 0.8 for eastern North America.
- Rasterised in `work/scratch/trees/eco_raster.py` (pure struct and PIL, no GDAL): 0.05 deg biome raster, 26 MB `biome.npy`. The unzipped 243 MB shapefile was deleted again (re-extract it from the zip to re-run).

## 5. Budget and risk (32-bit exe)

### 5.1 Loader limits (Ghidra, `work/scratch/trees/loader.c`, `ins.c`, `ins2.c`) [V unless marked]
| item | finding |
|---|---|
| loader | VA 0x966500: magic 0x3D4D4047 ("G@M="), version must be 1. Reads and **discards** the two header dwords (1024.0 and 6). Per model: path, loads the model, loads `<name>_low.rigid_model` (if that does not exist, a default handle is used), then per cell: reads and discards the bbox, then per instance x,y,z (vec3) + w |
| instance insert | VA 0x914A30: AABB = model bbox x w + position, put into a **quadtree** (root = the display box, patched to +-2048 by `exe_patch.py` group `display`). The record is 16 bytes: u8 model index + 24-bit id + x,y,z. `FUN_009617e0` appends it to the node's vector (capacity doubling) |
| count caps | **none in the loader**: no counter limit, no array size, no per-cell cap. Memory is 16 B per instance (+ doubling slack), so 100k = about 1.6 MB |
| model count | the model index is a **u8**: at most 255 models. We use the vanilla 174, so we cannot add new tree meshes without a limit hit (not needed) |
| position range | the root is +-2048, and our world is +-1910 x -1240..365, so everything fits. Instances that straddle a root quadrant line fall through to the object's own list (vanilla has instances at x=0 and z=0 and works, so they are not dropped) [I] |
| evidence of scale | CA's own `testdata` file: 27,618 instances (3 times Europe) in one map |
| LOD / imposters | cvars exist in the exe (strings): `render_campaign_trees`, `render_campaign_tree_imposters`, `enable_campaign_tree_lods`, `campaign_tree_lod_distance` (registered at VAs 0x4268C3, 0x426883, 0x425233, 0x423FA6). So there is distance LOD (the `_low` meshes) and imposters. The default distance is [?] |
| culling | quadtree by node bbox [I]. The `fx` comment says trees do not render to the depth pass. Per-frame cost therefore tracks what is **on screen**, not the world total |

### 5.2 Instance budget
Prototype run (`work/scratch/trees/gen_trees.py`, new instances outside the vanilla theatre only):

| tier | `--scale` | new | total with Europe | file | when |
|---|---|---|---|---|---|
| A | 0.35 | 32.6k | 41.5k | 0.70 MB | first in-game test (about 1.5x CA's own test file) |
| B | 0.6 | 55.9k | 64.8k | 1.07 MB | default if A is smooth |
| C | 1.0 | 93.3k | 102.2k | 1.67 MB | upper bound tried (11x Europe) |

- **Recommendation: A, then B.** C only if the frame rate holds over jungle at the maximum zoom-out.
- Cost drivers in tier C: 41.5k boreal (Siberia, Canada), 26.6k tropical moist forest, 9.7k temperate broadleaf, 9.0k temperate conifer. Mean 243 tris per instance, because jungle clusters are heavier than Europe's 160.
- The local maxima of the tier C result (windows 10 / 30 / 60 u): 44 / 265 / 811 vs Europe 53 / 213 / 539. At the 60 u window, 811 instances x 243 = about 200k tris, which is trivial for instanced vs_3_0. Cap the density at Europe's 0.35 per u^2 in jungle if the test shows stalls.
- Memory: the exe peaks at 2.3-2.5 GB (research/00); trees add under 5 MB. Load time: the insert is O(depth) per instance, so negligible [I].
- Risks, ranked:
  1. **Look and consistency**: density and mix next to vanilla Europe need tuning. Use per-biome `F` and `RHO` in the generator.
  2. **Models the parser could not read** (grass, savannahgrass, desertrock, ustree2): unknown appearance. Do not use them until the gallery test.
  3. **Wrong height y**: floating or buried trees if the heightmap sampling is off. Use bilinear sampling and check at the coast.
  4. **Trees on settlements, roads, rivers, lakes, ports**: keep-out radius about 2.3 u for settlements and ports, and a land mask minus lakes (the generator already uses the Natural Earth land minus lakes).
  5. **Winter tint**: no snow data in the world build [I].
  6. **Visible edge at the vanilla theatre border**: some blend (reduce density 3 u inside the new side).
  7. `desertrock` and `grass` at 13 KB may be heavier than they look [?].

## 6. Groundtypes

- `regions.esf groundtypes` is a separate polygon layer with 8 vanilla types: grassland, light_forest, hills, hilly_light_forest, dense_forest and `_cold_att` variants (research/05). Its own vertex pool and `query_info`.
  In our world build `regions_world.py` stretches the vanilla layer to the box, so **outside Europe the whole world is one `grassland` area** [V from code, did not load the 108 MB ESF].
- `db/campaign_ground_types` (decoded) gives per type: movement modifier, can_ambush, heat attrition, cold attrition.

  | type | movement | can_ambush |
  |---|---|---|
  | grassland | 0.9 | no |
  | plains | 1.3 | no |
  | hills | 0.6 | no |
  | light_forest | 0.5 | yes |
  | hilly_light_forest | 0.4 | yes |
  | marsh | 0.4 | no |
  | swamp | 0.2 | no |
  | tundra | 0.8 | no |
  | desert | 0.6 | no (heat attrition) |
  | **dense_forest** | **0.0** | no |
  | **jungle** | **0.0** | no |

  `_cold_att` variants add cold attrition. The 0.0 values for dense_forest and jungle look like an unset field rather than a rule. [?] whether the engine treats it as impassable or as "unset", so do not use these two types until tested.
- The groundtypes layer **does not drive tree display**: trees come only from `campaign.rigid_trees` [V]. The two layers are independent, so Europe's tree and groundtype maps are not even guaranteed to agree.
- Pathfinding: `pathfinding.esf` is generated by `pf_gen.py` from land polygons and regions, with no reference to groundtypes (grep). The **< 2^21 word polygon budget is not affected** [V]. Groundtypes live in regions.esf, which is bounded by memory and `query_info` size (about 108 MB loaded, 1.4 GB RSS), not by that budget.
- **Recommendation**: do **not** convert in v1. Reasons: (a) it changes the strategic game (light_forest slows armies from 0.9 to 0.5 and allows ambush) over millions of km^2 of Siberia, Canada and the tropics, which is a balance decision; (b) it adds polygons and quadtree load for no visual gain; (c) battle-map effect is [?] (the battle terrain chain uses climate, section 03 and 09 of the research, not groundtypes, but it is not proven either way).
  Optional later phase: coarse (about 4 u cell) light_forest polygons for the densest taiga and rainforest patches only, with a regions.esf rebuild and the existing groundtype checks (`regions_world.py` already verifies the groundtypes quadtree).

## 7. Plan

### 7.1 Pipeline (prototype exists: `work/scratch/trees/gen_trees.py`, 9 s)
1. **Cells**: 1 u grid over the theatre (3820 x 1605). Land = `worldgeo.land()` (Natural Earth minus lakes) rasterised with `worldgeo.mask`. Skip the vanilla theatre (keep CA's trees).
2. **Biome**: world (x,z) -> lon/lat (`proj.to_lonlat`) -> RESOLVE biome raster (0.05 deg). Coast mismatches are filled from the nearest classified cell.
3. **Forest patches**: patch field = smooth noise (sigma 4 and 14 u) + 0.6 x BMNG darkness, rank-normalised, forest where `u > 1 - f_eff`, with `f_eff = F[biome] x clearing(region) x polar fade`. Calibrated `F`: temperate broadleaf 0.30 (Europe 0.17), conifer 0.5, boreal 0.35 (Europe 0.2), tropical moist 0.6, Mediterranean 0.16, savanna 0.05, steppe 0.01, desert 0.
4. **Placement**: Poisson candidates at `RHO[biome]` (0.12-0.28 per u^2, Europe patches 0.28), blue-noise thinning to min distance 0.55 u (greedy pair removal), then per-biome acceptance back to the target density. Keep out: settlements and ports about 2.3 u (to add from the build's slot list), plus roads/rivers if wanted.
5. **Model mix**: per biome table (`FAM`), small vs large cluster 75/25 (boreal 88/12), dense vs sparse by position in the patch (core -> dense). `w = U(35, 38.5)`. `y = heightmap/53.2`.
6. **Write**: vanilla header + 174 vanilla model paths in the vanilla order, vanilla instances kept, new instances appended per model, `display.write_rigid_trees` (round trip asserted: `write(read(x)) == x`).
7. **Wire-in**: `world_build.py` copies the generated file over the vanilla one (one line after `copytree`), the generator reads the settlement slots from the build.

### 7.2 To do before it is shippable (est. by our pace, scripted generation plus screenshots)
| step | effort |
|---|---|
| move prototype to `tools/gen_trees.py` (settlement/port keep-out from the real build, jungle vs indianjungle by region, HYDE or modern clearing instead of boxes, bilinear y, edge blend at the vanilla border, `--seed`, self-check in `display.py`) | 1-1.5 h |
| wire into `world_build.py`/`assemble_mod.py` and add a `trees` row to the build log | 20 min |
| in-game gallery test (all 174 models) and test A, screenshots | 1-1.5 h (4-6 game launches of 2-3 min each, mostly waiting) |
| tuning (density, mix, border blend), tier B | 1 h |
| **total** | **about 4-5 h, no human-modder time** |

### 7.3 Minimal in-game test (do not run while someone is playing)
Everything is a pack-only overlay, no world rebuild, no startpos change.
1. **Assemble**: copy `work/mods/pt_w9` (or the current frozen build) to a temp dir, replace only `campaign_maps/nap_world/display/trees/campaign.rigid_trees`, build with `packtool.py build "$G/zz_gn_world.pack"`, then `playtest.sh install`-style (needs the patched exe, `exe_patch.py patch`).
2. **Gallery test** (find the models that render wrongly): a file with exactly one instance of each of the 174 models on a 12x15 grid, spacing 3 u, on land near the start view (Britain: near London). `ntw.sh start`, `coalition`, `shot` at max zoom in/out. Check: no black or missing-texture meshes (especially `grass`, `savannahgrass`, `desertrock`, `ustree2`, `lightdeciduous`), scale looks right.
3. **Test A** (`campaign_s0.35.rigid_trees`): load to the campaign map, `shot` on the start view (Europe unchanged), edge-scroll west to eastern North America and south-west to the Amazon (screenshots at close and far zoom), `ntw.sh turns 2`. Pass criteria: no crash, turn time about 100 s as before, peak RSS under 2.5 GB, trees on land and at the right height, shroud hides them, no trees on settlements. Then repeat with tier B.
4. Clean up: `playtest.sh uninstall`.

## 8. Open questions
- Default `campaign_tree_lod_distance` and what `render_campaign_tree_imposters` draws [?].
- The 12 models my parser cannot read [?] (gallery test).
- Whether trees get a winter tint without `snow/` and `snowmask/` in the world map [I].
- The meaning of header 1024.0 and 6: the loader discards both [V], so it does not matter.
- Whether the battle terrain uses groundtypes [?].

## Files
- Prototype and stats: `work/scratch/trees/` (`gen_trees.py`, `eco_raster.py`, `density.py`, `calib.py`, `feat.py`, `area.py`, `modelstats.py`/`modelstats.txt`, `mdl.py`, `tris.py`, `models.txt`, Ghidra output `loader.c` / `ins.c` / `ins2.c`, `grun.sh` and `Refs.java`).
- Generated candidates (not installed): `work/scratch/trees/out/campaign_s0.35.rigid_trees`, `campaign_s0.6.rigid_trees`, `campaign_s1.0.rigid_trees`, plus `preview.png` and `stats.json`.
- Extracted reference data: `work/scratch/trees/x/` (models, `.tai`, the CA test file, `campaigntree.fx`, the tree db tables).
- Download: `work/geodata/ecoregions/Ecoregions2017.zip` (149 MB, CC BY 4.0).
