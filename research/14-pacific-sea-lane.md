# 14 - A Pacific sea lane across the seam (Empire-style transition areas)

Problem: the world map is flat with the seam at 169 W (tools/proj.py `SEAM = -169.0`, theatre x +-1910). Russia's
Okhotsk (143.2 E) sits near the right edge and Sitka (-135.33) near the left, so a Russian fleet has to go round the world.
Question: can Empire's theatre transitions give a lane where a fleet enters an edge zone and comes out at the opposite edge?

**Answer: very probably yes, with data only (regions.esf + one UI Lua file), and no exe patch or pathfinding change.**
The whole Empire transition pipeline is still in Napoleon.exe and is still wired to NTW's campaign UI. None of the code
traced checks that the destination theatre differs from the current one. The open questions are a runtime test,
and the AI, which will not use the lane.

Tags: **[V]** verified by decompiling Napoleon.exe (Ghidra project work/ghidra, the exe copy in work/ghidra/Napoleon.exe)
or by reading the files. **[I]** inferred, not tested in game. Scratch work, scripts and decompiles: `work/scratch/sealane/`
(`dec*.c`, `strxref.txt`, `emp_tas.txt`, `lanes.py`, Ghidra helper scripts in `ghidra/`).

---

## 1. How Empire's transitions are stored

Three layers. Only the first is required for a working lane.

| Layer | File / record | Contents | Evidence |
|---|---|---|---|
| **Map definition** | `regions.esf` `theatres/theatre/transition_areas` (record array v0) | one item per area: `u32 name_id`, `xy min`, `xy max` (world-unit rect), `f32 unknown`, `transition_links` (record array), each link `f32 extra_turn_pct, u32 turns, u32 dest_theatre, u32 dest_area` | loader FUN_00a41de0 (str refs 0x00a4241a `transition_areas`, 0x00a426a3 `transition_links`), tag checks 0x08 / 0x0c / 0x0c / 0x0a, then 0x0a / 0x08 / 0x08 / 0x08 [V]; etwng names link fields 1..3 "Turns Needed / Destination Theatre / Area Inside Destination Theatre" (`work/scratch_pathfinding/esf_semantic_converter.rb:320`) [V] |
| **Unit state** | startpos/save `NAVY/THEATRE_TRANSITION_INFO v1` = `CAMPAIGN_MAP_TRANSITION_LINK v1 {f32, u32 turns, u32 dest_theatre, u32 dest_area}`, `bool in_transit`, `bool extra_turn`, `u32 turns_elapsed` | only on NAVY, never on ARMY. Idle value `(0.0, 0, 0xFFFFFFFF, 0xFFFFFFFF), False, False, 0` | 18 navies in vanilla mp_eur, 36 in the Empire GC startpos, all idle (`ntw_mp_eur_trans.txt`, `emp_dme_trans.txt`) [V]; field meaning from FUN_008cbde0 / FUN_008ca120 / FUN_00a24eb0 (section 2) [V]; etwng save sample `<theatre_transition turns="1" destination="6" via="0"/>` (etwng TAGS.txt:301) [V] |
| **AI shadow** | startpos `CAI_WORLD/CAI_WORLD_TRANSITION_AREAS` items: BDI header, CAI id, `CAI_SITUATED {i32 x, i32 y (2^20 fixed), u32 region, u32[] {theatre cai id}, u32}`, `CAI_TRANSITION_AREA {u32 index, u32[] reachable CAI TA ids}`; plus each `CAI_WORLD_THEATRES/THEATRE` has a final u32[] of its TA CAI ids | Empire GC: 23 TAs over 7 theatres (e.g. TA 3595 at (-750,100) in theatre 31). NTW mp_eur: `x0`, and THEATRE's last array is empty | `emp_tas.txt` [V]. Post-load fixup "Transition Areas" (FUN_00c48b60, str 0x00c491c2) only iterates existing CAI TAs; nothing seen that builds them from the map [V/I] |

Empire's regions.esf is not in `work/empire_reference/` (only the startpos files and minimap TGAs), so Empire's actual rects,
`f32` values and turn counts could not be read. The format comes from the exe loader, which is what matters for NTW [V].
A public web search turned up nothing on the Empire regions.esf transition data.

Pathfinding: transition areas are **not** in pathfinding.esf. They are plain world rects; fleets reach them over ordinary
sea polygons. Pathfinding type 2 ("transition area", 10165 Europe traits) is NTW's blocked/outside coverage, and path id 1023
is off-map. Neither is tied to these rects (research/06) [I, strong: NTW has type-2 polygons and zero transition areas].

## 2. Does NTW keep it? Yes, the whole chain

Vanilla NTW data: every map's `theatre/transition_areas` is present but `x0` (research/05). The startpos has the navy
`THEATRE_TRANSITION_INFO` (idle), an empty `CAI_WORLD_TRANSITION_AREAS`, and an empty `CAMPAIGN_TRADE_MANAGER/THEATRES` [V].

Exe chain, traced end to end [V unless marked]:

