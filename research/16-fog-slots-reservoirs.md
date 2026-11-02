# 16 - Fog of war, minor slots, reservoirs, walkable lakes, rivers

Read-only research (2026-10-21) on the w9 playtest build `work/world/pt_w9`, the vanilla loose
mp_eur_napoleon startpos, and the user's own Russia saves (Proton prefix, `auto_save.save` = turn 1,
`quick_save.save` = turn 6, 2026-10-20). Scripts and outputs are in `work/scratch/fog/`.

Tags: **[V]** verified from files or saves, **[I]** inferred.

---

## 0. Summary

| Question | Answer |
|---|---|
| Why is Siberia dark? | Every new region's **REGION LINE_OF_SIGHT bitmap is Eurasia's copy of Ireland's**, shifted to the new settlement. Own territory is lit by that per-region bitmap, not by circles around slots. [V] |
| Where does the vanilla radius come from? | Not from the db or the exe. In the startpos, each REGION's LOS = its region polygon **grown by 10 u**, and each SETTLEMENT's LOS is a disc of radius about 5-6 u. Only characters take their radius from the db (`agents_tables.line_of_sight`, in world units). [V] |
| Do farms, resource slots, towns or ports reveal fog? | **No.** All 337 vanilla REGION_SLOT LOS records are off, and so are all 72 road and 72 fort slots. The same holds in our build and in the turn-6 save (657 slots, 0 on). [V] |
| Cheapest fix | Rewrite each new REGION's LOS as region polygon + 10 u, and centre its SETTLEMENT disc. Only startpos.esf changes, and it takes about 1 minute as a post-pass. [V recipe, I in game] |
| Reservoirs | All 230 are holes inside the filled land, so region polygons and pathfinding are unaffected. A reservoir filter changes only the terrain bake: heightmap, supertexture and detail mask. That is a display-only fix of about 10 minutes, with no world_regions build. Caution: `Reservoir` also covers natural lakes that were later dammed (Il'men, Mjøsa, Zaysan, Oulujärvi...). [V] |
| Walkable lakes | Lakes are **land inside the region's passable area 0**, never holes: three steps fill them. Making them impassable is a geometry-stage change, i.e. a full rebuild. It is a different fix path from the reservoir filter, which only shares the lake list. [V] |
| No river lines outside Europe | `display/rivers/*.rigid_spline` are vanilla's 84 files, copied byte for byte. No tool generates rivers, and the bake paints no river water mask. [V] |

---

## 1. Q1: where the sight radius comes from

### 1.1 LINE_OF_SIGHT records in the startpos [V]

Record = `(bool on, xy min, xy max, QUAD_TREE_BIT_ARRAY)`. The bit array uses 1.25 u cells counted from
the world-box min, with row index growing with y. The engine struct is: +0 min, +8 max, +0x10 bit array,
+0x28 bool. It is loaded by `FUN_00af88f0` and saved by `FUN_00afd8e0`; the name getter is `FUN_00b026b0`.
In the REGION object it sits at +0x1f0, read in the REGION loader `FUN_00a45950`, which also references
`start_pos_regions_rebel_faction_name_%S%S`. (Ghidra output: `work/scratch/fog/los_callers.c`, `los_owners.c`.)

Survey of the vanilla mp_eur startpos (`los_survey.py`, `region_los.py`, `los_vs_poly.py`):

| Owner of the LOS record | Count / on | Shape | Fit |
|---|---|---|---|
| REGION (REGIONS_ARRAY) | 72 / 45 on | region polygon **buffered by 10 u** | IoU 0.95-0.98 at d = 10.0 u, best of 3..15 u in 0.5 u steps (Ireland, Moscow, France, Hungary, Novgorod, Corsica, Gibraltar) |
| SETTLEMENT residence | 72 / 33 on | 11.25 u box (9x9 cells), 69 cells: a disc of r ≈ 5-6 u | IoU 0.90-0.96 at r = 6 |
| CHARACTER | 539 / 64 on | box = 2 x `agents_tables.line_of_sight` + 1.25 | General / colonel 15 -> 31.25, admiral 20 -> 41.25, 10 -> 21.25 |
| REGION_SLOT (towns, ports, resources) | 337 / **0** | - | - |
| ROAD_SLOT, FORTIFICATION_SLOT | 72 + 72 / **0** | - | - |
| TRADE_SEGMENTS | 766 / 766 | small boxes along routes | (trade-route reveal) |

The REGION LOS is **on exactly for the regions of the 5 shroud factions** (France, Britain, Prussia,
Austria, Russia) and off for all minors: Denmark, Sweden, Spain, Ottomans and the rest. [V]

The user's screenshots match this. Vanilla Russia is fully lit. In the screenshots of Volga-Urals and the
North Caucasus, the lit patches are rounded Ireland-shaped blobs that sit at the settlement and spread west
from it, because Dublin is on Ireland's east coast. [V data, I visual match]

### 1.2 What our build does [V]

`land_probe.startpos` clones eur_ireland's REGION, and `world_regions.startpos_regions` moves its two LOS
records by the template offset rounded to 10 u (`shift_los`). Results in pt_w9 (`save_los.py`, `los_vs_poly.py`):

- 194 new REGION LOS records = **2931 cells each, which is exactly Ireland's**, all switched on. For
  asi_volga_urals (18 556 cells of land) the IoU with polygon + 10 is 0.14; for asi_olonets it is 0.35.
- Render: `work/scratch/fog/russia_los.png` shows Russia's REGION LOS union over the region outlines.
  Vanilla Russia is covered, and each new region (Olonets, Vologda, Russian North, Volga-Urals,
  West Siberia, North Caucasus) gets one Ireland blob.
- The SETTLEMENT disc moves by D rounded to 10 u while the settlement moves by exactly D, so the disc
  can sit up to 5 u off-centre (IoU 0.31 for Volga-Urals).

### 1.3 Does the engine recompute it? [V for stored state, I for mechanism]

- In the turn-6 save (`quick_save.save`, calendar 24,6,6), all 194 new REGION LOS records are still the
  2931-cell Ireland clone. So the engine never rebuilds REGION LOS from the polygon on load or per turn.
- Two vanilla regions changed owner by turn 6: eur_tyrol (Austria to France) and eur_gibraltar
  (Britain to Spain). Their REGION LOS went from on to **off**, while the settlement disc stayed on
  (`los_diff.py`). So a capture clears the region reveal and nothing re-derives it, at least by the save
  point. [V]
- CAMPAIGN_SHROUD holds only the explored arrays. Arrays 0 and 1 are identical and array 2 is empty; in
  the save there is only one, the player's. "Currently visible" is computed live from the LOS records and
  is not saved. [V layout, I meaning]
- I found no db column and no exe string for a region or settlement sight radius. The 10 u margin and the
  5-6 u disc are baked by CA's tool into the startpos. [V db and strings; I that no exe routine
  generates them, since I did not search for one beyond the serializer]

