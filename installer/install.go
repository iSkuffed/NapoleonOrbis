package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"slices"
	"strings"
)

const (
	stateFile = "gn_install.json"
	backupDir = "gn_backup"
	locName   = `text\localisation.loc`
	startpos  = "data/campaigns/mp_eur_napoleon/startpos.esf"
	locPack   = "data/local_en_gn.pack"
	exeName   = "Napoleon.exe"
)

// ---- payload: manifest.json + files, from a directory or go:embed (both are an fs.FS).

type Manifest struct {
	Version  string   `json:"version"`
	ModPacks []string `json:"mod_packs"`
	Startpos string   `json:"startpos"`
	LocRows  string   `json:"loc_rows"`
	ExePatch string   `json:"exe_patch"`
}

type patchEntry struct {
	Off       int
	Orig, New []byte
}

type exePatch struct {
	SHA256  string
	Entries []patchEntry
}

type Payload struct {
	FS  fs.FS
	M   Manifest
	Exe exePatch
}

func loadPayload(fsys fs.FS) (*Payload, error) {
	p := &Payload{FS: fsys}
	b, err := fs.ReadFile(fsys, "manifest.json")
	if err != nil {
		return nil, fmt.Errorf("payload: %w", err)
	}
	if err := json.Unmarshal(b, &p.M); err != nil {
		return nil, fmt.Errorf("payload manifest.json: %w", err)
	}
	m := p.M
	if m.Version == "" || len(m.ModPacks) == 0 || m.Startpos == "" || m.LocRows == "" || m.ExePatch == "" {
		return nil, fmt.Errorf("payload manifest.json: version, mod_packs, startpos, loc_rows and exe_patch are all required")
	}
	for _, n := range m.ModPacks {
		if n == "." || n == ".." || filepath.Base(n) != n || path.Base(n) != n {
			return nil, fmt.Errorf("payload: bad mod pack name %q", n)
		}
	}
	b, err = fs.ReadFile(fsys, p.M.ExePatch)
	if err != nil {
		return nil, fmt.Errorf("payload: %w", err)
	}
	var raw struct {
		SHA256 string             `json:"sha256"`
		Groups map[string][][]any `json:"groups"`
	}
	if err := json.Unmarshal(b, &raw); err != nil {
		return nil, fmt.Errorf("payload %s: %w", p.M.ExePatch, err)
	}
	p.Exe.SHA256 = strings.ToLower(raw.SHA256)
	if len(p.Exe.SHA256) != 64 || len(raw.Groups) == 0 {
		return nil, fmt.Errorf("payload %s: needs a sha256 and at least one patch group", p.M.ExePatch)
	}
	for g, list := range raw.Groups {
		for _, e := range list {
			if len(e) != 3 {
				return nil, fmt.Errorf("payload exe patch: bad entry in %s", g)
			}
			off, ok1 := e[0].(float64)
			o, ok2 := e[1].(string)
			n, ok3 := e[2].(string)
			ob, err1 := hex.DecodeString(o)
			nb, err2 := hex.DecodeString(n)
			if !ok1 || !ok2 || !ok3 || err1 != nil || err2 != nil || len(ob) != len(nb) || len(ob) == 0 || off < 0 {
				return nil, fmt.Errorf("payload exe patch: bad entry in %s", g)
			}
			p.Exe.Entries = append(p.Exe.Entries, patchEntry{int(off), ob, nb})
		}
	}
	return p, nil
}

func sum(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }

// set returns a copy of d with each entry's bytes replaced by pick(entry); nil if an entry is out of range.
func (e exePatch) set(d []byte, pick func(patchEntry) []byte) []byte {
	out := bytes.Clone(d)
	for _, x := range e.Entries {
		if x.Off < 0 || x.Off+len(x.Orig) > len(out) {
			return nil
		}
		copy(out[x.Off:], pick(x))
	}
	return out
}

func (e exePatch) apply(d []byte) []byte { return e.set(d, func(x patchEntry) []byte { return x.New }) }
func (e exePatch) restore(d []byte) []byte {
	return e.set(d, func(x patchEntry) []byte { return x.Orig })
}

// classify: "vanilla", "patched" (all new bytes in place), "partial" (vanilla + some other patch set), "unknown".
// vanilla is the exe with every patch range reset to original, only when that hashes to the known sha.
func (e exePatch) classify(d []byte) (kind string, vanilla []byte) {
	if sum(d) == e.SHA256 {
		return "vanilla", d
	}
	if v := e.restore(d); v != nil && sum(v) == e.SHA256 {
		if bytes.Equal(e.apply(v), d) {
			return "patched", v
		}
		return "partial", v
	}
	return "unknown", nil
}

