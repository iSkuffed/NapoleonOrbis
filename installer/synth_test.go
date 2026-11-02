package main

import (
	"bytes"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// Synthetic fixtures: no python, no real game files.

type fxOpt struct{ noScript, noStartpos bool }

type fx struct {
	tmp, steam, game, script, payDir string
	p                                *Payload
	exe, vsp                         []byte
}

func writePayload(t *testing.T, dir string, exe []byte) {
	t.Helper()
	var ents []string
	for _, off := range []int{100, 2000} {
		o := exe[off : off+4]
		n := []byte{^o[0], ^o[1], ^o[2], ^o[3]}
		ents = append(ents, fmt.Sprintf("[%d,%q,%q]", off, hex.EncodeToString(o), hex.EncodeToString(n)))
	}
	mustWrite(t, filepath.Join(dir, "exe_patch.json"), []byte(fmt.Sprintf(`{"sha256":%q,"groups":{"a":[%s]}}`, sum(exe), strings.Join(ents, ","))))
	mustWrite(t, filepath.Join(dir, "zz_gn_world.pack"), buildPack(3, `x\y.bin`, []byte("world")))
	mustWrite(t, filepath.Join(dir, "startpos.esf"), []byte("OUR STARTPOS"))
	mustWrite(t, filepath.Join(dir, "loc_rows.tsv"), []byte("key\ttext\ttooltip\nkey0\tours\\tone\\nline\\\\\tfalse\nnew_gn_key\tnew\ttrue\n"))
	mustWrite(t, filepath.Join(dir, "manifest.json"), []byte(`{"version":"synth","mod_packs":["zz_gn_world.pack"],"startpos":"startpos.esf","loc_rows":"loc_rows.tsv","exe_patch":"exe_patch.json"}`))
}

func synthExe() []byte {
	b := make([]byte, 4096)
	for i := range b {
		b[i] = byte(i*31 + 7)
	}
	return b
}

func newFx(t *testing.T, o fxOpt) *fx {
	t.Helper()
	f := &fx{tmp: t.TempDir(), exe: synthExe(), vsp: []byte("VANILLA STARTPOS")}
	f.payDir = filepath.Join(f.tmp, "payload")
	writePayload(t, f.payDir, f.exe)
	var err error
	if f.p, err = loadPayload(os.DirFS(f.payDir)); err != nil {
		t.Fatal(err)
	}
	f.steam = filepath.Join(f.tmp, "Steam")
	f.game = filepath.Join(f.steam, "steamapps/common/Napoleon Total War")
	mustWrite(t, filepath.Join(f.steam, "steamapps/libraryfolders.vdf"), []byte(`"libraryfolders" { "0" { "path" "`+f.steam+`" } }`))
	mustWrite(t, filepath.Join(f.steam, "steamapps/appmanifest_34030.acf"), []byte(`"AppState" { "appid" "34030" "installdir" "Napoleon Total War" }`))
	mustWrite(t, filepath.Join(f.game, "Napoleon.exe"), f.exe)
	var rows []locRow
	for i := 0; i < 10; i++ {
		rows = append(rows, locRow{fmt.Sprintf("key%d", i), fmt.Sprintf("text%d", i), byte(i % 2)})
	}
	mustWrite(t, filepath.Join(f.game, "data/local_en_patch.pack"), buildPack(2, locName, buildLoc(1, rows)))
	if !o.noStartpos {
		mustWrite(t, filepath.Join(f.game, startpos), f.vsp)
	} else {
		os.MkdirAll(filepath.Join(f.game, "data"), 0o755)
	}
	roaming := filepath.Join(f.steam, "steamapps/compatdata/34030/pfx/drive_c/users/steamuser/AppData/Roaming")
	if o.noScript {
		os.MkdirAll(filepath.Join(f.steam, "steamapps/compatdata/34030/pfx/drive_c"), 0o755)
	} else {
		mustWrite(t, filepath.Join(roaming, "The Creative Assembly/Napoleon/scripts/User.script.txt"), encodeScript([]string{"mod keep.pack;", "log keep;"}))
	}
	if runtime.GOOS == "windows" {
		t.Setenv("APPDATA", roaming)
	}
	g, lib, err := locateGame("", []string{f.steam})
	if err != nil || g != f.game {
		t.Fatalf("locateGame: %v %v", g, err)
	}
	if f.script, err = userScriptPath(lib); err != nil {
		t.Fatal(err)
	}
	return f
}

func (f *fx) install(t *testing.T) {
	t.Helper()
	if err := install(f.game, f.script, f.p); err != nil {
		t.Fatal(err)
	}
}

func (f *fx) uninstall(t *testing.T) {
	t.Helper()
	if err := uninstall(f.game); err != nil {
		t.Fatal(err)
	}
}

func TestWriteFixtureForEmbed(t *testing.T) { // used by the embedpayload build check, not a real test
	if dir := os.Getenv("GN_WRITE_FIXTURE"); dir != "" {
		writePayload(t, dir, synthExe())
	}
}

func TestSynthFullCycle(t *testing.T) {
	f := newFx(t, fxOpt{})
	before := snapshot(t, f.tmp)
	f.install(t)
	status(f.game, f.script, f.p)
	if got := string(mustRead(t, filepath.Join(f.game, startpos))); got != "OUR STARTPOS" {
		t.Fatal("startpos:", got)
	}
	if !bytes.Equal(mustRead(t, filepath.Join(f.game, backupDir, startpos)), f.vsp) {
		t.Fatal("startpos backup wrong")
	}
	if sl := decodeScript(mustRead(t, f.script)); len(sl) != 3 || sl[2] != "mod zz_gn_world.pack;" {
		t.Fatalf("user.script: %q", sl)
	}
	lb, _ := readPackFile(filepath.Join(f.game, locPack), locName)
	if _, rows, err := parseLoc(lb); err != nil || len(rows) != 11 || rows[0].Text != "ours\tone\nline\\" || rows[10].Key != "new_gn_key" || rows[3].Text != "text3" {
		t.Fatalf("merged loc wrong: %v %v", err, rows)
	}
	if !bytes.Equal(mustRead(t, filepath.Join(f.game, "Napoleon.exe")), f.p.Exe.apply(f.exe)) {
		t.Fatal("exe not patched")
	}
	if fi, _ := os.Stat(filepath.Join(f.game, "Napoleon.exe")); fi.Mode().Perm() != 0o644 && runtime.GOOS != "windows" {
		t.Fatal("exe mode changed:", fi.Mode())
	}
	mid := snapshot(t, f.tmp)
	f.install(t) // idempotent
	sameTree(t, mid, snapshot(t, f.tmp), "reinstall")
	// Steam "verify files" restores vanilla exe + startpos
	mustWrite(t, filepath.Join(f.game, "Napoleon.exe"), f.exe)
	mustWrite(t, filepath.Join(f.game, startpos), f.vsp)
	f.install(t)
	sameTree(t, mid, snapshot(t, f.tmp), "verify+reinstall")
	f.uninstall(t)
	f.uninstall(t)
	sameTree(t, before, snapshot(t, f.tmp), "uninstall")
}

func TestPreflightLeavesTreeUntouched(t *testing.T) {
	cases := map[string]func(f *fx){
		"missing local_en_patch.pack": func(f *fx) { os.Remove(filepath.Join(f.game, "data/local_en_patch.pack")) },
		"bad TSV header":              func(f *fx) { mustWrite(t, filepath.Join(f.payDir, "loc_rows.tsv"), []byte("a\tb\n")) },
		"duplicate TSV key": func(f *fx) {
			mustWrite(t, filepath.Join(f.payDir, "loc_rows.tsv"), []byte("key\ttext\ttooltip\nk\ta\tfalse\nk\tb\tfalse\n"))
		},
		"payload pack missing": func(f *fx) { os.Remove(filepath.Join(f.payDir, "zz_gn_world.pack")) },
		"unknown exe":          func(f *fx) { mustWrite(t, filepath.Join(f.game, "Napoleon.exe"), append(bytes.Clone(f.exe), 1)) },
		"patch offset out of range": func(f *fx) {
			mustWrite(t, filepath.Join(f.payDir, "exe_patch.json"), []byte(fmt.Sprintf(`{"sha256":%q,"groups":{"a":[[999999,"00","01"]]}}`, sum(f.exe))))
			f.p, _ = loadPayload(os.DirFS(f.payDir))
		},
		"exe not writable": func(f *fx) {
			if runtime.GOOS == "windows" || os.Getuid() == 0 {
				t.Skip("cannot make the exe unwritable here")
			}
			os.Chmod(filepath.Join(f.game, "Napoleon.exe"), 0o444)
		},
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			f := newFx(t, fxOpt{})
			mutate(f)
			before := snapshot(t, f.tmp)
			if err := install(f.game, f.script, f.p); err == nil {
				t.Fatal("install succeeded")
			} else {
				t.Log(err)
			}
			sameTree(t, before, snapshot(t, f.tmp), name)
		})
	}
	// manifest problems are caught while loading
	for name, m := range map[string]string{
		"empty version": `{"version":"","mod_packs":["a.pack"],"startpos":"s","loc_rows":"l","exe_patch":"e"}`,
		"dot pack name": `{"version":"1","mod_packs":[".."],"startpos":"s","loc_rows":"l","exe_patch":"e"}`,
		"no packs":      `{"version":"1","mod_packs":[],"startpos":"s","loc_rows":"l","exe_patch":"e"}`,
	} {
		f := newFx(t, fxOpt{})
		mustWrite(t, filepath.Join(f.payDir, "manifest.json"), []byte(m))
		if _, err := loadPayload(os.DirFS(f.payDir)); err == nil {
			t.Errorf("%s accepted", name)
		}
	}
}