### 1.4 How it can be raised

| Scope | Lever | Notes |
|---|---|---|
| **Per region** | REGION LOS bitmap: any shape, e.g. polygon + 10 u like vanilla, or more | The fix. Only startpos. [V format] |
| Per settlement | SETTLEMENT LOS disc: any radius | Small help only. Centre it exactly. |
| Global (characters) | `agents_tables.line_of_sight` (world units, per agent type) | Changes every army and agent ring, the AI's included. [V] |
| Per character | `line_of_sight_mod` effect (bonus value `line_of_sight_extension`): traits (Scout +5/+10, Grand Armée +50), ancillaries (+10), tech `admin4_semaphore_lines` (+10) | Character effects, probably percent. [V rows, I unit] |
| Per building | none in vanilla: `building_effects_junction` has no sight effect | `line_of_sight_mod` on a building would most likely buff characters, not reveal land. [I] |

Side effects [I]:
- AI: the CAI has its own `CAI_VISIBILITY_ANALYSIS_*`, and scripts call `disable_movement_for_ai_under_shroud`.
  Lighting the player's own regions only shows the player what vanilla already shows in Europe, enemy
  armies inside own territory included.
- Performance: polygon + 10 for 194 regions is about 1.1M cells, roughly 20k 8x8 quadtree leaves. That
  adds well under 1 MB to the startpos and is a cheap union per faction.
- Note for the faction carousel: vanilla minors such as **Denmark** (eur_denmark, eur_norway) have REGION
  LOS **off**, so a made-playable Denmark campaign starts with dark own territory. The same pass should
  switch on the regions of every playable faction. [V data, I in game]

