# 11 - Coalition faction-select screen: where the 4-faction limit lives, and how to offer N factions

Question: why does "Campaigns of the Coalition" (mp_eur_napoleon) offer exactly Britain/Austria/Prussia/Russia,
and what is the cheapest way to make the Qing, Marathas, USA... selectable.

Tags: **[L]** local evidence (file + offset/line; exe addresses are VAs, base 0x400000), **[W]** web, **[I]** inference.
Scratch: work/scratch/ui/ (pack/ = extracted data.pack frontend files, dec/ = unluac output, *.asm = capstone dumps,
dis.py/xref.py = the disassembly/xref helpers, tools/ = unluac jar + capstone/lupa venv, downloaded, isolated).

---

## 0. Answer in five lines

1. The **list of factions comes from the startpos** (CAMPAIGN_PREOPEN_MAP_INFO), via the exe function behind
   `FrontEnd.CampaignDetails`. **The exe has no count cap** [L].
2. **The limit is the UI layout**: `ui\frontend ui\grand_campaign` has only 4 flag slots, `placeholder_faction_1..4`.
   `grand_campaign_scripts\faction_selection.luac` puts faction i into slot i and **silently drops** every faction
   after the 4th (sorted by ListOrder) [L].
3. Vanilla has **5** selectable entries (France plus the four). The exe hard-codes France out when the campaign key is
   `mp_eur_napoleon`, which leaves 4 [L].
4. Cheapest way to get N factions: set the startpos flags for each faction (a script exists), and override **one Lua
   file** in a mod pack so it does not stop at 4 slots. No exe change is needed. The exe patch is only for making
   France selectable [L+I].
5. Fallbacks: swapping which 4 are playable needs the startpos alone (trivial). Several campaign entries is expensive
   and not recommended (section 4).

---

## 1. Mechanism, end to end

### 1.1 Menu -> screen [L]
- `ui\frontend ui\main` (layout, Version028): the button `grand_campaign` has the property `campaign_key = mp_eur_napoleon`
  (byte offset 29342; `spain_main` 29348). There is also a second button with `spa_napoleon` (32117).
- `main.main.luac` (dec line 9, 195): reads `campaign_key` and calls `Root:LuaCall("TransitionTo", "grand_campaign", nil, key)`.
- `grand_campaign_scripts\grand_campaign.luac`, `OnEnter(campaign)`: calls `FrontEnd.OpenMapDataFile(campaign)` and then
  `main_panel:LuaCall("Initialise", campaign)`. `StartCampaign()` calls
  `FrontEnd.StartCampaign(campaign, main_panel:LuaCall("FactionAndVCType"))`.
- Scripts attach **by component name**: `<layout>_scripts\<component>.luac`. The exe has `_scripts/` and `%S/%s.lua` at
  file offsets 0xff10f0/0xff1138. The grand_campaign layout names no script file for `faction_selection`.

### 1.2 main_panel.luac (dec, 237 lines) [L]
- `campaign_details = FrontEnd.CampaignDetails(campaign, false)`. The second argument is false for single player.
- `list_factions()`: takes `campaign_details.Factions`, turns a hash table into an array, and does
  `table.sort(... a.ListOrder < b.ListOrder)`.
- If not `spa_napoleon`: `faction_list = this:Find("faction_selection")`, then
  `faction_list:LuaCall("Initialise", Address, list_factions())`.
- `InitialiseFaction(details)` uses `Name, FlagPath.."/portrait_flags.tga", LeaderPortrait` (may be empty),
  `Description, StartingRegions, GameTypes`.
- `SetVictoryConditions` uses `Factions[fac].VictoryConditions[selected_data+1]`.
  **A faction with no victory-condition entry gives an empty GameTypes, `selected_data` is nil, and the Lua
  arithmetic error breaks the panel** [I from code]. So every selectable faction needs a VICTORY_CONDITION_OPTIONS
  entry.
- Side bug: the `StartYear`-as-table branch concatenates strings with `+`. It is dead in vanilla; leave it alone.