// ---- install state (gn_install.json), saved atomically before the first change and after every step

type State struct {
	Version           string   `json:"version"`
	Files             []string `json:"files_written"` // relative to the game dir, slash separated
	Backups           []string `json:"backups"`       // relative to the game dir
	CreatedDirs       []string `json:"created_dirs"`  // absolute; removed on uninstall if empty
	UserScript        string   `json:"user_script"`
	UserScriptCreated bool     `json:"user_script_created"`
	LinesAdded        []string `json:"lines_added"`
	ExePatched        bool     `json:"exe_patched"`
	ExeVanillaSHA     string   `json:"exe_vanilla_sha256"`
	ExePatchedSHA     string   `json:"exe_patched_sha256"`
}

func loadState(game string) (*State, error) {
	b, err := os.ReadFile(filepath.Join(game, stateFile))
	if err != nil {
		return nil, err
	}
	s := &State{}
	if err := json.Unmarshal(b, s); err != nil {
		return nil, fmt.Errorf("%s is unreadable: %w", stateFile, err)
	}
	return s, nil
}

func (s *State) save(game string) error {
	b, _ := json.MarshalIndent(s, "", "  ")
	return writeAtomic(filepath.Join(game, stateFile), bytes.NewReader(b))
}

func exists(p string) bool { _, err := os.Lstat(p); return err == nil }

func addUniq(l []string, v ...string) []string {
	for _, x := range v {
		if !slices.Contains(l, x) {
			l = append(l, x)
		}
	}
	return l
}

func dropStr(l []string, v string) []string {
	return slices.DeleteFunc(slices.Clone(l), func(x string) bool { return x == v })
}

// writeAtomic writes src to dst via a temp file + rename, so a failed copy never leaves a half-written file.
// The file mode of an existing dst is kept (the exe stays executable).
func writeAtomic(dst string, src io.Reader) error {
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	tmp := dst + ".gn_tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return err
	}
	_, err = io.Copy(f, src)
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if fi, serr := os.Stat(dst); err == nil && serr == nil {
		err = os.Chmod(tmp, fi.Mode().Perm())
	}
	if err == nil {
		err = os.Rename(tmp, dst)
	}
	if err != nil {
		os.Remove(tmp)
	}
	return err
}

func sumFile(open func() (io.ReadCloser, error)) string {
	f, err := open()
	if err != nil {
		return ""
	}
	defer f.Close()
	h := sha256.New()
	io.Copy(h, f)
	return hex.EncodeToString(h.Sum(nil))
}

// ---- install

type plan struct {
	exe, vanilla, patched []byte
	kind                  string
	loc                   []byte // the merged local_en_gn.pack
	locMsg                string
	script, newScript     []byte
	scriptExisted         bool
	added                 []string
}