| Step | Function (VA) | What it does |
|---|---|---|
| Load | FUN_00a41de0 | parses `transition_areas` into the theatre's 0x38-byte TA vector (theatre +0x7c count / +0x80 ptr): rect, name `campaign_map_transition_areas_onscreen_name_<name_id>`, the f32 at +0x1c, links at +0x28/+0x2c, 4 edge-touch flags (within 2.0 u of a theatre edge), and a global running index |
| Lookup | FUN_00aaf360 / FUN_00aaf800 | theatre containing a point / TA rect containing a point (`min <= p < max`) |
| Cursor | FUN_009ce010 @0x009d03da | a selected character + a TA under the cursor + a path to that point (FUN_00b17710) sets order type **0x12**. No theatre test |
| Click | FUN_00a0bd50 case 0x12 -> FUN_009c49f0 | calls Lua `ShowTravelDestinationsPopup(details)` with `Character, Units, PositionX/Y, Bounds*, CurrentTheatre`, `Transitions = {theatre key -> dest theatre}` built from the TA's links |
| UI | `ui/campaign ui/layout.root.lua:747` -> panel `travel_destinations` (layout + `travel_destinations.luac` ship in NTW data.pack) | 7 hard-coded theatre buttons (`Theatre` property `america`, `europe`, `india`, `trade_*`), then `CampaignUI.FinaliseMoveTransition(char, units, x, y, Transitions[button.Theatre])` |
| Command | FinaliseMoveTransition 0x009e43a0 -> CCQ_TRANSITION_THEATRE handler FUN_009388a0 -> FUN_0096d3c0 | navy only (FUN_008be360). Finds the TA under the position, then the first link whose dest theatre equals the chosen theatre |
| Move | FUN_0091df70 | paths to the TA, or acts at once if already inside; creates the pending move/transition action (vtable 0x0135f82c, saved as `TRANSITION_ACTION_CONTROLLER`) |
| Depart | `transition_to_theatre` action (ctor FUN_0090bc80) -> FUN_0094e640 -> FUN_008cbde0 | copies the link into navy +0xf0, sets `in_transit` (+0x100), `extra_turn = rand(0..100) <= link.f32` (FUN_007add80 is a 0..100 RNG), `elapsed = 0`, removes the fleet from map and display |
| Tick | FUN_008ca120 (called from FUN_00a24eb0, character turn start) | `elapsed++` while `elapsed < turns + extra_turn` |
| Arrive | FUN_00a24eb0 | when `turns + extra_turn - elapsed == 0`: dest TA = `theatres[dest_theatre].TAs[dest_area]`, up to 8 random points in that rect (1.0 u margin), validated by FUN_00b34010 / FUN_00a0bbd0; place with FUN_0096c8d0, reset the info to idle. If all 8 tries fail, it retries next turn. **No bounds check on dest_area.** |

