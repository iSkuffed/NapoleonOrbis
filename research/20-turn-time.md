# 20. AI-turn time: where it goes (2026-10-30)

The question: AI turns of 3–5 minutes in pt_w11/pt_w12, a release blocker. Is the world map the cause?

## Method

A per-faction timer in the campaign Lua: a copy of vanilla `episodicscripting.lua` (from data.pack) with
`events.FactionTurnStart` / `FactionTurnEnd` handlers that write `os.clock() os.time() start|end <faction>` to
`gn_turns.log` in the game dir. Under Wine `os.clock` is wall seconds; `os.time` barely moves. The copy is shipped in
a type-2 pack (`zz_gn_prof.pack`, test only; type-2 packs auto-load). `work/scratch/gn_agg.py` sums seconds per faction per
AI round. Same campaign each time: Coalition, Great Britain, a new game, turns 1–4, with `work/scratch/turns.sh`
answering modals.

CPU profiling (perf) was flat. The A* (FUN_00ac54c0, research/19) was 0.7%. About 16% of the main thread is kernel
time from Wine file lookups of missing "placeholder" assets, about 100/s, and vanilla data.pack and sound.pack
reference them too.

## Results (seconds of AI per round)

| build   | rounds         | big 8 powers | 76 world minors (mean each) |
|---------|----------------|--------------|-----------------------------|
| vanilla | 141, 146, 64   | 138, 143, 61 | (13 minors: 2.6 s, 0.2 each) |
| pt_w10  | 173, 105, 170, 104 | 150, 57, 130, 71 | 23–48 s (0.3–0.6 each) |
| pt_w12  | 187, 189       | 151, …       | 36 s (0.46 each)           |

- **The 60–85 s spikes are the harness.** Prussia (64 s in vanilla, 67 s in w10), Russia (70–85 s) and the Ottomans
  (78 s in w12) each wait on a diplomacy proposal to the player. turns.sh polls every 10 s and cycles through
  5 buttons, so it takes 40–75 s to hit Decline. The popup screenshots fall inside exactly those faction windows.
  A human answers in seconds.
- **The steady cost is vanilla's.** France, Austria and the Ottomans take 20–26 s each per round in vanilla too, with
  no popup inside the window.
- **The world map adds about 25–45 s per round.** That comes from 76 more minor factions, each 0.3–0.6 s, against
  0.2 s for a vanilla minor. That fits per-faction work that scales with region count (266 regions against
  about 70 in vanilla).

So the world map runs about 1.3–1.5× vanilla's AI time on this machine, at 100–110 s of real AI time per round
early in the campaign. The earlier 4.5–5.5 min figures were harness modal waits plus, before the `astar` patch, the
ocean flood (research/19).

## Long campaign (pt_w13, 2026-10-30)

17 AI rounds from the turn-6 autosave (Britain) to turn 23, same timer. Seconds of AI per round:

| turns   | AI per round                    |
|---------|---------------------------------|
| 6–10    | 270, 160, 183, 184, 235         |
| 11–16   | 210, 240, 133, 159, 121, 103    |
| 17–22   | 79, 67, 173, 44, 77, 119        |

Turn time does not grow; it falls as the early wars settle. The single-faction spikes (Spain 121 s, France 67 s,
the Ottomans 82–95 s) fall in rounds where the harness was clicking through proposal and event modals; with none,
a big power takes 2–40 s. Game RSS went from 2.64 to 2.82 GB over the run. A perf sample of an Ottoman window is flat,
as in the early turns (top function 12.7%), so nothing single is worth patching.

The harness's turn-end check matches the end-turn panel including its date text, so it misses most turn ends and
ends several turns per "turn"; the Lua log is the record.