### 1.5 Fix recipe

For every REGION whose owner can be a player (simplest: all regions), set the LOS to
`(True, bounds min, bounds max, qtba_encode(3072, 2048, cells))`, where `cells` = the 1.25 u cells whose
centre lies in `region polygon (all areas, from regions.esf) .buffer(10)`. Snap the bounds outward to the
1.25 grid, like vanilla's boxes. Set the SETTLEMENT LOS to a 9x9-cell disc centred exactly on the
settlement. All helpers exist (`campaign_misc.qtba_encode`, `regions_model.area_polygons`). Check: IoU
against `polygon.buffer(10)` >= 0.95 for every region, as vanilla scores. Captured regions will still go
dark after capture, as in vanilla (1.3).

---

## 2. Q2: minor slots

### 2.1 (a) Which slots reveal fog [V]

None. Slot types (`slots_tables`): settlement_N_slot, settlement_road / fortification / prestige,
town-commercial / industrial / intellectual / UNUSED, port, and the resource slots wheat, horses,
sheep (is_farm), iron, gold, timber, wine. Every REGION_SLOT, ROAD_SLOT and FORTIFICATION_SLOT
SIEGEABLE_GARRISON_RESIDENCE LOS is off in:
- the vanilla startpos (337 + 72 + 72);
- pt_w9 (657 + 266 + 266);
- the turn-6 save, where the AI had built ports and recruited.

The generated ports also have LOS off (`port_probe` asserts it). The circles the user saw are the Ireland
blobs (1.2) and character rings (1.1).

**So adding farms or resource slots will not light Siberia.** The cheapest fog fix is 1.5.

### 2.2 (b) How the build creates slots now [V]

- New regions get only `road:0`, `settlement_1_slot:1` and `fortification:2`. These come from
  eur_ireland's template (`land_probe.startpos` keeps those 3; `land_probe_b.place_slots`, placed by
  `world_regions.place_settlements` in the geometry stage).
- Stage `p` (`port_probe.add_ports`, after `pre`) appends one port slot per regions.json port.
- No town or resource slots, and no `campaign_map_slots` rows for new regions.

### 2.3 (c) What N extra slots per region would take

This follows the port_probe recipe, which is the only proven slot-adding path [V recipe, I for non-port kinds]:

| File | Change |
|---|---|
| regions.esf | append a `slot_descriptions` entry (key `<type>:<region>:<name>:<idx>`, idx = list position; model, angle, footprint) |
| pathfinding.esf | carve the footprint as **kind-7 slot land** of the region's domain ("every slot footprint is kind 7"), re-derive middle20/contact masks round it, then `pf_check` 0. No new domains; about 75 polygon words per slot (ports: +9,486 words for 126) |
| startpos | REGION_SLOT with fresh handles, owner residence, BUILDING (key, owner faction), type flags (resource `(1,0,False,0,2,0/-1,0)`, town `(0,1,True,1,1,-1,2)`), position |
| CAI | CAI_BUILDING_SLOT (kind 5 wheat/wine, 6 pasture/timber, 4 gold/iron, 2 town), CAI_REGION_SLOT, CAI_REGION slot list; ids from CAI_CENTRAL_BDI_POOL |
| db / loc | `campaign_map_slots` (resource) or `campaign_map_towns_and_ports` (town) row + onscreen loc |
| trade, sea_grids, poi | none for inland towns and resources [I] |
| Limits | vanilla goes up to 18 slots per region (eur_england), mean 6.7; no hard limit known; word budget 1.618M of 2^21 = 479k spare |

Rebuild: as a new post stage after `p` with its own cache entry, about 90 s plus its check. Folded into
`pre`, it is the 10-minute path of 5.

### 2.4 (d) Density

Europe has 121,484 u² of land and 337 map slots, i.e. **one slot per 360 u²**. At that density
asi_volga_urals would need 80, asi_west_siberia 146 and asi_east_siberia 555. All 194 new regions together
would need about 4,400 slots and about 330k words. That is pointless for fog, given 2.1. If slots are
wanted for the economy, a sane rule is one town per real 1805 city (Kazan, Perm, Tobolsk, Tomsk, Irkutsk,
Yakutsk, Orenburg, Astrakhan...) plus 1-3 resource slots per region from the ecoregion, capped near 12.
This is a separate gameplay task.