### 1.3 faction_selection.luac (dec, 44 lines) = **the cap** [L]
```lua
for i, v in ipairs(factions) do
  local container = this:Find("placeholder_faction_" .. tostring(i))
  if container ~= nil then  -- slot 5+ does not exist -> faction skipped, no error
    CreateFromComponent(template, v.Key, container, 0, 0) ... flag_animation0000/0001.tga
```
- Layout `ui\frontend ui\grand_campaign` (Version039, 88175 B): `faction_selection` (offset 84839) contains
  `faction_ButtonGroup` (84873), `placeholder_faction_1` (85105, holds the `faction_button` template), and
  `placeholder_faction_2/3/4`. **No 5th slot.**
- `Selected()` returns the clicked key, which main_panel passes on to StartCampaign.

### 1.4 Exe: FrontEnd.CampaignDetails [L]
- Registered at 0x401b80: push "Retrieves various details about the specified campaign" / "CampaignDetails" / **0x46bcc0**.
  Ghidra has no function there (`Decomp` printed "no function"), so the code was read with capstone
  (work/scratch/ui/cd.asm).
- The campaign object is built by **0x877430**. It opens `data/campaigns/%S/startpos.esf` (string 0x1357818) and reads
  CAMPAIGN_PREOPEN_MAP_INFO (reader 0x8cfc30). It then copies the FACTION_INFOS array (+0x6c count/+0x70 data, 0x54-byte
  records) to an MP copy (+0x7c/+0x80), and the players array to an MP copy (+0x84).
- **Hard-coded per-campaign edits, made after the MP copy** (0x8776c1-0x87779d):
  - if key == `"mp_eur_napoleon"`: FACTION_INFOS[`france`] byte +0x19 = 0, and players[`france`] byte +0xa9 = 0
    (lookup 0x8de9f0).
  - if key == `"spa_napoleon"`: the same for `spa_portugal`.
  - 0x8777a4: for mp_eur_napoleon, prussia/russia/austria victory-condition sub-records get field +0x44 = 0x19.
    This does not affect selection.
- Faction loop **0x46bfa0-0x46cd95**: for each players-setup entry (stride 0xbc, count at +8; SP list because the
  argument is false, 0x8dea40):
  - `cmp byte [entry+0xa9],0 / je skip` (0x46bfd7)
  - **and** `0x8be9e0(key)` must find the key in FACTION_INFOS (SP array) (0x46bfeb)
  - then it emits `Key, Name, Description, StartingRegions(+0x50), LeaderPortrait(+0xc), FlagPath(+0x44), ListOrder(+0x1c)`.
  - Victory conditions: game types 0..5 (`cmp esi,6`, 0x46c719), each found by 0x8f9fb0 in VICTORY_CONDITION_OPTIONS
    (stride 0x1c; a block matches when its field +0x7c == the game type).
  - At the end: `Factions`, and `TotalFactions` = the count. **No upper bound anywhere in the loop.**
- Field map of CAMPAIGN_PLAYER_SETUP (serializer 0x891cb0): the key is followed by bools at **+0xa8, +0xa9, +0xaa**.
  The ESF shows `utf16 key, bool, bool, bool`, and the **2nd** bool is the selectable one.

### 1.5 Startpos data [L] (work/scratch/ui/fi.py, players.py on every vanilla campaign)
FACTION_INFOS row = `[key, leader_portrait, boolA(+0x18), boolB(+0x19), ListOrder(+0x1c), description_lockey, FlagPath(+0x44), StartingRegions(+0x50)]`.

| campaign | rows with boolA/boolB | players with 2nd bool True |
|---|---|---|
| mp_eur_napoleon (vanilla) | france T,T,1; austria T,T,2; britain T,T,3; prussia T,T,4; russia T,T,5; ottomans T,F,6; spain T,F,7 | france austria britain prussia russia |
| spa_napoleon | spa_britain/portugal/france/spain all T,T | all 4 (portugal removed by exe) -> 3 shown via its own `button_faction_<k>` layout |
| ita / egy / tut | majors T,T; minors T,F | the 2 (tut: 1) majors |