// preflight validates everything and builds every output in memory. It writes nothing.
func preflight(game, script string, p *Payload) (*plan, error) {
	g := func(rel string) string { return filepath.Join(game, filepath.FromSlash(rel)) }
	if err := isGameDir(game); err != nil {
		return nil, err
	}
	pl := &plan{}
	for _, n := range append([]string{p.M.Startpos}, p.M.ModPacks...) {
		fi, err := fs.Stat(p.FS, n)
		if err != nil || fi.IsDir() {
			return nil, fmt.Errorf("payload: %s is missing or not a file", n)
		}
		f, err := p.FS.Open(n)
		if err != nil {
			return nil, fmt.Errorf("payload: %w", err)
		}
		f.Close()
	}
	tsv, err := fs.ReadFile(p.FS, p.M.LocRows)
	if err != nil {
		return nil, fmt.Errorf("payload: %w", err)
	}
	ours, err := parseTSV(string(tsv))
	if err != nil {
		return nil, err
	}

	// localisation, built in memory from the player's own CA pack
	theirs, err := readPackFile(g("data/local_en_patch.pack"), locName)
	if err != nil {
		return nil, err
	}
	ver, rows, err := parseLoc(theirs)
	if err != nil {
		return nil, fmt.Errorf("local_en_patch.pack %s: %w", locName, err)
	}
	merged := mergeLoc(rows, ours)
	pl.loc = buildPack(2, locName, buildLoc(ver, merged))
	pl.locMsg = fmt.Sprintf("localisation: %d CA rows + %d of ours -> %d rows in %s", len(rows), len(ours), len(merged), locPack)

	// user.script
	cur, rerr := os.ReadFile(script)
	if rerr != nil && !os.IsNotExist(rerr) {
		return nil, rerr
	}
	pl.script, pl.scriptExisted = cur, rerr == nil
	var want []string
	for _, m := range p.M.ModPacks {
		want = append(want, "mod "+m+";")
	}
	var lines []string
	if rerr == nil {
		lines = decodeScript(cur)
	}
	lines, pl.added = addLines(lines, want)
	pl.newScript = encodeScript(lines)

	// exe: must be a known state, patchable, and writable (a locked file means the game is running)
	exePath := g(exeName)
	if pl.exe, err = os.ReadFile(exePath); err != nil {
		return nil, err
	}
	pl.kind, pl.vanilla = p.Exe.classify(pl.exe)
	if pl.kind == "unknown" {
		return nil, fmt.Errorf("Napoleon.exe is not a game version this mod supports (sha256 %s, expected %s).\n"+
			"Nothing was changed. Use Steam's \"Verify integrity of game files\" and try again", sum(pl.exe), p.Exe.SHA256)
	}
	if pl.patched = p.Exe.apply(pl.vanilla); len(pl.patched) != len(pl.vanilla) || len(pl.patched) == 0 {
		return nil, fmt.Errorf("payload %s does not fit this Napoleon.exe", p.M.ExePatch)
	}
	f, err := os.OpenFile(exePath, os.O_RDWR, 0)
	if err != nil {
		return nil, fmt.Errorf("cannot open Napoleon.exe for writing (is the game running? close it and retry): %w", err)
	}
	f.Close()
	return pl, nil
}

func install(game, script string, p *Payload) error {
	g := func(rel string) string { return filepath.Join(game, filepath.FromSlash(rel)) }
	fmt.Println("Close Napoleon: Total War (and its launcher) before installing.")
	old, err := loadState(game)
	if os.IsNotExist(err) {
		old, err = &State{}, nil
	}
	if err != nil {
		return err
	}
	pl, err := preflight(game, script, p)
	if err != nil {
		return err
	}

	st := &State{Version: p.M.Version, Files: old.Files, Backups: old.Backups, CreatedDirs: old.CreatedDirs,
		UserScript: old.UserScript, UserScriptCreated: old.UserScriptCreated, LinesAdded: old.LinesAdded,
		ExePatched: old.ExePatched, ExeVanillaSHA: old.ExeVanillaSHA, ExePatchedSHA: old.ExePatchedSHA}
	save := func() error { return st.save(game) }
	if err := save(); err != nil { // before the first change
		return err
	}
	mk := func(dir string) error { // MkdirAll, remembering the dirs we created
		var missing []string
		for d := dir; !exists(d) && d != filepath.Dir(d); d = filepath.Dir(d) {
			missing = append(missing, d)
		}
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
		st.CreatedDirs = addUniq(st.CreatedDirs, missing...)
		return nil
	}
	// put writes game/rel. With backup, the original is saved once under gn_backup/ (never overwritten, and
	// never taken from a file we wrote ourselves). State records the item before it is touched.
	put := func(rel string, src io.Reader, backup bool) error {
		dst, bak := g(rel), backupDir+"/"+rel
		ours := slices.Contains(old.Files, rel) && !slices.Contains(old.Backups, bak)
		if backup && exists(dst) && !exists(g(bak)) && !ours {
			st.Backups, st.Files = addUniq(st.Backups, bak), addUniq(st.Files, rel)
			if err := save(); err != nil {
				return err
			}
			f, err := os.Open(dst)
			if err != nil {
				return err
			}
			err = writeAtomic(g(bak), f)
			f.Close() // now, not deferred: Windows can't rename over dst below while it is open
			if err != nil {
				return err
			}
		}
		st.Files = addUniq(st.Files, rel)
		if err := mk(filepath.Dir(dst)); err != nil {
			return err
		}
		if err := save(); err != nil {
			return err
		}
		return writeAtomic(dst, src)
	}
	putFS := func(rel, name string, backup bool) error {
		open := func() (io.ReadCloser, error) { return p.FS.Open(name) }
		// a loose file identical to ours is not an original: never back that up
		if backup && sumFile(open) == sumFile(func() (io.ReadCloser, error) { return os.Open(g(rel)) }) {
			backup = false
		}
		f, err := open()
		if err != nil {
			return fmt.Errorf("payload: %w", err)
		}
		defer f.Close()
		return put(rel, f, backup)
	}

	// 3. user.script.txt
	st.UserScript, st.LinesAdded = script, addUniq(st.LinesAdded, pl.added...)
	if !bytes.Equal(pl.newScript, pl.script) {
		st.UserScriptCreated = st.UserScriptCreated || !pl.scriptExisted
		if err := mk(filepath.Dir(script)); err != nil {
			return err
		}
		if err := save(); err != nil {
			return err
		}
		if err := writeAtomic(script, bytes.NewReader(pl.newScript)); err != nil {
			return err
		}
	}
	fmt.Printf("user.script: %s (%d line(s) added)\n", script, len(pl.added))

	// 4. mod packs
	for _, m := range p.M.ModPacks {
		if err := putFS("data/"+m, m, false); err != nil {
			return err
		}
		fmt.Println("pack:", m)
	}
	// 5. startpos (loose file only)
	if err := putFS(startpos, p.M.Startpos, true); err != nil {
		return err
	}
	fmt.Println("startpos: " + startpos)
	// 6. localisation
	if err := put(locPack, bytes.NewReader(pl.loc), false); err != nil {
		return err
	}
	fmt.Println(pl.locMsg)

	// 7. exe patch, last. The backup always holds verified vanilla bytes.
	exePath, exeBak := g(exeName), g(exeName)+".gn_backup"
	st.ExePatched, st.ExeVanillaSHA, st.ExePatchedSHA = true, p.Exe.SHA256, sum(pl.patched)
	st.Backups = addUniq(st.Backups, exeName+".gn_backup")
	if err := save(); err != nil {
		return err
	}
	if b, _ := os.ReadFile(exeBak); sum(b) != p.Exe.SHA256 {
		if err := writeAtomic(exeBak, bytes.NewReader(pl.vanilla)); err != nil {
			return err
		}
	}
	if pl.kind == "patched" {
		fmt.Println("exe: already patched")
	} else if err := writeAtomic(exePath, bytes.NewReader(pl.patched)); err != nil {
		return fmt.Errorf("writing Napoleon.exe (is the game running?): %w", err)
	} else {
		fmt.Println("exe: patched")
	}
	fmt.Println("Install complete.")
	return nil
}