---

## 3. Q3: reservoirs, walkable lakes, rivers

### 3.1 Who reads the lakes [V]

| Reader | Use of `ne_10m_lakes` | Effect of a reservoir filter |
|---|---|---|
| `worldgeo.land()` (cache `work/world/land.wkb`) | land minus lakes | the input below |
| `regions_world.prep_land` | `Polygon(p.exterior)`: **lake holes filled** ("lakes are filler land") | none: all 230 reservoirs are pure holes |
| `pf_gen.land_fixed` (cache `pf_land.wkb`) | theatre minus the ocean of the **filled** land | none |
| `world_regions` geometry / pathfinding | uses ZREGIONS / ZPF and the admin-1 features, never worldgeo | none |
| `bake_terrain`: `coast_dist` (cache `coastdist.npy`), `bake_heightmap` (sea = 0), supertexture alpha + colour, `bake_detail` water mask, check | `worldgeo.mask(land())` | **these change** |
| `geo.land_mask` (geo.py:113) | paints lakes 0 | dead code: no caller |
| coastline mesh | vanilla `coastline_group0.rigid_mesh`, copied byte for byte | none |

`work/scratch/fog/reservoirs.py` reports 230 reservoirs (2,932 u²), **0 that are not a hole of the filled
land, and 0 that touch the ocean**. The largest are Rybinsk 125, Smallwood 121, Samara 112, Vilyuy 108,
Volta 87, Bratsk 81, Zaysan 71, Tsimlyansk 63, Kariba 53, Kakhovka 42, Nasser 42 and Volgograd 30 u².
Reservoirs under vanilla's painted mask keep vanilla's pixels anyway.

**Display-only fix: yes.** Filter in `worldgeo.land()`, delete `work/world/land.wkb` and
`work/world/terrain/cache/coastdist.npy`, then run `bake_terrain.py heightmap`, `supertexture`, `detail`
and `check`. Copy the 3 rasters into `work/mods/world_m1/.../display`, then `assemble_mod.py pt_w9` and
pack. BMNG colour is already land under the reservoirs: `bmng_prep` fills bluish-dark water pixels.
pf_gen and regions_world give the same result if ever rerun (pure holes).

**Caveat [V]:** `featurecla == 'Reservoir'` also covers natural lakes that were dammed later. The `year`
field is the dam year: Il'men (Volkhov, 1926), Kubenskoye (1917), Oulujärvi (1950), Zaysan (Bukhtarma,
1960), Koitere, Rikkavesi, Ondozero, Kovdozero, Cedar Lake, Southern Indian Lake. Mjøsa has year -99.
A blanket filter would erase real 1805 lakes. Use the filter plus an allowlist of natural lakes, or a
denylist of the big man-made ones. The NE Aral is also the modern split North/South Aral, which is
anachronistic. [V names, I shape vs 1805]

### 3.2 Why Aral, Balkhash and Baikal are walkable [V]

Point checks in pt_w9 regions.esf put each lake inside a region's **area 0, passable = True,
nonwalk_group 0xFFFF**: Baikal in asi_east_siberia, Balkhash and Aral in asi_kazakh_steppe, Tsimlyansk
in mea_north_caucasus, Volgograd reservoir in asi_volga_urals, Rybinsk in asi_vologda, Nasser in
afr_upper_egypt. The Caspian is different: eur_map_east filler area 253, passable False, because the
`FILLER_KEEP` rule keeps it filler. Lakes are not holes with no sea region. Three steps fill them:

1. `regions_world.prep_land` fills lake holes, so filler land covers the lakes;
2. `world_regions.partition` keeps a filler component that one region encloses as that region's land
   (docstring: "lakes inside one region's admin-1 units stay its land: Aral, Balkhash, Baikal");
3. `pf_gen.land_fixed` fills lakes, so they are off-map cells. `world_regions.pathfinding` then makes
   land of (off-map ∩ region pass polygons), so lake cells become walkable land of the region's domain.

The supertexture already draws them as water, because `worldgeo.land()` subtracts lakes. Only gameplay
is wrong.