func TestPartialUninstallThenRerun(t *testing.T) {
	f := newFx(t, fxOpt{})
	before := snapshot(t, f.tmp)
	f.install(t)
	// make the user.script step fail: a directory sits where the file is
	script := mustRead(t, f.script)
	os.Remove(f.script)
	os.Mkdir(f.script, 0o755)
	if err := uninstall(f.game); err == nil {
		t.Fatal("expected an error")
	}
	if !exists(filepath.Join(f.game, stateFile)) {
		t.Fatal("state must be kept after a partial failure")
	}
	if !bytes.Equal(mustRead(t, filepath.Join(f.game, startpos)), f.vsp) {
		t.Fatal("startpos not restored by run 1")
	}
	// run 2 with the problem still there must not delete the restored startpos or fail on the exe
	if err := uninstall(f.game); err == nil {
		t.Fatal("expected an error again")
	}
	if !bytes.Equal(mustRead(t, filepath.Join(f.game, startpos)), f.vsp) || sum(mustRead(t, filepath.Join(f.game, "Napoleon.exe"))) != sum(f.exe) {
		t.Fatal("run 2 damaged restored files")
	}
	os.Remove(f.script)
	mustWrite(t, f.script, script)
	f.uninstall(t)
	sameTree(t, before, snapshot(t, f.tmp), "final")
}