- Both CAMPAIGN_PLAYERS_SETUP copies (PREOPEN and CAMPAIGN_ENV/CAMPAIGN_SETUP) carry the same flags. The frontend
  reads PREOPEN. The setup copy is presumably what the campaign uses, so set both [I].
- boolB (+0x19) is what the exe clears for France. CampaignDetails itself does not test it, so it is probably read by
  other code (MP or the episodic list) [I]. Set boolA and boolB to True, matching vanilla playables.
- VICTORY_CONDITION_OPTIONS (vanilla, 5): austria britain russia prussia france. Each entry is a
  VICTORY_CONDITIONS_BLOCK of 3 CAMPAIGN_VICTORY_CONDITIONS (REGION_KEYS, date, region count, game-type u32 1/4/3).
- Our world build (tools/land_probe_b.py:1281) clones the `oldenburg` row into PLAYERS_ARRAY and FACTION_INFOS. So
  every generated faction is boolA=F, boolB=F, ListOrder 0, players bool F (not selectable), and it is **not** added
  to VICTORY_CONDITION_OPTIONS [L code, I not re-dumped: the 61 MB world startpos was not loaded, to respect the
  memory budget].
- Flags: zz_gn_world.pack ships the full ui\flags\gn_* set (flag_132, flag_animation0000-0011, portrait_flags,
  mini_flag ...) for 66 factions [L], so both pickers below have their textures.

### 1.6 Raw Lua is accepted [L+I]
- The game's chunks are Lua 5.1 with header `1b4c7561 51 00 01 04 04 04 04 00`: lua_Number is a **4-byte float**.
  A stock luac 5.1 build would produce incompatible bytecode.
- The parser is in the exe: strings "unexpected symbol" and "'=' or 'in' expected". Layouts embed Lua **source**,
  e.g. `function OnSelect() parent:LuaCall("FactionSelected", this:Id()) end` in grand_campaign.
- There is a tweak `use_compiled_scripts`: "If use_compiled_scripts is set to false then the raw lua scripts will
  always be used rather than looking for compiled versions" (UtilityDLL LuaState.cpp strings, file offset ~0xff20c3).
- So shipping **plain source text under the .luac file name** should load, because lua_load auto-detects
  text vs bytecode [I, test T1 confirms].
- Fallback: compile with Lua 5.1.5 built with `LUA_NUMBER float` (luaconf.h).

### 1.7 Prior art [W]
- Napoleon Total Faction (startpos-only): the author found "a 4 faction limitation in Napoleon UI" and split the
  release into one file per group of four - https://m.cafe.daum.net/shogun/4rgB/93 (search snippet).
- Gromazeka's mod "allows you to open absolutely all factions in the coalition campaign selection menu (previously
  you could only open 24)", with "flags reduced by half". That means a frontend UI edit plus all factions in one
  startpos - https://www.moddb.com/mods/gromazeka (search snippet; the page returns 403 to fetch).
  The 24 probably refers to an earlier modded layout with 24 slots [I].
- Neither mod's files were used.

### 1.8 Engine leftovers that already handle N factions [L]
- `ui\frontend ui\faction_selection_big` / `_small` (ETW grand-campaign pickers, referenced by no NTW layout) run
  `..\common\faction_list.luac`.
  - It is a **9-flag rotating carousel** (`flag_1..flag_9`, `SelectPrevFaction`/`SelectNextFaction` arrows) for any
    number of factions.
  - Interface: `Initialise(parent_addr, init_func, isNaval, start_key)`, where `init_func()` returns the faction
    array (`Key, Name, FlagPath`).
  - It calls `parent:LuaCall("NotifyFactionSelected", key)`.
- `common\faction_dropdown_menu.luac` (MP lobby): a list that grows one row per faction with no scrolling. It is unfit
  for about 100 factions.
- UI API used in vanilla scripts: `Component.CreateFromLayout(path, name, parent)`,
  `CreateFromComponent(tpl, id, parent, x, y)`, `:MoveTo`, `:Position`, `:Resize`, `:Dimensions`, `:Width`,
  `:Height`, `:SetVisible`.