// ---- uninstall: every step looks at what is on disk now, so a re-run after a partial failure is safe.
// State is updated after each step; items already restored are never deleted again.

func uninstall(game string) error {
	g := func(rel string) string { return filepath.Join(game, filepath.FromSlash(rel)) }
	st, err := loadState(game)
	if os.IsNotExist(err) {
		fmt.Println("Nothing to uninstall (no " + stateFile + ").")
		return nil
	} else if err != nil {
		return err
	}
	var errs []error
	fail := func(e error) { errs = append(errs, e); fmt.Println("ERROR:", e) }
	save := func() {
		if e := st.save(game); e != nil {
			fail(e)
		}
	}

	for _, rel := range slices.Clone(st.Files) {
		dst, bakRel := g(rel), backupDir+"/"+rel
		os.Remove(dst + ".gn_tmp")
		switch {
		case exists(g(bakRel)):
			if e := os.Rename(g(bakRel), dst); e != nil {
				fail(fmt.Errorf("restoring %s: %w", rel, e))
				continue
			}
			fmt.Println("restored:", rel)
		case slices.Contains(st.Backups, bakRel):
			// Backup gone: either restored by an earlier run or lost. Never delete in that case.
			fmt.Printf("warning: backup of %s is missing; left as is (Steam's \"Verify integrity\" restores it if it is still modded)\n", rel)
		default:
			if e := os.Remove(dst); e != nil && !os.IsNotExist(e) {
				fail(fmt.Errorf("removing %s: %w", rel, e))
				continue
			}
			fmt.Println("removed:", rel)
		}
		st.Files, st.Backups = dropStr(st.Files, rel), dropStr(st.Backups, bakRel)
		save()
	}

	if st.ExePatched {
		exePath, exeBak := g(exeName), g(exeName)+".gn_backup"
		cur, err := os.ReadFile(exePath)
		if err != nil {
			fail(err)
		} else {
			bb, _ := os.ReadFile(exeBak)
			bakOK, now := sum(bb) == st.ExeVanillaSHA, sum(cur)
			ok := true
			switch {
			case now == st.ExeVanillaSHA:
				fmt.Println("exe: already vanilla")
			case bakOK && now == st.ExePatchedSHA:
				if e := writeAtomic(exePath, bytes.NewReader(bb)); e != nil {
					fail(fmt.Errorf("restoring %s (is the game running?): %w", exeName, e))
					ok = false
				} else {
					fmt.Println("restored:", exeName)
				}
			case bakOK:
				fmt.Println("warning: Napoleon.exe changed since install (a Steam update?); left untouched")
			default:
				fmt.Println("warning: no usable Napoleon.exe backup; use Steam's \"Verify integrity of game files\" to restore the exe")
			}
			if ok {
				if bakOK {
					os.Remove(exeBak)
				}
				st.ExePatched, st.Backups = false, dropStr(st.Backups, exeName+".gn_backup")
				save()
			}
		}
	}

	if st.UserScript != "" {
		b, err := os.ReadFile(st.UserScript)
		ok := true
		switch {
		case err == nil:
			left := removeLines(decodeScript(b), st.LinesAdded)
			if st.UserScriptCreated && len(left) == 0 {
				err = os.Remove(st.UserScript)
			} else if nb := encodeScript(left); !bytes.Equal(nb, b) {
				err = writeAtomic(st.UserScript, bytes.NewReader(nb))
			}
			if err != nil {
				fail(fmt.Errorf("updating user.script: %w", err))
				ok = false
			} else {
				fmt.Println("user.script: removed", len(st.LinesAdded), "line(s)")
			}
		case !os.IsNotExist(err):
			fail(fmt.Errorf("reading user.script: %w", err))
			ok = false
		}
		if ok {
			st.UserScript, st.LinesAdded, st.UserScriptCreated = "", nil, false
			save()
		}
	}

	pruneEmpty(g(backupDir))
	if len(errs) > 0 {
		fmt.Println("Uninstall finished with problems; " + stateFile + " kept so you can fix them and re-run.")
		return errors.Join(errs...)
	}
	dirs := slices.Clone(st.CreatedDirs)
	slices.SortFunc(dirs, func(a, b string) int { return len(b) - len(a) }) // deepest first
	for _, d := range dirs {
		os.Remove(d) // only succeeds if empty
	}
	if e := os.Remove(g(stateFile)); e != nil && !os.IsNotExist(e) {
		return e
	}
	fmt.Println("Uninstall complete.")
	return nil
}

