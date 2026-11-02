# 07 - Campaign map `display/` formats (spec + generator requirements)

Ground truth: the vanilla files under `data/campaign_maps/{nap_europe,nap_egypt,nap_italy,nap_spain,nap_tut}/display/`.
Tool: `tools/display.py` (read + write for every binary format below; `python tools/display.py` runs the
round-trip self-check). Tags: [V] verified on local files by the self-check or a scripted test, [I] inferred, [?] unknown.
Public reference used: taw/etwng (MIT) `rigid_splines/`, `markers/`, `etwconv/lib/rigid_mesh.rb`. etwng's
world.markers parser targets a different (ETW) layout and does not parse NTW files, so that layout was reversed here.

## 1. Coordinate conventions

| item | convention |
|---|---|
| world box | nap_europe (-640,-320)..(640,320); egypt/italy/spain (-320,-320)..(320,320) |
| 3D axes | x = east, y = up, z = north. z has the **same sign** as world y [V: coastline, trees and overlays all line up with the supertexture water mask only at +z; the -z score is far worse] |
| units | world units everywhere, **except** `rigid_spline` and `bridge.markers`, which use world/40 [V: river splines line up best with the river alpha at a scale of 40; 38 and 42 score worse] |
| rasters | every geographic raster covers the **whole world box**, edge-aligned. Row 0 is north as Pillow returns it (DDS is stored top-down; the TGA heightmap is stored bottom-up, and Pillow flips it). Pixel = ((x-xmin)*W/ww, (ymax-y)*H/wh): `display.world_to_pixel` |
| texel densities (Europe) | heightmap, fogmask, winter: 3.2 px/unit. Supertexture: 25.6 px/unit (32768 px / 1280 units; Egypt 16384/640, the same). campaign_detail_mask: 0.8 px/unit |

## 2. Binary formats

All values are little-endian. `str` = u16 character count followed by UTF-16LE text, with no terminator.

### 2.1 rigid_spline (borders/, roads/**, rivers/, traderoutes/) [V 903/903 files byte-exact]
```
"SPLN"  u32 version=1  u32 nsplines
nsplines x { str name ; u32 flag (always 1) ; u32 npts ; npts x f32[3] (x, h, z) }
```
- x and z are world/40. h is a constant height offset per layer: borders 0.0112, roads 2.8e-4, rivers 0, trade routes 0.127.
- Names: `border:<region>:<n>`, `road:<region>:<n>`, `river:<nn>`, `Sea:<n>` (trade_routes), and similar names in land_trade_routes.
  Each border and road file holds one spline. The traderoutes files hold hundreds: trade_routes has 299 `Sea:*` splines, which presumably mirror `trade_routes.esf` SPLINES [I].
- Points outside the world box are tolerated: Egypt `rivers/01` lies at x=-781 [V].
- Writer helper: `spline_from_world(name, xy_world, height)`.

### 2.2 bridges/bridge.markers [V 5/5]
```
repeat to EOF { str name ("bridge:<region>:<n>") ; f32[16] 4x4 row-major matrix }
```
Rows 0-2 hold the rotation (row 1 = up), and row 3 = (x/40, h, z/40, 1). Europe has 149 bridges.

### 2.3 coastline/coastline_groupN.rigid_mesh [V 8/8]
```
u32 0x12345678
u32 nstreams ; nstreams x { u8 flag ; str (empty) }   -- always [(1,''),(1,''),(1,''),(0,''),(0,'')]
u32 0
u32 nverts ; nverts x f32[20]
u32 nidx   ; nidx x u32  (triangle list)
```
Vertex columns used: 0=x, 2=z (world units), 6=s/len, 7=0 on the shore / 1 offshore, 18=s (arc length), 19=strip length.
All other columns are 0. The geometry is a **ribbon exactly 1.0 world unit wide**, laid along every shoreline on the sea side. The vertices
come in pairs (shore, offshore), and each segment uses two triangles (a+2,a+3,a),(a+3,a+1,a). Europe has 312 strips, 6426 verts and one group;
Egypt has 4 groups. Generator: `coastline_mesh([shore polylines])` (the offshore side is to the left of the travel direction, so reverse a strip if it comes out wrong).

