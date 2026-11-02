# 18 - Every saved GN campaign crashed on load (0xB979C3)

Investigation dated 2026-10-24, on branch `fix/load-crash`. Inputs:
- the installed playtest build `work/world/pt_w10` (its startpos is byte-identical to the one installed);
- the vanilla loose mp_eur_napoleon startpos;
- Empire's `empire_mp_wpath_startpos.esf`;
- copies of the user's four saves;
- saves written in the headless test game.

Tags: **[V]** verified (files, saves, gdb, in game), **[I]** inferred.

---

## 0. Summary

| | |
|---|---|
| Symptom | Loading any GN save crashed at napoleon+0x7979C3 (VA 0xB979C3, `FUN_00b979b0`). Loading from inside a campaign crashed at VA 0xA4FAB7 instead. |
| What the crash is | A CA teardown bug that hides the real error. The CAI load **fails** in "Post Load Fixup A: Factions", the half-loaded CAI is torn down, and a destructor dereferences an id that was never turned into a pointer. [V] |
| Why fixup A fails | A CAI ancestor/descendant cache holds an id that is no component. In the user's 10/21 save this is faction 687's j+13 = 500481492, a garbage value. [V] |
| Root cause | GN's CAI faction cloner (`tools/cai_faction.py`) filed links in the wrong cache. The caches are keyed by the BLOCK_OWNS **row type** (the row's last field, 0/1), not by the A/B parts of the pairs and rows. The game unlinks a deleted component through the cache that matches the row type, so an entry GN filed in the other cache dangles. The next save writes it, and loading that save fails. [V on files and saves; the unlink rule is I, see section 3] |
| Fix (data-side, no exe change) | Cloner caches follow the row type. `fix_caches()` recomputes all four caches by the vanilla rule on the finished startpos (`world_regions.py` calls it before writing). The same pass repairs existing saves: `tools/cai_faction.py fix IN OUT`. |
| Verified in game | (a) The user's save that crashed, repaired: loads. Played 2 turns, then a manual save loaded both in-campaign and from the front end. (b) A new campaign on the installed startpos with `fix_caches` applied: 4 turns, manual save, in-campaign load OK. [V] |

---

## 1. Crash site and the failing step

- Runtime base under Proton wow64 is 0x7aae0000, so runtime = VA - 0x400000 + 0x7aae0000. The crash napoleon+0x7979C3 is VA 0xB979C3.
- The CAI load function is `FUN_00a3ce70`. With `PROTON_LOG=1`, the OutputDebugString section lines appear in `steam-34030.log`. The last section printed before the crash is `Done CAI: WORLD: Post Load Fixup A: Factions`. A "Done" line prints on both the success and the failure path. [V]
- `FUN_00c48b60` is CAI world "Post Load Fixup A": theatres, factions, regions and so on. The CAI_FACTION vtable is at 0x1382694, and slot 6 is `FUN_00c48150` (the faction fixup).
- `FUN_00c48150` does the following:
  - calls `FUN_00c48540` (base);
  - calls `FUN_00a9a190` = `thunk_FUN_00cfd790`, the BDI component header fixup, which resolves every header id list through `FUN_00cc3d50`: owner pairs, the four caches, BLOCK_OWNS rows, subjects and referenced-by;
  - then resolves the faction's own id vectors (+0x110/+0x114, +0x124/+0x128, +0x148/+0x14c, ...).

  Any id that `FUN_00cc3d50` cannot resolve returns 0, so the step fails. [V decompile]
- gdb attached to the wine process, with breakpoints on the failure exits: `FAIL site c48173 n=7`, i.e. the header fixup of faction 687 returned 0. The load then hit `c48372` / `c492ce` (fixup A returning false). [V]
- On failure, the CAI is torn down. `CAI_INTERFACE_DIRECTOR_BDI_POOL`'s +0x8c is still the raw u32 id that the load constructor `FUN_00b8eee0` read from the save, because its fixup never ran. The destructor `FUN_00b979b0` dereferences it, giving the crash at 0xB979C3. Loading in-campaign tears down through `FUN_00a4f770` instead and crashes at 0xA4FAB7 (`call [eax]`, eax = 0). Both crashes are teardown symptoms of the same failed fixup. [V]

## 2. The bad ids in the saves [V]

Dangling cache entries in copies of the user's saves (ids that are no component):

| save | dangling |
|---|---|
| Russia Early January 1805 (10/21, turn 1) | faction 687 j+13: 500481492 |
| auto_save (orig. 10/24 02:29) | faction 687 j+13: 665480760 |
| Russia Late January 1805 | faction 783 j+12: 64 ids; 64 x CAI_BDI_GOAL_REGIONAL_MOTIVATED_DEVELOPMENT_SPECIFIED j+18; faction j+13: 1 |
| quick_save (Britain, 10/20) | the same pattern, plus factions 681 / 714 j+13 garbage |

