# 02 - NTW campaign-map files, formats and tooling

Scope: Napoleon: Total War (NTW, 2010) campaign-map data for a "whole world as a campaign map" mod.
Evidence tags: [V] verified by parsing the local install (read-only), [S] read in source code / docs, [R] reported by community (TWC/ModDB, often only via search snippets), [?] unknown / inferred.
Local install: `~/.local/share/Steam/steamapps/common/Napoleon Total War/data` (never modified).

## 1. Executive summary

1. All `.esf` in NTW (regions, pathfinding, poi, sea_grids, trade_routes, startpos) are **ABCE** (magic bytes `ce ab 00 00`), the same flavour as ETW. [V] Not the ABCA/ABCF of Shogun 2+ (no string table, no compression). Fully parseable with a ~60 line walker (section 4).
2. **RPFM cannot read NTW ESF** (it only supports CAAB/CBAB; ABCE is read as "CEAB" and rejected) and there is no `rpfm_cli` in v5. [S] RPFM is still useful for NTW pack, DB and Loc editing (`schema_nap.ron`, 7 MB, in rpfm-schemas). [S]
3. Best reusable ESF tooling: **taw/etwng** (Ruby, MIT; ABCE read/write, esf2xml/xml2esf, poi/sea_grids/pgm helpers, rigid_spline + marker tools), **Overload2664/esfpy** (Python, MIT), **aleferri/ESFEditor** (C#, MIT), **xADDBx/EditSF** (C#). Writing our own ABCE writer in Python is cheap and the safest option for a 32 MB startpos. [S][V]
4. NTW packs are **PFH0** (not PFH4, despite a README claim). 24-byte header, type 3 = mod, type 4 = movie. Mod packs are enabled by `mod <name>.pack;` lines in `scripts/user.script.txt`; movie packs auto-load; loose files under `data/` also override. [V][S][R]
5. A campaign map is a folder `data/campaign_maps/<map>/` with ~20 top-level files plus `display/` (splines, meshes, trees, textures). Europe is `nap_europe`; it is registered by name in `startpos.esf` (UTF-16 string `nap_europe` next to `eur_napoleon`, offset 733377) and by DB tables (not yet traced). [V]
6. World units: Europe theatre is **1280 x 640** units (x in ±640, y in ±320). Heightmap is **3.2 px per world unit**, bottom-left origin; supertexture 25.6 px/unit; pathfinding grid cells 2.0 units; rigid_spline coordinates = world / 40. [V]
7. **Files we can confidently generate ourselves** (format fully understood, content derivable from geodata): heightmap.tga, climate/lookup-style TGAs (as images), fogmask/snow/snowmask TGA/DDS, rigid_spline (borders/roads/rivers; trivial 'SPLN' format, verified on 379 files), bridge.markers, lighting XML, sea_grids.esf (11x6 grid of 75-unit cells, format documented in etwng). Supertexture is generatable but needs the `stpi`/tile container reversed more (tiles are zlib).
8. **Files that are generatable but with real RE risk**: regions.esf (structure fully walked, but many cross-references with startpos/DB), trade_routes.esf, poi.esf (blob decoded by taw's `poi.rb`), metadata.dat (semantics unknown), rigid_mesh coastline, world.markers (no decoder).
9. **The hard blocker is pathfinding.esf + `CAMPAIGN_PATHFINDER` in startpos** (about 93k fixed-point vertices, 375x193 grid, 22,242 grid cells; 12,683 `OBSTACLE_BASE_GRID_NODE` in startpos). Community (PietroMicca, uanime5, Taw) decoded parts but never produced a general generator; every "add a region/settlement" attempt stalled here. [R][V]
10. **Region ownership, settlements, armies, factions all live in startpos.esf** (32 MB for eur_napoleon): 41 factions, 72 REGIONs, 72 settlements, 531 characters, 87 armies/navies, plus a `CAI_WORLD` mirror (101 regions, 259 boundaries). Editing them means editing three places consistently (REGION_MANAGER, CAI_WORLD, FACTION_ARRAY). [V]
11. Whole-world mod implication: heightmap, supertexture and fogmask are resolution-scalable (they are just rasters tied to the theatre bounds), but whether the engine accepts a theatre larger than 1280x640 is **unknown** [?]. The safe path is to keep ±640 x ±320 and remap the globe into it (Distant Seas / Egypt / Italy / Spain maps show other sizes exist: 640x640).
12. Mod prior art: Darthmod/DME style (`DME/` folder in the install) edits startpos + DB; "OpenETW" and TWC "modding campaign map" threads confirm nobody has shipped a brand-new campaign_map folder with new pathfinding; closest are Distant Seas-like total conversions that reuse an existing map. [R]
13. Reuse plan: (a) etwng or esfpy for read/diff/inspect, (b) our own ABCE writer for generated esf, (c) RPFM for pack/DB/Loc, (d) own Python for TGA/DDS/spline/markers. Do not wait on any GUI tool.
14. Biggest unknowns to resolve experimentally in-game: engine max theatre size, `lookup.tga` index meaning, `metadata.dat` semantics, how new `campaign_maps/<name>` is registered via DB, grid_cells boundary byte semantics, Spain pathfinding header variant.

## 2. Coordinates, scale and pixel-to-world relation [V unless noted]

| Quantity | Value | Notes |
|---|---|---|
| Europe theatre bounds | x ±640, y ±320 (1280 x 640) | regions.esf `theatres` + `region_data vertices bounds`. TWC ETW guide quotes full map 2560 x 1280 (different convention, x2). [R] |
| Egypt / Italy / Spain | 640 x 640 (±320 square) | |
| Fixed point | i32 * 2^-20 | pathfinding vertices, poi, grid origin; sentinel -2147483647 |
| heightmap.tga | 8-bit grayscale, bottom-left origin; Europe 4096x2048, others 2048x2048 | 3.2 px per unit. px = (wx + 640) * 3.2, py = (wy + 320) * 3.2 from bottom. Values 0..226, mostly 0 (sea). |
| rigid_spline | (x, ~0, z) with x = wx/40, z = wy/40 (same sign as world y) | verified on 77 borders, 218 roads, 84 rivers |
| supertexture | Europe 32768 x 16384, 64 x 32 tiles of 512 | 25.6 px/unit (= 8 x heightmap) |
| fogmask / snow / winter (Europe) | 4096 x 2048 | same grid as heightmap |
| climate map (Europe) | 2344 x 1203 | regions.esf theatre `climate_map` |
| pathfinding grid | origin (fixed), 115 x 65 header, cell 2.0 units, 375 x 193 cells | Europe |
| sea grid | 11 x 6 cells of 75 units | covers theatre; AI sea planning only |
| metadata.dat | Europe 2048x1024, Egypt 4096x4096, Italy/Spain 2048x2048 bytes | 'MTGI' + u32 w + u32 h + 1 byte per cell |

## 3. Per-file table

Map folder: `data/campaign_maps/<map>/` (maps present: nap_europe, nap_egypt, nap_italy, nap_spain, nap_tut). `[X]` = same name prefix as the map.

| File | Purpose | Format | Known tooling | Regenerable by modders? | Source |
|---|---|---|---|---|---|
| regions.esf | Theatres, region polygons (faces, outlines, connectivity), settlement slots, roads/rail/canal links, mountain data, climate indices, quadtree query_info, ground types, map_heights, trade_nodes, bridges | ABCE | etwng esf2xml, esfpy, own walker | Yes in principle (structure walked fully, 101 regions in Europe) but cross-linked with startpos + DB | [V] |
| pathfinding.esf | Campaign pathfinding: `pathfinding_areas.vertices` (~93k fixed pairs), `grid_data` (origin, 115, 65, 2.0 cells, 375x193), `grid_cells` (22,242) with boundaries | ABCE | etwng `pgm.rb` (partial), community notes | Partially; CA generated with internal tool. No public generator | [V][R] |
| poi.esf | AI points of interest | ABCE with blob | etwng `esfxml/lib/poi.rb` | Likely (blob documented) | [S] |
| sea_grids.esf | `CAI_SEA_GRID_ROOT`: 11x6 sea grid, 75-unit cells | ABCE | etwng `sea_grids.rb` | Yes | [V][S] |
| trade_routes.esf | SPLINES, PORTS, SETTLEMENTS, ROUTES, TRADE_NODE_ROUTES | ABCE | etwng, esfpy | Yes with care (refs ports and settlements) | [V] |
| metadata.dat | Per-cell byte map; one TWC thread claims it drives auto-generated campaign battle maps | 'MTGI' u32 w u32 h + w*h bytes | none | Unknown semantics; probably generatable once semantics known | [V] / [R] |
| [X]_lookup.tga | Region index raster (colour or index per region) | TGA | none | Probably yes; mapping to region ids inconclusive | [?] |
| [X]_map.tga | Strategic map colour image (minimap/overview) | TGA | image editors | Yes | [V] |
| stratradar_*.tga | Strategic radar / overview images | TGA | image editors | Yes | [V] |
| world.markers | Placement markers (ports, battle spots, etc.) | binary | etwng `markers/` handles related files; no ETW decoder for world.markers | Unknown | [S] |
| heightmap.tga | Terrain height for campaign 3D map | TGA 8-bit grayscale, bottom-left | any | **Yes, confidently** | [V] |
| display/**/rigid_spline (borders, roads, rivers) | Splines drawn on the map | `SPLN` u32 1 u32 1 u16 namelen + UTF-16 name, u32 1, u32 npoints, npoints * 3 f32 | etwng `rigid_splines/` | **Yes, confidently** | [V][S] |
| display/**/rigid_mesh (coastline etc.) | Static meshes | starts 0x12345678 | etwng partial, Warscape mesh tools | Hard (mesh format) | [V] |
| detail/mask DDS | Terrain blend masks | DDS | any DDS tool | Yes (raster) | [V] |
| supertexture (stpi + tiles) | Terrain colour mega-texture | header `6, W, H, 512, 262144, 6, tilesX, tilesY`, zlib tiles (`78 da`) | none public | Generatable once tile index understood | [V] |
| snow / snowmask / winter | Seasonal textures and masks | TGA/DDS | any | Yes | [V] |
| fogmask | Fog-of-war base mask | TGA/DDS, 4096x2048 Europe | any | Yes | [V] |
| rigid_trees | Tree instance data | magic `G@M=` | none | Unknown | [V] |
| tradenodes / traderoutes | Visual trade node/route data (display) plus trade_routes.esf logic | mixed | etwng | Yes with care | [S] |
| bridge.markers | Bridge placement | `u16 namelen + UTF-16 name + 16 f32` repeated | etwng markers | **Yes** | [V][S] |
| arrows | Arrow meshes/markers | binary | none | Reuse CA's | [?] |
| lighting | Lighting setup | XML | text editor | **Yes** | [V] |
| campaigns/<camp>/startpos.esf | Campaign start state | ABCE, 32 MB for eur_napoleon | etwng, EditSF, esfpy | Yes, but huge and cross-referenced | [V] |

## 4. ABCE format (what NTW/ETW use) [V]

Header (16 bytes, little endian): `ce ab 00 00 | u32 0 | u32 timestamp | u32 offset of record-name table`. Root node begins at offset 16; name table lives at the offset in the header, near the end of file.

Node tags:
- `0x80` record: `u16 nameidx, u8 version, u32 abs_end` then children until `abs_end`.
- `0x81` record array: `u16 nameidx, u8 ver, u32 abs_end, u32 count`; each element = `u32 elem_abs_end` + children until it.
- Primitives `0x01..0x10`: bool, i8, i16, i32, i64, u8, u16, u32, u64, f32, f64, vec2 (0x0c), vec3 (0x0d), UTF-16 string (0x0e, `u16 len` then len code units), ASCII string (0x0f, `u16 len` then bytes), angle (0x10).
- Arrays `0x40 + type`: `u32 ABSOLUTE END OFFSET` (not a length) then packed values.
- Name table: `u16 count`, then per name `u16 len + ascii`.

Verified reference walker (Python sketch):
```python
magic,unk,ts,nameoff = struct.unpack('<IIII', d[:16]); p = 16     # root
# 0x80: ni,ver,end = struct.unpack_from('<HBI', d, p+1)
# 0x81: ni,ver,end,cnt = struct.unpack_from('<HBII', d, p+1)
# 0x0e/0x0f strings: u16 len, then len*2 / len bytes
# 0x40..0x5f arrays: u32 absolute end offset at p+1
```
Gotchas: region and settlement names are UTF-16 (0x0e); type/key names in many records are ASCII (0x0f). Absolute end offsets mean a writer must back-patch or compute sizes bottom-up (easy with a recursive builder).

Newer formats for contrast: ABCA (Shogun 2 era) and ABCF (Rome 2+) use string tables and compression; not relevant to NTW. [S]

## 5. Tools

| Tool | Link | Licence | Lang | NTW/ETW ESF? | Notes |
|---|---|---|---|---|---|
| etwng (taw) | https://github.com/taw/etwng | MIT | Ruby | Yes (ABCE, ETW/NTW) | esf2xml/xml2esf, `esfxml/lib/{poi,sea_grids,pgm}.rb`, rigid_splines, markers, pack tools; docs `docs/ESF.txt`, `ESF_TYPES.txt`, `FORMATS.txt`. Best documentation. |
| esfpy | https://github.com/Overload2664/esfpy | MIT | Python | ABCE read/write | Good base for our own writer. |
| ntw_pack_esf_tools | https://github.com/mikejaklitsch/ntw_pack_esf_tools | check repo | Python | packfile.py + esf_editor.py | README says NTW=PFH4, wrong versus install (PFH0). |
| EditSF (xADDBx fork) | https://github.com/xADDBx/EditSF | check repo | C# | Yes (ABCE + newer) | GUI tree editor; Windows/.NET (Proton or mono). |
| ESFEditor (aleferri) | https://github.com/aleferri/ESFEditor | MIT | C# | Yes | GUI. |
| RPFM | https://github.com/Frodo45127/rpfm | MIT | Rust | Packs, DB, Loc: yes (game key `napoleon`). **ESF: no** (CAAB/CBAB only; "CEAB" rejected). No `rpfm_cli` in v5. | Schema `schema_nap.ron` from https://github.com/Frodo45127/rpfm-schemas |
| PFM (Pack File Manager) | classic TWC tool | free, closed | Delphi | Yes (PFH0) | Old but reliable GUI for packs. |
| NTW_ModManager | https://github.com/bcedu/NTW_ModManager | check repo | Python | mod enable/disable | Writes user.script.txt. |
| CampaignMapToolkit | https://github.com/TW-Campaign-Map-Modding-Team/CampaignMapToolkit | check repo | ? | Targets newer TW maps; NTW coverage unconfirmed | Look for ideas, not a drop-in. |

PFH0 header: `PFH0 | u32 pack type | u32 dep count | u32 dep index size | u32 file count | u32 file index size`; index entries `u32 size + NUL-terminated path`, then data. Types: 0 boot, 1 release, 2 patch, 3 mod, 4 movie. Writing packs ourselves is ~40 lines.

## 6. Packs, load order and mod enablement

- Install has `data.pack`, `boot.pack`, `DME_campaign.pack`, `local_en_patch.pack`, all `PFH0`. [V]
- Type 3 (mod) packs must be listed in `<prefix>/AppData/Roaming/The Creative Assembly/Napoleon/scripts/user.script.txt` as `mod <name>.pack;` (one per line; later lines override earlier). Local Proton prefix `compatdata/34030` has no such file yet. [V][R]
- Type 4 (movie) packs in `data/` load automatically in alphabetical order after the base packs; popular for content-only mods. [R]
- Loose files under `data/campaign_maps/` and `data/campaigns/` are honoured (TWC "mod-foldering" thread; snippet only). [R]
- Override rule: later-loaded pack wins per file path; a new map folder needs no collision if named uniquely, but it needs DB registration (see open questions).
- There is a `DME/` folder with `dme_log.txt` (Darthmod Empire style), useful as a real-world mod layout reference. [V]

## 7. startpos.esf structure (eur_napoleon) [V]

Path: `campaigns/eur_napoleon/startpos.esf` (32,002,498 bytes).

```
CAMPAIGN_STARTPOS
  CAMPAIGN_PREOPEN_MAP_INFO        FACTION_INFOS (41), REGION_OWNERSHIPS_BY_THEATRE (72)
  CAMPAIGN_ENV
    CAMPAIGN_MODEL
      WORLD
        FACTION_ARRAY (41)         each: CHARACTER_ARRAY, ARMY_ARRAY (87 armies/navies total; 531 characters)
        REGION_MANAGER             72 REGIONs, each with slots and a settlement (72 settlements)
      CAI_INTERFACE
        CAI_WORLD                  mirror: 101 CAI_WORLD_REGIONS, 259 region boundaries, settlements
      CAMPAIGN_PATHFINDER          grid nodes incl. 12,683 OBSTACLE_BASE_GRID_NODE
      CAMPAIGN_TRADE_MANAGER
```
- Map binding: UTF-16 strings `eur_napoleon` and `nap_europe` appear together at offset 733377 inside the preopen/map info (campaign name -> map folder). [V]
- Region ownership: `REGION_OWNERSHIPS_BY_THEATRE` (who owns each region at start) and `REGION_MANAGER > REGION`. Faction capital/leader/army placements are inside each `FACTION_ARRAY` element. Changing owner means editing both places plus CAI_WORLD.
- Regions in startpos (72) are the playable subset; regions.esf has 101 (extras are minor/sea/cosmetic). Count mismatch is normal. [V]
- Known editing practice: EditSF/etwng XML round-trip; DME and Darthmod edit startpos by hand after DB changes; adding a brand-new region/settlement is the part that fails because of pathfinding and CAI mirrors. [R]
- Practical approach for the mod: generate startpos by transplanting a trimmed copy of the vanilla tree (keep factions/characters, replace region list) rather than synthesising from scratch.

## 8. Campaign pathfinding: reverse-engineering notes

- Data lives twice: `pathfinding.esf` (static map: area vertices, grid, grid cells, boundaries) and `CAMPAIGN_PATHFINDER` in startpos (runtime nodes, obstacles). They must agree. [V]
- `pathfinding_areas.vertices`: ~93k fixed-point (2^-20) coordinate pairs, with `-2147483647` as separator/sentinel between polygons. `grid_data`: origin, 115, 65, cell size 2.0 units, 375 x 193 cells (Europe). `grid_cells`: 22,242 entries, each with boundaries (byte flags; semantics not decoded). [V]
- Spain pathfinding.esf has a header variant not yet understood. [V]
- Community: TWC threads by PietroMicca, uanime5, Taw discuss decoding; consensus was that adding/relocating settlements and regions requires regenerating pathfinding, which nobody released a tool for. Taw's `pgm.rb` handles parts. [R][S]
- Strategy options: (a) keep vanilla pathfinding topology and remap geography onto it (zero RE, low fidelity); (b) rasterise our land/sea mask into the same grid_cells layout and infer boundary bytes by comparing against vanilla Europe (needs experiments); (c) hybrid: generate polygons from land mask and test in-game for crash/stuck.
- Validation idea: write a reader that renders pathfinding_areas polygons over heightmap.tga to confirm alignment, then change one cell and observe in-game.

## 9. Open questions

1. Does the engine accept theatre bounds larger/other than ±640 x ±320? (Egypt/Italy/Spain prove 640x640 works.)
2. How is a new `campaign_maps/<name>` registered (DB tables such as campaign_maps / campaigns / campaign_map_*; not traced)? Needs RPFM DB inspection of `data.pack` using `schema_nap.ron`.
3. `lookup.tga`: what do pixel values encode (region index, region key hash, colour)? Mapping attempt was inconclusive.
4. `metadata.dat` ('MTGI'): semantics of the per-cell byte (battle terrain type? ground type?).
5. `grid_cells` boundary byte semantics; Spain header variant.
6. `world.markers` layout (no ETW decoder exists).
7. `stpi` supertexture tile index (offsets) and tile pixel format after zlib; mip handling.
8. rigid_mesh coastline: required, or can it be omitted/reused from vanilla?
9. Are PFH0 mod packs able to add whole new files under `campaign_maps/` without any script entry beyond `mod x.pack;`? (Likely, untested.)
10. Several TWC threads (NTW mapping guide 414986, The Campaign Map 686835, mod-foldering 275922, startpos analysis 272139/339181) were not archived; only search snippets seen, so claims from them are [R].

## 10. Sources

- Local install parsing (python, read-only): all five campaign maps, `eur_napoleon/startpos.esf`, pack headers.
- RPFM source: `rpfm_lib/src/files/esf/mod.rs`, `games/supported_games.rs`, `games/pfh_version.rs`, docs/supported-games.md.
- taw/etwng: README, LICENSE (MIT), `docs/ESF.txt`, `ESF_TYPES.txt`, `FORMATS.txt`, `rigid_splines/*`, `markers/*`, `esfxml/lib/*.rb`.
- TWC "Guide to the ETW map" (Wayback 2025-07-06), TWC "modding campaign map" 548643 (Wayback), ModDB OpenETW (Wayback).