func TestUninstallExeChangedAfterInstall(t *testing.T) {
	f := newFx(t, fxOpt{})
	before := snapshot(t, f.tmp)
	f.install(t)
	newer := append(bytes.Clone(f.exe), 9, 9) // e.g. a Steam update
	mustWrite(t, filepath.Join(f.game, "Napoleon.exe"), newer)
	f.uninstall(t)
	if !bytes.Equal(mustRead(t, filepath.Join(f.game, "Napoleon.exe")), newer) {
		t.Fatal("changed exe was touched")
	}
	after := snapshot(t, f.tmp)
	if after["Steam/steamapps/common/Napoleon Total War/Napoleon.exe"] != sum(newer) {
		t.Fatal("exe hash")
	}
	delete(after, "Steam/steamapps/common/Napoleon Total War/Napoleon.exe")
	delete(before, "Steam/steamapps/common/Napoleon Total War/Napoleon.exe")
	sameTree(t, before, after, "rest of tree")
}

func TestUninstallMissingBackups(t *testing.T) {
	// exe already vanilla and its backup gone: counts as done, everything else restored
	f := newFx(t, fxOpt{})
	before := snapshot(t, f.tmp)
	f.install(t)
	mustWrite(t, filepath.Join(f.game, "Napoleon.exe"), f.exe)
	os.Remove(filepath.Join(f.game, "Napoleon.exe.gn_backup"))
	f.uninstall(t)
	sameTree(t, before, snapshot(t, f.tmp), "vanilla exe, no backup")

	// both backups lost: nothing is deleted or downgraded, no error, state removed
	f = newFx(t, fxOpt{})
	f.install(t)
	os.Remove(filepath.Join(f.game, "Napoleon.exe.gn_backup"))
	os.Remove(filepath.Join(f.game, backupDir, startpos))
	f.uninstall(t)
	if string(mustRead(t, filepath.Join(f.game, startpos))) != "OUR STARTPOS" || !bytes.Equal(mustRead(t, filepath.Join(f.game, "Napoleon.exe")), f.p.Exe.apply(f.exe)) {
		t.Fatal("files with lost backups must be left alone")
	}
	if exists(filepath.Join(f.game, stateFile)) || exists(filepath.Join(f.game, "data/zz_gn_world.pack")) {
		t.Fatal("state or added files left behind")
	}
}