- Lead from the coordinator: Napoleon64Lab `results/dispatcher_inventory.json` lists class-method bindings
  (e.g. `SetFaction`) but not the FrontEnd table. The FrontEnd registration above (0x401b80) was found directly.

---

## 2. Where N is limited

| layer | limit | evidence |
|---|---|---|
| startpos | none; any faction with players 2nd bool + a FACTION_INFOS row (+ a VC entry for a working panel) | 1.4, 1.5 |
| exe | none for count; **France blocked by name** for mp_eur_napoleon | 0x8776c1 |
| Lua faction_selection | stops at the last existing `placeholder_faction_i` | 1.3 |
| layout grand_campaign | **4 slots** | 1.3 |

---

## 3. Options ranked (effort / risk)

| # | option | changes | effort | risk |
|---|---|---|---|---|
| A | **Swap the 4** | startpos only: flags + VC entry + ListOrder for 4 chosen factions; clear (or give a higher ListOrder to) the vanilla 4 | S (script ready) | low on the screen; the in-game player-faction risk is the same as B |
| B | **N in one campaign, Lua override** (recommended) | A for N factions + one text file `ui\frontend ui\grand_campaign_scripts\faction_selection.luac` in a mod pack | S-M | medium: the carousel layout's on-screen position/size is unknown; text-.luac load not yet confirmed |
| C | layout edit (Gromazeka route) | add `placeholder_faction_5..N` to the binary `grand_campaign` Version039 layout | M-L (no local twui editor) | medium |
| D | several campaign entries | main menu has hard-coded buttons (`grand_campaign`, `spain_campaign` gated by `SpanishCampaignEnabled`); the episodic list comes from the exe (`EnumerateNapoleonsCampaigns`); 12 code sites test the string `mp_eur_napoleon`; each entry needs its own loose 61 MB startpos | L | high (per-key exe special cases, pfgrid/word-budget patches checked only on mp_eur) |
| E | exe patch (only for France) | file offset **0x476acd: `74` -> `EB`** (`je 0x877734` -> `jmp`), which skips the France removal | XS | low; candidate for an exe_patch group |

Not covered by any option: whether a **generated** faction plays correctly as the human player (government screen,
ministers, ui_skin, advisor, events).
- The Coalition scripting.lua guards its faction logic with `FactionIsHuman("<vanilla key>")` (lines 729-780), so it
  is tolerant [L].
- NTF made vanilla minors playable with startpos edits alone, which implies they work as the human player
  [W, search snippet only, not verified].
- Generated (oldenburg-clone) factions are untested in human hands [I]. This is test T2.

---

## 4. Change list for option B

1. **Startpos** (after the world build, before install). The tool is `work/scratch/ui/make_playable.py IN OUT key...`
   (scratch, ~60 lines, verified on vanilla).
   - FACTION_INFOS row: boolA = boolB = True; ListOrder = max+1, +2, ... in the order given.
     Optionally set a leader portrait path (an empty one is fine).
   - PLAYERS_ARRAY in **both** CAMPAIGN_PLAYERS_SETUP copies: 2nd bool after the key = True.
   - VICTORY_CONDITION_OPTIONS: append `[key, deepcopy(britain's VICTORY_CONDITIONS_BLOCK)]` with REGION_KEYS emptied.
     That keeps the 3 game types; the region-count targets stay Britain's. Tune per faction later.
   - Loc: the FACTION_INFOS description key must exist in the loc. The builder already writes `desc` keys
     (land_probe_b.py:1294); check that they have text. The name comes from factions_tables.
   - Move this into tools/ (world build stage) when adopted.
   - It loads the whole ESF, so it obeys the memory budget: never run it beside a world build or a game test.