### 2.4 world.markers [V 5/5]
```
str "BASE_MARKER_REPOSITORY" ; handle(0x0009D9BB) ; u32 1 ; u16 ngroups=3
group x3 { handle(id) ; str class ; handle(id) ; u32 version ; u32 n ; n x record ;
           if n>0: u16 nnames ; nnames x { u16 1 ; str name ; u32 k ; k x u32 record_index } }
handle = 12 zero bytes + u32 id    (ids 0x2A5DF201/02/03)
```
| class | ver | record |
|---|---|---|
| CAMPAIGN_DISPLAY_EMITTER_MARKER | 2 | u32 ptr, f32 x, f32 z, u32 flag (low byte 0/1/0xFF, upper bytes are garbage) |
| CAMPAIGN_DISPLAY_MODEL_MARKER | 2 | u32 ptr, f32 x, f32 z, f32 rot_rad, u32 flag |
| CAMPAIGN_DISPLAY_OVERLAY_MARKER | 5 | u32 flags (1,2,4,6,7,15), str texture_set, u32 nv, nv x f32[6] (x, y=0, z, u, v, alpha), u32 ni, ni x u32 (always 0..ni-1) |

- `ptr` looks like a serialized heap pointer (0x10CB9714 and similar, different per map), so it is probably ignored [I].
- Emitter names are particle templates (`campaign_ambient_clouds`, `_heathaze`, `_dust`, `_snow_light`) mapped to record indices.
  Model names: Europe has `arrows_eu` at (0,0) with rot -pi/2. Egypt has the pyramids.
- Overlay names are **region slot names** (`eur_normandie:SETTLEMENT`, `eur_wales:TOWN`, `eur_brandenburg:04`, `eur_spain:PORT1`).
  Each one maps a slot to the ground-decal mesh around it, and the texture sets are `europe`, `europesettlement`, `woodland`, `horseunderlay`, `vineyardsunderlay`
  (Egypt adds `egyptfarm`). Some overlays have no name. Europe: 281 overlays and 275 names.
- An empty group has **no** name table. Vanilla Spain has 0 emitters, and Italy/tut have 0 models. `empty_world_markers()` builds an all-empty file [V parses, untested in game].

### 2.5 trees/campaign.rigid_trees [V 5/5]
```
"G@M=" u32 1 ; f32 1024.0 ; u32 6 ; u32 nmodels (174 in every map)
nmodels x { str model_path ; u32 ncells (always 1) ;
            ncells x { u32 n ; f32[6] bbox (always -1,-1,-1,1,1,1) ; n x f32[4] (x, y, z, w) } }
```
x and z are world units. y is the ground height (0..2.5). w is in [35.0, 38.5] with unknown meaning (scale or a seed?) [?]. Every map lists the same 174
`RigidModels/CampaignTrees/*.rigid_model` paths in the same order, and only the instance lists differ. Europe has 8903 instances in 78 models, and
99.99 % of them sit on land. Meaning of the 1024.0 and the 6 is [?], so keep both.

### 2.6 supertexture/supertexture.stpi + .stpd (terrain colour mega-texture) [V stpi 5/5; Europe stpd re-serialised byte-exact]
stpi:
```
u32 6 ; u32 W ; u32 H ; u32 512 (tile) ; u32 262144 (tile bytes) ; u32 nlevels=6
nlevels x { u32 tx ; u32 ty ; tx*ty x { u32 offset ; u32 csize ; u32 usize=262144 ; u32 id ; u32 pad } }
u32 1
```
- Europe is W=32768 and H=16384, with levels 64x32, 32x16, 16x8, 8x4, 4x2, 2x1 (2730 tiles, 125 MB). Egypt/Italy/Spain are 16384^2, with levels 32x32 down to 1x1.
- Level L is a full mip pyramid of the **whole world box**: level-L texel = 2^L level-0 texels. Tiles are row-major and **row 0 = north**.
- `id` is a running 1-based counter over all levels. `pad` has low byte 0. Its upper 3 bytes are FF FF FF on level 0 and garbage on the others. The writer uses 0xFFFFFF00.
- The stpd is the concatenation of tiles in index order (offset = running sum). Each tile is **8 chunks** of `{u32 csize ; u32 usize=32768 ; zlib}`,
  and each chunk holds 64 texel rows. The decompressed tile is **DXT5 (BC3) 512x512, no mips**.