func TestUserScriptCreatedThenDeleted(t *testing.T) {
	f := newFx(t, fxOpt{noScript: true})
	before := snapshot(t, f.tmp)
	f.install(t)
	b := mustRead(t, f.script)
	if !bytes.HasPrefix(b, []byte{0xff, 0xfe}) || len(decodeScript(b)) != 1 {
		t.Fatal("user.script not created as UTF-16LE with our line")
	}
	f.uninstall(t)
	sameTree(t, before, snapshot(t, f.tmp), "uninstall (incl. created dirs)")
}

func TestNoOriginalStartpos(t *testing.T) {
	f := newFx(t, fxOpt{noStartpos: true})
	before := snapshot(t, f.tmp)
	f.install(t)
	f.install(t) // must not back up our own file
	if exists(filepath.Join(f.game, backupDir, startpos)) {
		t.Fatal("our own startpos was backed up")
	}
	f.uninstall(t)
	sameTree(t, before, snapshot(t, f.tmp), "uninstall")
}

func TestRegParserAndCaseInsensitiveJoin(t *testing.T) {
	out := "\r\nHKEY_CURRENT_USER\\Software\\Valve\\Steam\r\n    SteamPath    REG_SZ    c:/program files (x86)/steam\r\n\r\n"
	if got, want := parseRegSteamPath(out), filepath.FromSlash("c:/program files (x86)/steam"); got != want {
		t.Fatalf("got %q want %q", got, want)
	}
	if parseRegSteamPath("ERROR: not found\r\n") != "" || parseRegSteamPath("    Other    REG_SZ    x\n") != "" {
		t.Fatal("parsed garbage")
	}
	d := t.TempDir()
	mustWrite(t, filepath.Join(d, "The CREATIVE Assembly/Scripts/User.Script.TXT"), nil)
	want := filepath.Join(d, "The CREATIVE Assembly/Scripts/User.Script.TXT")
	if got := ciJoin(d, "The Creative Assembly", "scripts", "user.script.txt"); got != want {
		t.Fatalf("got %q", got)
	}
	if got := ciJoin(d, "new", "x"); got != filepath.Join(d, "new", "x") {
		t.Fatalf("got %q", got)
	}
}