2. **Lua**: `work/scratch/ui/proposed/faction_selection.lua`, which compiles under Lua 5.1 (lupa).
   - With 4 or fewer factions it behaves like vanilla.
   - With more than 4 and `MODE="carousel"`: it hides the 4 placeholders, `CreateFromLayout("data/ui/frontend
     ui/faction_selection_big", ...)`, moves it to the panel origin, and drives it through common\faction_list.luac.
   - `MODE="grid"`: clones the vanilla flag button at `SCALE` (0.5) in rows from placeholder_faction_1, at a pitch
     taken from placeholder 1 -> 2.
   - It adds `NotifyFactionSelected` (called by the carousel) and keeps `Selected()` for main_panel.
   - Built packs: `work/scratch/ui/zz_gn_fsel_carousel.pack` and `zz_gn_fsel_grid.pack` (type 3, one file each,
     source text under the .luac name). Fold it into zz_gn_world.pack once one mode passes.
3. **ListOrder policy**: keep the vanilla 4 at 2-5 and number the new ones after them, so the default selection
   stays a vanilla major.
4. Optional E (France).

---

## 5. Proposed in-game test (for the user to run; nothing here launched the game)

Setup: back up the loose `data/campaigns/mp_eur_napoleon/startpos.esf`. user.script.txt must stay UTF-16LE with BOM.

- **T0 (control, confirms the cap)**
  - Copy `work/scratch/ui/test_vanilla9/startpos.esf` into the loose path. It is the vanilla map with
    sweden/denmark/ottomans/spain made selectable; sha256 starts 9df4c3be155c6ecb.
  - Remove `mod zz_gn_world.pack;` from user.script.txt for T0/T1, because the world db would not match a vanilla
    startpos.
  - Coalition screen. Expect **exactly Austria, Britain, Prussia, Russia** (ListOrder 2-5) and none of the 4 new ones.
- **T1 (UI fix, vanilla map)**
  - Same startpos. Copy `zz_gn_fsel_carousel.pack` to data/ and add `mod zz_gn_fsel_carousel.pack;`.
  - Pass: a flag carousel with arrows; all 8 reachable; clicking Sweden updates the name, flag, description, starting
    regions and the victory-condition dropdown; Start Game loads a campaign as Sweden; End Turn twice without a crash.
  - Record: carousel position/overlap (screenshot), and whether arrows and flag clicks work.
  - If the screen shows **no flags at all**, the text-.luac load failed. Report it, and I will compile real
    float-number bytecode.
  - If the carousel is mis-placed or broken, repeat with `zz_gn_fsel_grid.pack` instead.
    Pass is the same; record the flag size and whether they overflow.
- **T2 (world)**
  - Run `python3 work/scratch/ui/make_playable.py <world startpos> <out> <keys>` using the startpos keys for the Qing,
    Maratha Peshwa and the United States (as written in FACTION_INFOS; the script asserts they exist). Run it only
    when no world build is running.
  - Install `<out>` as the loose startpos, with zz_gn_world + the passing fsel pack.
  - Start as the Qing and play 3 turns.
  - Check: the government/ministers screen, the faction summary, recruitment, the diplomacy screen, and the end-turn
    AI phase.
  - The crash signatures to watch are the known ones (0xB108F5, 0xAED830) and any new one.
- **T3 (optional, France)**: a copy of the exe with byte 0x476acd = EB. Expect France in the list.

## 6. In-game results (2026-10-21, run by the main session)
- T0 passes: test_vanilla9 startpos, no pack. Only Austria, Britain, Prussia and Russia show, though 8 are flagged playable.
- T1 passes:
  - With zz_gn_fsel_carousel.pack the plain-text .luac loads.
  - The carousel shows all 8: Sweden, Denmark, Ottomans, Spain | Austria, Britain, Prussia, Russia.
  - Clicking a flag updates the name, the minimap regions and the victory conditions. The description is
    "PLACEHOLDER" for factions without Coalition loc.
  - Start Game as Denmark loads, and 2 AI turns pass (56 s, 71 s).
- T1 cosmetic issues:
  - The carousel sits right of centre, and the side flags overlap.
  - Russia is off-screen until rotated.
  - A click on a side flag rotates the carousel, so the selection lands on the slot rotated into the click
    position (clicking Sweden selected Denmark).
- T2 (world startpos as the Qing) is not run yet.