- In the startpos, faction 687's j+13 held 14282, a CAI_BDI_DESIRE_TRADE_BEHAVIOUR. The game deletes that component at campaign start, and 687 keeps the pointer.
- The 64 faction-783 entries are CAI_DIPLOMATIC_GOAL_BASE components, deleted during play while 783's j+12 still listed them.
- The 64 x j+18 entries are CAI_BDI_BUILDING_TYPE_CONSTRUCTION components, also deleted during play.

## 3. The cache rule (what vanilla does) [V]

Header layout, as offsets from the CAI_BDI_COMPONENT_PROPERTY_SET index j:
- j+9: (owner, row) pairs, with counts in j+10 / j+11;
- j+12 / j+13: ancestors caches;
- j+14: BLOCK_OWNS rows `[item, owner, f32, f32, type]`, with counts in j+15 / j+16;
- j+17 / j+18: descendants caches.

**The rule:**
- j+12 = the transitive closure over owners that link x by a type 0 row; j+13 = the same over type 1 rows.
- j+17 / j+18 = the closure over x's own type 0 / type 1 rows.
- Closure means `dedup [o] + o.j12` (or j13, j17, j18 for the other caches).
- The A/B parts (j+10 / j+11 and j+15 / j+16) are a separate attribute. Neither part decides the cache: every combination of pair part and row part occurs with both caches, but row type 0 always goes with j+12/j+17 and type 1 with j+13/j+18.

Checks:
- vanilla mp_eur startpos: 80638 of 80638 ancestor caches match as sets (`direct` only: 73953). 99.5% also match in list order.
- vanilla mp_eur and Empire mp startposes: `fix_caches` changes nothing.
- Saves the game wrote after several turns on fixed data (t4 manual, t4 auto, new-campaign t5): `fix_caches` changes nothing, so the game itself maintains exactly this rule while it runs.

The old docstring said "A/B ancestors = closure over the A/B owners, ~95% exact in vanilla". That was the wrong model, and the 5% "inexact" was the type mismatch.

**What GN got wrong** (installed pt_w10 startpos):
- 1748 caches differ from the rule, all on GN-cloned components or on outside components that GN clones link to.
- 128 owner pairs sit in the wrong part:
  - CAI_DIPLOMATIC_GOAL_BASE -> CAI_FACTION (faction 783 got 64 A pairs, where vanilla uses B);
  - REGIONAL_MOTIVATED_DEVELOPMENT_SPECIFIED -> CAI_REGION.

  Both came from `_relink` choosing the pair part from the clone's row part.
