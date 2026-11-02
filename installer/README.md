# Napoleon: Orbis installer

One Go program, stdlib only, no cgo. Windows (Steam) and Linux (Steam + Proton).

## Build

    export PATH=$HOME/.local/go/bin:$PATH
    CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build -ldflags="-s -w" -o dist/napoleon-orbis-installer-linux-amd64 .
    CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o dist/napoleon-orbis-installer-windows-amd64.exe .
    # single-file build: put the payload in installer/payload/ first (manifest.json at its top level)
    CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -tags embedpayload -ldflags="-s -w" -o dist/napoleon-orbis-installer-embedded.exe .
    go vet ./... && go test ./...      # synthetic tests need nothing; the real-file tests skip when ../.venv or the game files are absent
    # embed check: GN_WRITE_FIXTURE=$PWD/payload go test -run WriteFixture . && go test -tags embedpayload -run Embedded . ; rm -rf payload

## Usage

    installer install|uninstall|status [--game DIR] [--payload DIR] [--yes]    (flags may also come before the command)
    installer            (no arguments: 1) Install 2) Uninstall 3) Status, then waits for Enter)

Game detection: Steam root (Windows: registry `HKCU\Software\Valve\Steam` SteamPath via `reg query`, else
`C:\Program Files (x86)\Steam`; Linux: `~/.local/share/Steam`, `~/.steam/steam`, Flatpak path), every library in
`steamapps/libraryfolders.vdf`, the one holding `appmanifest_34030.acf`. `--game` overrides.
user.script.txt: `%APPDATA%\The Creative Assembly\Napoleon\scripts\` on Windows; on Linux the Proton prefix in the same
library (`compatdata/34030/pfx/...`, must exist: run the game once). An existing `User.script.txt` casing is kept.

## Payload

`payload/` next to the binary, `--payload DIR`, or embedded (`-tags embedpayload`; `--payload` still wins).

    manifest.json   {"version","mod_packs":["zz_gn_world.pack"],"startpos":"startpos.esf","loc_rows":"loc_rows.tsv","exe_patch":"exe_patch.json"}
    zz_gn_world.pack  (every name in mod_packs)
    startpos.esf
    loc_rows.tsv      header line key<TAB>text<TAB>tooltip, then key<TAB>text<TAB>tooltip(true|false), escapes \t \n \r \\   (our rows only, no CA text)
    exe_patch.json    `python tools/exe_patch.py json`

## What install does

Close the game first (the installer says so). Before any write it checks everything (payload files, manifest, TSV
without duplicate keys, `local_en_patch.pack` and the merged localisation built in memory, the exe being a known version,
patchable and openable read-write; a locked exe means the game is running). If anything fails, nothing was changed.
Then, saving `gn_install.json` atomically before the first change and after every step:

1. user.script.txt: reads UTF-16LE(BOM) or ASCII/UTF-8, keeps every line, adds `mod <pack>;`, writes UTF-16LE + BOM + CRLF.
2. Copies mod packs to `data/`.
3. Copies startpos to `data/campaigns/mp_eur_napoleon/startpos.esf` (original saved once in `gn_backup/<same path>`;
   a file identical to ours or written by an earlier install is never taken as an original).
4. Writes the merged `data/local_en_gn.pack` (PFH0 type 2, auto-loaded) from the player's own `text\localisation.loc`.
5. Last: patches Napoleon.exe via temp file + rename. The vanilla copy is `Napoleon.exe.gn_backup` (same name as
   tools/exe_patch.py) and always holds verified vanilla bytes. Already patched: reports it.

Re-running is safe: backups are never overwritten, nothing is backed up twice. After a Steam "verify files", run install again.

## What uninstall does

Needs only the game dir and `gn_install.json`. Every step checks the disk, and state is updated after each one, so a re-run
after a partial failure never deletes what an earlier run restored.
- Restores backed-up files (startpos) and deletes files we added (packs, `local_en_gn.pack`, a startpos that had no original).
  A recorded backup that is gone is a warning: the file is left alone.
- Exe: restored from `Napoleon.exe.gn_backup` only if the backup is the recorded vanilla and the exe is still our patched
  bytes. Already vanilla counts as done; an exe that changed since install (e.g. a Steam update) is left untouched with a warning.
- Removes only our user.script lines (file stays UTF-16LE; deleted if we created it and it is empty), removes empty
  directories the install created and `gn_backup/`, then deletes `gn_install.json`. Errors keep the state file for a retry.

`status` prints paths and per-piece state; exe is vanilla / patched / partially patched / unknown.