Also present: debug `transition_theatre` ("Make selected naval character transition to edge of nearest transition
area", handler 0x0096d360; the console is not reachable in release), UI strings `exit_theatre_tooltip` and
`fleet_status_transit1/2`, the `fleet_arrives_in_theatre` event, the `campaign_transition_markers` marker model class
(arrows, visual only), and the advisor mp3s `1179_campaign_advice_move_between_theatres`.

## 3. Can it work inside one theatre?

| Option | For | Against / risks | Verdict |
|---|---|---|---|
| **(a) self-transition**: theatre 0 has TA_E (east edge) linked to (theatre 0, TA_W) and TA_W linked back | nothing in load, cursor, command, depart, tick or arrive compares the destination theatre with the current one [V]. Links are matched by dest-theatre pointer; one link per TA is enough. Each lane is its own pair, so several lanes are fine. TA rects add ~100 bytes each to regions.esf and **0 pathfinding words** | UI: the buttons only light up when `Transitions[<button.Theatre>]` exists. NTW's theatre key is probably not `europe`, so ship a replacement `travel_destinations` Lua that takes the one entry via `pairs()` (text Lua under the .luac name works, research/12) [I]. Not tested in game. Arrival happens at the faction's next turn start, so the fleet is gone at least one turn (turns 0 and 1 behave the same) [V] | **Recommended** |
| (b) two theatres (thin "east Pacific" theatre) | Empire-proven inter-theatre case | needs a 2nd `theatres` + `theatres_and_region_keys` entry, a `campaign_map_playable_areas` row, REGION_OWNERSHIPS_BY_THEATRE, CAI THEATRE, governor posts per theatre, radar, a theatre switcher. Positions outside every theatre rect get no theatre (FUN_00aaf360 returns null). Uses the same arrival code as (a), so it only adds work | fallback only if (a) hits a hidden same-theatre check |
| (c1) scripted teleport (scripting.lua) | | NTW `game_interface` has no teleport or move method (full method list in the exe strings: `add_location_trigger`, `disable_movement_for_character`, `cancel_actions_for`, ...). `teleport_to` / `CCQ_TELEPORT_TO` is debug-console only [V] | infeasible without an exe patch |
| (c2) pathfinding link (land-bridge style) / true wrap | | land-bridge types 4/5 are local polygon geometry inside 2-u cells. Neighbours come from grid column +-1, and the edge direction byte 0x01 means "leaves grid". Wrapping needs pathfinder, heuristic, camera and render patches | infeasible at sensible cost |

AI: with no `CAI_TRANSITION_AREA` records, the AI has no lane. Even with them, it reasons about TAs per theatre (getting to
a theatre it is not in), and with one theatre that never triggers. Expect AI fleets never to use the lane. That is neutral:
the AI gets the same map as today. AI movement cannot start a transition by accident: departure needs the explicit
CCQ / action [I]. Hand-built CAI TA records are possible (format in section 1), but the payoff is unknown.

Save compatibility: the TAs are read from regions.esf at every load, and the navy transit state is saved, so **adding**
lanes to an existing save should just work [I]. **Removing or reordering** TAs while any fleet is in transit (or has a
pending move to a TA) indexes past the TA vector at arrival, which risks a crash [V: no bounds check]. Rule: append-only TA
list, and never delete a lane in a patch.

## 4. Recommendation and experiments

Use option (a). The proposed world lanes have 40-u-deep rects on both edges, with the same latitude band on each side
(`work/scratch/sealane/lanes.py`, NE land fraction):

| Lane | Lat band | y range | east rect x 1870..1910 | west rect x -1910..-1870 |
|---|---|---|---|---|
| Bering | 54..62 N | 68..172 | 0.2% land | 5.5% (Alaska Peninsula tip; trim to 55.5 N) |
| N Pacific (Kamchatka <-> Gulf of Alaska) | 40..51 N | -114..29 | 0% | 0% |
| Hawaii | 18..32 N | -354..-212 | 0% | 0% |
| Equator | 8 S..8 N | -618..-456 | 0% | 0% |
| S Pacific (Samoa/Niue side) | 30..12 S | -842..-659 | 0.4% | 0% |
| Southern | 55..35 S | -1096..-893 | 0% | 0% |

Each TA: `name_id` = its index, `f32` = 0.0, one link `(-1.0, 1, 0, partner_index)`. With `extra_turn_pct` = -1 the
extra turn never happens.

**Experiment A: arrival only, data only, fully automated (vanilla map, mp_eur_napoleon).**
1. regions.esf (vanilla nap_europe, in a mod pack): append 2 items to `theatres/theatre[0]/transition_areas` (v0).
   TA0 "Biscay-west": `0, (-410,-60), (-380,-20), 0.0, links [(-1.0, 1, 0, 1)]`.
   TA1 "south of Rhodes": `1, (120,-190), (160,-176), 0.0, links [(-1.0, 1, 0, 0)]`. Both rects are 0% land and touch a
   theatre edge. `transition_links` is a new name for the name table; esf.dumps appends it. Use v0.
2. startpos: set one British NAVY's `THEATRE_TRANSITION_INFO` to `((-1.0, 1, 0, 1), True, False, 0)`.
3. Load, end turn once, save. Pass: in the save, that navy's info is idle again and its position is inside TA1
   (parse with tools/esf.py), and the screenshot near Rhodes shows it. Also run 3 more AI turns with no crash.
4. Expected failure modes: fleet never arrives (placement rejected; fall back to a bigger rect), crash at load (link record
   version), the fleet visible at its start point during transit (the startpos shortcut skipped the depart notifications;
   not a real-game problem).

**Experiment B: the real player path.** Same regions.esf, plus a `ui/campaign ui/travel_destinations.luac` replacement
whose `Initialise` takes the only `pairs(details.Transitions)` entry and enables OK. Select a British fleet, hover TA0
(look for the transition cursor), right-click, check the popup, OK. Pass: the fleet sails into TA0, disappears with a transit
status, and appears in TA1 at the next turn start. Also save and load mid-transit. Optionally add loc rows
`campaign_map_transition_areas_onscreen_name_0/1` in the type-2 loc pack.

**Effort (our pace):** A is ~2 h of scripting plus one game run. B is +3-4 h (Lua, then clicks via ntw.sh or a human
playtest). World integration is ~1 day: emit the 12 TAs from proj.py bands in world_build after regions_world, run a seam
self-check on rect land fraction and edge contact, plus one sail-across test per lane. CAI TA records for AI use: 2-4 days,
uncertain; not recommended until A and B pass.

## 5. Open risks

1. Not yet run in game: a same-theatre check could still exist off the traced path, e.g. in the UI cursor state or the pick
   classifier FUN_00963870 [I]. Experiment A or B settles it.
2. The UI popup needs the Lua replacement. `CurrentTheatre` comes from the playable-area record (+0x34); its NTW value was
   not resolved [?].
3. Meaning of the TA's own `f32` (+0x1c) is unknown. 0.0 is a guess [?].
4. AI never uses the lane (accepted). Its naval planner still sees the long way round as the only route.
5. Saves break if lanes are removed or reordered (no bounds check at arrival) [V].
6. TA rects capture the cursor over their whole area. Keep them on open sea, away from ports and coasts, or clicks near
   land inside a rect become transition orders [I].
7. The pfgrid exe patch (memory note) is still needed for any test east of x=138. The east-edge lanes are at x ~1890.