- [I] The game unlinks a deleted component through the cache matching each link's row type. Evidence: the entries left dangling are exactly the ones GN filed in the other cache, and the game's own saves never deviate from the rule. The unlink code itself was not decompiled.
- The earlier "mirror" repair (make j12 <-> j17 symmetric) loaded the turn-1 save. It still failed after one more turn (the t2 manual save, faction 783's goals), because it mirrored into the wrong caches.

## 4. Fix (tools, branch fix/load-crash)

Changes in `tools/cai_faction.py`:
- `_want` / `_flat` / `_owners`: caches are recomputed by row type, closing over the same cache only.
- `_bubble`: picks the cache to refresh from the row type.
- `_relink`:
  - `links()` builds the clone caches by row type;
  - an outside item owned by a clone gets its owner pair in the **template's** part, not the row part;
  - its cache refresh follows the row type.
- `header_issues`: compares the four caches with `_want` as sets.
- `fix_caches(sp)`: the authoritative pass. It recomputes every component's caches from the pairs and rows. Caches whose set is already right keep their order, and ids that are no component drop out.
- CLI: `.venv/bin/python tools/cai_faction.py fix IN OUT` repairs a startpos or a save, and asserts that a second pass changes nothing.

Change in `tools/world_regions.py`: `fix_caches(sp)` runs right before `startpos.esf` is written. Its result is recorded in `build_info.json` as `cai_caches_fixed`.

Not done:
- `fix_caches` does not move existing owner pairs between the A and B parts. The game deleted those goals and dropped their pairs without trouble (the t2 save had 0 stale pairs), so this was left alone in saves. New builds get the vanilla part from `_relink`.
- `land_probe_b.register_owned` / `clone_beliefs` still write j+16/j+18 their old way. `fix_caches` overrides them at the end.
- Existing saves stay broken until someone repairs them with `cai_faction.py fix`. The game cannot repair them itself, because the load fails before any of its own code could do so.

## 5. Verification

Offline:
- user's Russia Early save repaired: `{13: 787, 12: 577, 17: 256, 18: 128}` caches changed;
- t2 manual save (which crashed) repaired: `{13: 273, 12: 385, 18: 280, 17: 384}`.

In game (headless gamescope, `game_take/give gnload`, game menus; loads checked by `CAI Load Complete` in the Proton log plus a screenshot):
1. Repaired t2 save ("gnload t2fixed"), loaded from the front end: loads.
2. From there, 2 turns ended, then manual save "gnload t4":
   - loaded in-campaign: OK;
   - quit to the main menu and loaded from the front end: OK.
3. Offline check of t4 manual and t4 auto: 0 dangling ids, 0 deviations from the rule.
4. Installed startpos plus `fix_caches`, placed temporarily (original restored afterwards, md5 3924ce5f...): new Russia campaign, 4 turns, manual save "gnload new t5", in-campaign load OK. That save has 0 deviations.
5. World build `world_regions.py build --variant w8 --stages lsvpj --reuse` in the worktree with the new code (cold, 18.6 min):
   - PASS, and every generated faction's header links are exact;
   - `cai_caches_fixed = {13: 130}`: the clone steps still leave 130 j+13 caches off the rule, and the final pass repaired them. Their source (probably the `land_probe_b` belief helpers) was not traced;
   - the resulting startpos has 0 deviations from the rule and 0 owner pairs in a part that vanilla never uses for that kind pair;
   - the standalone `cai_faction.py STARTPOS` check: PASS.

   This build was not played. The in-game runs used the installed pt_w10 startpos with `fix_caches` applied.

Side observation, not investigated: saves grow from about 60 MB at turn 1 to about 112 MB at turn 4. Most of the growth is CAI_RELATIVE_ABSOLUTE_STRENGTH_ANALYSIS_MOBILE / CAI_TAS_ANALYSIS / region-analysis components (+137k components in 2 turns).

## 6. Follow-up (2026-10-24)

**pt_w10 repaired.** `work/world/pt_w10/startpos.esf` is now the `fix_caches` version (md5 bd0269ae..., the same file that is installed). `build_info.json` records `cai_caches_fixed` `{13: 787, 12: 577, 17: 256, 18: 128}`. The original is still in `work/load_fix_backup/` (md5 3924ce5f...).

**Source of the ~130 j+13 repairs on a fresh build.** It was `land_probe_b.land_beliefs`. The head belief clones copied the template's j+13 (type-1 ancestors) and only renamed the ids through the clone map. A clone's ancestors are owned by different beliefs than the template's, so the copy was wrong for every clone whose owners differ. The fix rebuilds j+13 from the rule:
- take the owners whose j+14 row for this belief has type 1;
- add each owner's own j+13.

Wrapping `protectorates.apply` showed it adds no deviations (129 before, 129 after). Rebuild with the fix: `world_regions.py build --variant w8 --stages lsvpj --reuse`, cold, 18 min. Result: `cai_caches_fixed = {}`, and every generated faction's header links are exact. `fix_caches` is now only a safety net. That build has 2 FAILs, both unrelated phase-2 data:
- a Sahara caravan corridor width;
- the Karelia army walk `eur_finland -> asi_olonets`.

**Stage cache gotcha.** If `world_regions.py` runs through `runpy.run_path(<relative path>)`, `co_filename` is relative. `code_digest` then skipped every function as "generated", so the key covered nothing and stale stages were restored. Generated code is now recognised by a `<` prefix, and a module missing from `sys.modules` is judged by the code's file. A normal CLI run was never affected.

**Save growth.** Startpos is 89,702 CAI components. The turn-8 save (135 MB) has 278,336. Nearly all of the growth is per (faction, object) analysis records, which the AI fills in during the first turns:

| kind | startpos | turn 8 |
|---|---|---|
| RELATIVE_ABSOLUTE_STRENGTH_ANALYSIS_MOBILE | 5,927 | 65,898 |
| TAS_ANALYSIS | 5,890 | 57,933 |
| MILITARY_REGION_GROUP_REGION_ANALYSIS | 1,516 | 20,405 |
| COMPOSITE_REGION_ANALYSIS | 1,572 | 20,368 |
| PORT_ANALYSIS | 897 | 13,773 |
| REGION_MILITARY_STRENGTH | 2,565 | 13,461 |
| ARMED_CITIZENRY_ANALYSIS | 2,067 | 10,777 |

These tables are bounded by factions (107) × regions, ports or forces. Only the mobile-forces term keeps growing, as armies get recruited. So this is not a leak. Game RSS is about 2.0 GB on a turn-1 load and 2.26 GB on the turn-8 save, well inside the 32-bit 4 GB. A late-game soak would confirm the plateau.

**The other repaired saves load.**
- auto_save: loads from the front end.
- Russia Late and quick_save: load in-campaign.
- From quick_save, one AI turn was played and a turn-8 save made. That save reloads from the front end, and `fix_caches` on it returns `{}`.