- RGB = the painted terrain colour, including the parchment and wood frame outside the playable area. **A = water mask**: 255 for sea, lakes
  and drawn rivers, 0 for land. It matches the coastline mesh to within about 1.5 px at level 3.
- zlib: CA used level 9 (header 78 DA), but only about 55 % of chunks re-compress identically with Python's zlib. Byte-exact round trip therefore keeps
  the raw chunks, and any valid zlib should load [I].
- Writer: `write_supertexture(stpi, stpd, W, H, tile_fn, nlevels)` streams one tile at a time. `tile_fn(level,i,j)` returns a 512x512 RGBA image.
  `tile_fn_from_image(img)` is a convenience adapter for sources small enough to hold in RAM. `decode_tile`, `read_level_image` read tiles back.

### 2.7 DDS / TGA rasters
| file | Europe size / format | maps to world box? | notes |
|---|---|---|---|
| heightmap/heightmap.tga | 4096x2048, TGA type 3, 8 bpp, bottom-left origin (Egypt adds a TGA2 footer) | yes, 3.2 px/unit | 0 = sea **and** flat lowland; only 13 % of land is >0 |
| fogmask/fogmask.dds | 4096x2048 L8 (pf 0x20000), no mips | same grid as heightmap [I] | content is soft cloud blobs, not geography; Egypt and Spain have none |
| snow/winter.dds | 4096x2048 L8, no mips | yes [V: snow only on land when read north-up] | Italy 2048^2 L8 with mips, Spain 1024^2 DXT1; Egypt has none |
| snowmask/campaign_snow_mask_{summer,winter}.dds | 2048x1024 DXT5 + mips | **no** | identical in Egypt and Europe, and shows an Empire-style world (N. America, Siberia), so it is an ETW leftover; Italy/Spain have none |
| detail/campaign_detail_mask.dds | 1024x512 DXT3 + mips (Egypt 512^2 ARGB) | yes, 0.8 px/unit | A = water mask; RGB = detail-texture weights |
| detail/campaign_detail.dds, campaign_rocks.dds | 1024^2 ARGB8 / 512^2 DXT5 | no (tiling) | reuse |
| rivers/textures/*.dds, arrows/*.dds | small DXT1/5 | no | shared across maps |

`write_l8_dds` (fogmask/winter header) and `write_l8_tga` (heightmap) reproduce the vanilla files byte-exact [V].

### 2.8 Other files
- `environment/*.lighting`: XML `<SCENE_ENVIRONMENT>` (sun direction, ambient cube, HDR) for each season. Not tied to the world box, so copy or tweak it.
- `arrows/arrows.rigid_model`: CA rigid_model with small local geometry (|coord| < 16). It is placed by the world.markers MODEL marker. Not decoded, so reuse it.
- `tradenodes/all_tradenode.rigid_model`: byte-identical in all 4 maps, so reuse it.
- `README.txt`: CA note saying shared data may live higher up the folder tree.

## 3. Which files depend on the world-box size

| file | tied to box? | when the world is enlarged |
|---|---|---|
| supertexture stpi/stpd | **yes** (W,H = box * 25.6 at vanilla density) | regenerate. W/H should be multiples of 512*2^(nlevels-1). Whether the engine derives texel density from W/box or assumes 25.6 is [?]: keep 25.6, or test |
| heightmap.tga | yes (3.2 px/unit) | regenerate at box*3.2 (the other lane owns the semantics) |
| fogmask.dds, winter.dds, campaign_detail_mask.dds | yes (cover the box) | regenerate at the same ratio, or omit (see 4) |
| coastline, borders, roads, rivers, traderoutes, bridges, world.markers, trees | absolute coordinates only | regenerate from geodata in the new coordinates; the files have no size field |
| snowmask, detail, rocks, river textures, lighting, arrows, tradenode | no | copy vanilla |

## 4. What can be omitted or left empty (evidence from vanilla maps; none of this is tested in game)
- `traderoutes/`: absent in Egypt, Italy and Spain [V].
- `fogmask/`: absent in Egypt and Spain. `snow/`: absent in Egypt [V].
- `snowmask/`: absent in Italy and Spain [V].
- `arrows` model marker: Italy and tut have the file but 0 MODEL markers [V].
- world.markers groups may be empty (Spain 0 emitters, Italy 0 models) [V]. An all-empty file loses settlement ground decals and clouds only [I].
- `trees`: an instance list can be empty (96 of 174 models are empty in Europe). The file probably cannot be removed, so write the 174 names with no instances to disable trees [I].
- `bridge.markers`: needed only where roads cross rivers [I].
- These should be treated as required (they are present in every map): supertexture, heightmap, coastline mesh (at least one group), borders, environment, detail.

## 5. What a generator must produce for a new map (world box (xmin,ymin)..(xmax,ymax))
1. **supertexture**: W=(xmax-xmin)*25.6 and H=(ymax-ymin)*25.6, both rounded to multiples of 512*2^(n-1). Paint RGB terrain and set A=255 on water.
   Stream it with `write_supertexture`. Size estimate: a 2560x1280 world gives 65536x32768, about 10.9k tiles and 2.9 GB of DXT5 before zlib.
   That is still inside the u32 offsets, but a 32-bit engine streaming a file that size is a real risk [?]. Fallback: a lower density, if the engine supports it [?].
2. **heightmap.tga** at box*3.2, written with `write_l8_tga`. **fogmask/winter**: L8 DDS at the same grid, or omit them.
   **campaign_detail_mask.dds** at box*0.8, with A = water. No writer exists for this file yet: write DXT3/ARGB with Pillow/magick.
3. **coastline_group0.rigid_mesh** from shoreline polylines (`coastline_mesh`); several groups are allowed (Egypt has 4).
4. **borders/<region>_<n>.rigid_spline** for each region outline piece, named `border:<region>:<n>`. **roads/** use `road:<region>:<n>`, and
   **rivers/NN.rigid_spline** use `river:NN`. All coordinates are world/40 (`spline_from_world`).
5. **bridges/bridge.markers** where roads cross rivers: a 4x4 matrix with translation /40.
6. **world.markers**: start from `empty_world_markers()`. Optionally add OVERLAY decals keyed by `region:SLOT` names (these must match regions.esf slot names)
   and EMITTER cloud points.
7. **trees/campaign.rigid_trees**: copy the 174 vanilla model names and fill the instances (x, ground_y, z, w in 35..38.5) from a land-cover layer.
8. Copy as-is: environment/, detail/campaign_detail.dds and campaign_rocks.dds, rivers/textures/, snowmask/, arrows/, tradenodes/.

## 6. Open questions
- Whether the engine accepts a world box or supertexture larger than Europe's (the supertexture is 32768x16384, 2730 tiles) is unknown. An in-game test is needed.
- Whether supertexture texel density is fixed at 25.6/unit or derived from W/H and the world box is unknown.
- The meanings of: rigid_trees w and the header 1024.0/6; overlay `flags`; the stpi first header field (6, equal to nlevels in every map?); whether the record `id` is used at all.
- The semantics of the heightmap (most land reads 0) belong to the heightmap lane; a land/sea mask is better taken from the supertexture alpha.

## 7. Vanilla supertexture is framed parchment (2026-10-18)
Vanilla nap_europe paints its map only inside a torn parchment frame: about 24% of VT is parchment, and the painted edge is
burnt dark 6-9 u inward. World bakes keep vanilla only inside the painted mask (connected non-parchment area at level 2,
holes filled, trimmed `EDGE_TRIM` u from the torn edge) and generate everything else, feathered 3 u from vanilla's edge
colour. Vanilla sea is shaded by distance from coast, not depth: a halo of about (68,90,93) fading to (29,41,43) by about
20 u. The generated sea copies this so the seam doesn't show (`tools/bake_terrain.py`).