**Fix path (different from 3.1):** cut lakes above a size threshold (e.g. >= 20 u²) out of the region
pass polygons as impassable pieces. Reuse the corridor mechanism: `corridors()` already emits
`k|iN` impassable labels and `pass_polys`; the lake set joins the masks. This is vanilla's "lakes as land"
style (research/05: passable False). Turning them into water would need sea regions and domains, which
the Caspian ports already show is a separate problem. This changes geometry, so regions.esf, pathfinding,
poi, CAI, startpos and ports all rebuild. Adds pathfinding words for the lake outlines, no new domains [I].
The only thing it shares with 3.1 is the filtered lake list.

### 3.3 Why the Don and every non-vanilla river have no blue line [V]

- Rivers are drawn by `display/rivers/NN.rigid_spline` (`river:NN`, world/40 coordinates, height 0)
  with `rivers/textures/*.dds`. The supertexture alpha also marks "drawn rivers" as water (research/07).
- `world_build.py` copies vanilla `display/` with `copytree`. The 84 river splines in world_m1 and pt_w9
  are byte-identical to vanilla (`cmp`). `display.spline_from_world` and `write_spline` have no callers
  outside display.py. `bake_terrain` paints no river alpha. **The build never generates rivers.**
- Vanilla splines stop at x ≈ 322, and none cover the lower Don (x 271-337, y < 55) or anything outside
  CA's painted map. The dark "rivers" in the Volga screenshot are the Volga reservoir chain from
  ne_10m_lakes.
- Fix [I]: splines from `ne_10m_rivers_lake_centerlines` (filtered by scalerank, clipped outside the
  painted mask) via `spline_from_world`, written as `rivers/84..NN.rigid_spline`. Optionally paint the
  same lines into the supertexture alpha, in the same bake as 3.1. These are cosmetic only: vanilla
  rivers are also impassable `river` regions with crossings, so generated ones would be walkable. Unknown:
  whether a river spline renders without alpha water under it, and any cap on the river file count.

---

## 4. Outputs, stages and rebuild time per change

The cold `world_regions.py build` takes 1090 s: geometry 517, rest of `pre` about 357 (cai_regions 251),
ports 86, checks about 164 (`work/scratch/speed/final_w9.log`). The terrain bake takes 654 s, of which
bmng prep (137 s) is now cached (`work/world/terrain/cache/all.log`).

| Change | Outputs touched | Stages | Est. time |
|---|---|---|---|
| **Q1 REGION LOS = polygon + 10 u, SETTLEMENT disc centred** (also switch on playable minors' regions) | startpos.esf only | as a post-pass on the built dir (or a new last stage): none of geometry / pre / ports | **about 1 min** (61 MB startpos load + dump, about 0.9 GB RSS) |
| same, but edited inside `startpos_regions` / `land_probe.startpos` | startpos.esf | `pre` + `ports` miss, geometry hit | about 10 min (357 + 86 + checks) |
| Q2 extra town / resource slots (not a fog fix) | regions.esf, pathfinding.esf, startpos, CAI, db, loc | new post stage after `p` | about 1.5-2 min + check; about 10 min if in `pre` |
| Q3 reservoir filter (with allowlist) | land.wkb, coastdist.npy, heightmap.tga, supertexture.stpi/.stpd, campaign_detail_mask.dds (+ minimap preview if wanted) | none of world_regions; bake_terrain heightmap + supertexture + detail + check | **about 10 min** + 1-2 min copy, assemble and pack |
| Q3 lakes impassable | regions.esf, pathfinding, poi, CAI, startpos, ports | geometry miss = everything | about 18 min (full) |
| Q3 rivers, splines only | display/rivers/*.rigid_spline | none (world_m1 + pack) | about 1-2 min |
| Q3 rivers with alpha | + supertexture | the bake of the reservoir row | do it in the same 10 min bake |

Memory: the supertexture bake forks a Pool. Run it alone, never next to a game test (memory-budget). [I]

## 5. Open questions (game-only)

1. Does a REGION LOS of polygon + 10 for a new region light it in game? Data says yes, as in vanilla.
2. Does the engine ever rebuild REGION LOS after a capture (it was cleared by turn 6)?
3. Do generated river splines render without matching supertexture alpha?