// pruneEmpty removes dir and any empty subdirectories (non-empty ones are left alone).
func pruneEmpty(dir string) {
	ents, _ := os.ReadDir(dir)
	for _, e := range ents {
		if e.IsDir() {
			pruneEmpty(filepath.Join(dir, e.Name()))
		}
	}
	os.Remove(dir)
}

// status prints what is installed. script may be "" when unknown; p may be nil.
func status(game, script string, p *Payload) {
	g := func(rel string) string { return filepath.Join(game, filepath.FromSlash(rel)) }
	st, err := loadState(game)
	if err == nil && st.UserScript != "" {
		script = st.UserScript
	}
	if script == "" {
		script = "(not found)"
	}
	fmt.Println("game:        ", game)
	fmt.Println("user.script: ", script)
	if err != nil {
		fmt.Println("install:      not installed (no " + stateFile + ")")
	} else {
		fmt.Println("install:      recorded, payload version", st.Version)
	}
	if p == nil {
		fmt.Println("(payload not found: per-piece checks skipped)")
		return
	}
	yn := func(ok bool) string { return map[bool]string{true: "installed", false: "NOT installed"}[ok] }
	b, _ := os.ReadFile(script)
	lines := decodeScript(b)
	for _, m := range p.M.ModPacks {
		fi, err := os.Stat(g("data/" + m))
		pi, perr := fs.Stat(p.FS, m)
		fmt.Printf("pack %-24s %s, user.script line %s\n", m, yn(err == nil && perr == nil && fi.Size() == pi.Size()),
			yn(hasLine(lines, "mod "+m+";")))
	}
	sp, _ := fs.ReadFile(p.FS, p.M.Startpos)
	cur, _ := os.ReadFile(g(startpos))
	fmt.Printf("startpos:     %s\n", yn(len(sp) > 0 && bytes.Equal(sp, cur)))
	fmt.Printf("localisation: %s\n", yn(exists(g(locPack))))
	exe, _ := os.ReadFile(g(exeName))
	kind, _ := p.Exe.classify(exe)
	if kind == "partial" {
		kind = "partially patched (re-run install)"
	}
	fmt.Printf("exe:          %s (backup %v)\n", kind, exists(g(exeName+".gn_backup")))
}
