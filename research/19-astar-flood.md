# 19. AI-turn hang: the campaign A* floods the world ocean (2026-10-28)

pt_w11 (the friend's list on top of phase 2) played AI turns 1–3, then hung on AI turn 4. The screen froze on
"Other powers move" with the Great Britain banner, the main thread stayed at 100% CPU, and there was no crash.
The hang is deterministic: reloading the turn-4 autosave and ending the turn hangs again.

## What runs

Stack samples, every 15 s for 3 min, all showed the same chain: `0xB0073B` (node compare) ← `0xB40CD7` (visited
lookup, FUN_00b40c70) ← `0xAC575E` (A*, FUN_00ac54c0) ← `0xB3149D` (path request, FUN_00b31320).

- FUN_00ac54c0 is an A* on pathfinding cells. A node holds the cell (x, y) as u16 at +0x14, its position in
  2^20-per-u fixed point at +4 / +8, and an identity pointer at +0xC. The visited set is a linear-probing hash
  at `this+0xC4` (entries, count +0xC8, capacity +0xCC; 12-byte slots).
- The request: start cell (795, 612), at 6.0°W 47.7°N (Bay of Biscay). Goal cell (1105, 578), at 41.3°E 42.5°N
  (eastern Black Sea). Cost bound FLT_MAX.
- The visited table held 243k cells, out of a capacity of 262,144, and was still growing.

## Why it floods

The flood covered 87.7°W–80.8°E and 43.7°S–80.3°N (Atlantic, Caribbean, Arctic, Baltic), but not a single
Mediterranean cell. A geometric sea BFS over pathfinding.esf goes through the strait to the goal, through
1,076,056 cells. The game's search instead stops at a rectangle around the Strait of Gibraltar: cells x ≥ 785,
rows 530–540. pt_w10 and pt_w11 have identical cells there (costs8, traits, middle20), so the pathfinding data
is fine. The box is most likely the AI's avoidance rect around an enemy force at Gibraltar.

So the goal really is unreachable, and A* has to try every reachable sea cell before it can say "no path". Vanilla
Europe's whole sea is under ~100k cells, so this is cheap there. The world's sea is about 1M cells.

## Why it hangs, then runs out of memory

1. **Growth.** The insert (FUN_00b69130) only grows the table, to 2n+1, after a full scan finds no empty slot. The
   table runs 100% full and every miss scans all of it.
2. **Hash.** FUN_00b44f00 returns `(ptr>>2) ^ byteswap16(y*4095 + x)`. The values sit in a narrow band. With
   growth fixed, the table was at 37% load and one occupied run was still 295,348 slots long. The rate was ~70
   inserts per second.
3. **Memory.** With both fixed, the flood ran far enough to exhaust the 32-bit address space (wine
   `allocate_virtual_memory out of memory`, then a page fault) about 20 s into the AI turn.

## Fix: `tools/exe_patch.py` group `astar`

- The entry nop of the insert (VA 0xB69139) jumps to a cave (0xA38B80). The cave sends the insert to the existing
  grow path (0xB69242) when `2*count + 2 > capacity`.
- The hash's tail (0xB44F49) jumps to a cave (0xA38BA0) that adds a murmur3 finaliser step. All 6 callers reload
  EDX before using it.
- The loop already had a give-up test (0xAC5961): an expansion counter at +0xDC against a limit at +0xE0. The limit
  is always 0xFFFFFFFF, and the counter is only reset by the constructor, so it never fires. It now compares the
  visited count (+0xC8) with 200,000 instead and returns "no path", the same as an exhausted open set. The visited
  table is the per-source cache: FUN_00b31320 looks the goal up in it before searching. 243k visited ran without
  running out of memory.

## Result

The turn-4 save, which hung for 10+ minutes before the fix, now finishes its AI turn in 265 s. Later turns took
261–292 s, with peak RSS ~2.6 GB. Builds before this one took 41–236 s per AI turn. Stack sampling during these
turns found no A* frames.

If AI fleets start failing long routes that do exist, raise the cap and watch memory.
