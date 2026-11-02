package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

var (
	repo     = filepath.Join("..")
	python   = filepath.Join(repo, ".venv/bin/python")
	realGame = filepath.Join(os.Getenv("HOME"), ".local/share/Steam/steamapps/common/Napoleon Total War")
)

func py(t *testing.T, args ...string) string {
	t.Helper()
	out, err := exec.Command(python, args...).CombinedOutput()
	if err != nil {
		t.Fatalf("python %v: %v\n%s", args, err, out)
	}
	return string(out)
}

func pyStdout(t *testing.T, args ...string) []byte {
	t.Helper()
	out, err := exec.Command(python, args...).Output()
	if err != nil {
		t.Fatalf("python %v: %v", args, err)
	}
	return out
}

func mustRead(t *testing.T, p string) []byte {
	t.Helper()
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func mustWrite(t *testing.T, p string, b []byte) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, b, 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestVDF(t *testing.T) {
	v, err := parseVDF("\"libraryfolders\"\n{\n\t\"0\"\n\t{\n\t\t\"path\"\t\t\"C:\\\\Program Files (x86)\\\\Steam\"\n\t\t\"apps\" { \"34030\" \"123\" }\n\t}\n\t\"1\" { \"path\" \"/mnt/games\" }\n}\n")
	if err != nil {
		t.Fatal(err)
	}
	lf := v["libraryfolders"].(map[string]any)
	if p := lf["0"].(map[string]any)["path"]; p != `C:\Program Files (x86)\Steam` {
		t.Fatalf("path = %q", p)
	}
	if p := lf["1"].(map[string]any)["path"]; p != "/mnt/games" {
		t.Fatalf("path = %q", p)
	}
	acf, err := parseVDF(`"AppState" { "appid" "34030" "installdir" "Napoleon Total War" "UserConfig" { "language" "english" } }`)
	if err != nil || acf["AppState"].(map[string]any)["installdir"] != "Napoleon Total War" {
		t.Fatalf("acf: %v %v", acf, err)
	}
	if _, err := parseVDF(`"a" { "b" "c"`); err == nil {
		t.Fatal("unterminated block accepted")
	}
}

func TestUserScript(t *testing.T) {
	orig := encodeScript([]string{"mod other.pack;", "", "something else"})
	lines := decodeScript(orig)
	lines2, added := addLines(lines, []string{"mod zz.pack;", "mod other.pack;"})
	if len(added) != 1 || added[0] != "mod zz.pack;" || len(lines2) != 4 {
		t.Fatalf("add: %v %v", lines2, added)
	}
	enc := encodeScript(lines2)
	if !bytes.HasPrefix(enc, []byte{0xff, 0xfe}) || !bytes.Contains(enc, []byte("\r\x00\n\x00")) {
		t.Fatal("not UTF-16LE BOM + CRLF")
	}
	if got := encodeScript(removeLines(decodeScript(enc), added)); !bytes.Equal(got, orig) {
		t.Fatal("remove did not restore original bytes")
	}
	// ASCII/UTF-8 input (LF and CRLF) is converted and kept
	if got := decodeScript([]byte("mod a;\r\nmod b;\n")); len(got) != 2 || got[1] != "mod b;" {
		t.Fatalf("ascii: %q", got)
	}
}

func TestPackAndLocRealRoundTrip(t *testing.T) {
	realPack := filepath.Join(realGame, "data/local_en_patch.pack")
	if !exists(realPack) {
		t.Skip("real local_en_patch.pack not available")
	}
	tmp := t.TempDir()
	py(t, filepath.Join(repo, "tools/packtool.py"), "extract", realPack, tmp, "text/localisation.loc")
	want := mustRead(t, filepath.Join(tmp, "text/localisation.loc"))
	got, err := readPackFile(realPack, locName)
	if err != nil || !bytes.Equal(got, want) {
		t.Fatalf("readPackFile differs from packtool extract: %v", err)
	}
	ver, rows, err := parseLoc(want)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(buildLoc(ver, rows), want) {
		t.Fatalf("LOC round trip not byte-exact (%d rows)", len(rows))
	}
	t.Logf("LOC round trip exact: %d rows, %d bytes", len(rows), len(want))

	// our pack is readable by tools/packtool.py
	out := filepath.Join(tmp, "x.pack")
	mustWrite(t, out, buildPack(2, locName, want))
	list := py(t, filepath.Join(repo, "tools/packtool.py"), "list", out)
	if !strings.Contains(list, "text\\localisation.loc") || !strings.Contains(list, "type=2") {
		t.Fatalf("packtool list: %s", list)
	}
}

func snapshot(t *testing.T, root string) map[string]string {
	t.Helper()
	m := map[string]string{}
	filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		rel, _ := filepath.Rel(root, p)
		if d.IsDir() {
			m[rel+"/"] = ""
		} else {
			h := sha256.Sum256(mustRead(t, p))
			m[rel] = hex.EncodeToString(h[:])
		}
		return nil
	})
	return m
}

func sameTree(t *testing.T, a, b map[string]string, what string) {
	t.Helper()
	for k, v := range a {
		if w, ok := b[k]; !ok || v != w {
			t.Errorf("%s: %s changed or missing", what, k)
		}
	}
	for k := range b {
		if _, ok := a[k]; !ok {
			t.Errorf("%s: extra %s", what, k)
		}
	}
}

func TestInstallUninstallRealFiles(t *testing.T) {
	realExe := filepath.Join(realGame, "Napoleon.exe")
	if b := realExe + ".gn_backup"; exists(b) && sum(mustRead(t, realExe)) != "44880ec1770f600163a336eec83b4366901484c5cceec83dc326e2932f02a054" {
		realExe = b // the game exe is currently patched; the backup is the vanilla copy (read-only use)
	}
	realPack := filepath.Join(realGame, "data/local_en_patch.pack")
	vanillaSP := filepath.Join(repo, "work/vanilla_loose_backup/campaigns/mp_eur_napoleon/startpos.esf")
	for _, p := range []string{realExe, realPack, vanillaSP, python} {
		if !exists(p) {
			t.Skip("missing real fixture " + p)
		}
	}
	tmp := t.TempDir()

	// payload, with exe_patch.json from the reference tool
	pay := filepath.Join(tmp, "payload")
	mustWrite(t, filepath.Join(pay, "exe_patch.json"), pyStdout(t, filepath.Join(repo, "tools/exe_patch.py"), "json"))
	mustWrite(t, filepath.Join(pay, "zz_gn_world.pack"), buildPack(3, `x\y.bin`, []byte("world")))
	mustWrite(t, filepath.Join(pay, "startpos.esf"), []byte("OUR STARTPOS"))
	_, rows, _ := parseLoc(func() []byte { b, _ := readPackFile(realPack, locName); return b }())
	mustWrite(t, filepath.Join(pay, "loc_rows.tsv"), []byte("key\ttext\ttooltip\n"+rows[0].Key+"\tours\\tone\\nline\\\\\tfalse\nnew_gn_key\tnew\ttrue\n"))
	mustWrite(t, filepath.Join(pay, "manifest.json"), []byte(`{"version":"t1","mod_packs":["zz_gn_world.pack"],"startpos":"startpos.esf","loc_rows":"loc_rows.tsv","exe_patch":"exe_patch.json"}`))
	p, err := loadPayload(os.DirFS(pay))
	if err != nil {
		t.Fatal(err)
	}
	exeBytes := mustRead(t, realExe)
	if sum(exeBytes) != p.Exe.SHA256 {
		t.Skip("no vanilla Napoleon.exe available")
	}

	// fake Steam root + library + game
	steam := filepath.Join(tmp, "Steam")
	game := filepath.Join(steam, "steamapps/common/Napoleon Total War")
	mustWrite(t, filepath.Join(steam, "steamapps/libraryfolders.vdf"),
		[]byte(`"libraryfolders" { "0" { "path" "`+steam+`" } }`))
	mustWrite(t, filepath.Join(steam, "steamapps/appmanifest_34030.acf"),
		[]byte(`"AppState" { "appid" "34030" "installdir" "Napoleon Total War" }`))
	mustWrite(t, filepath.Join(game, "Napoleon.exe"), exeBytes)
	mustWrite(t, filepath.Join(game, "data/local_en_patch.pack"), mustRead(t, realPack))
	vsp := mustRead(t, vanillaSP)
	mustWrite(t, filepath.Join(game, startpos), vsp)
	scriptDir := filepath.Join(steam, "steamapps/compatdata/34030/pfx/drive_c/users/steamuser/AppData/Roaming/The Creative Assembly/Napoleon/scripts")
	mustWrite(t, filepath.Join(scriptDir, "User.script.txt"), encodeScript([]string{"mod keep.pack;", "log keep;"}))
	if runtime.GOOS == "windows" {
		t.Setenv("APPDATA", filepath.Join(steam, "steamapps/compatdata/34030/pfx/drive_c/users/steamuser/AppData/Roaming"))
	}
	before := snapshot(t, tmp)

	gamePath, lib, err := locateGame("", []string{filepath.Join(tmp, "nope"), steam})
	script, serr := userScriptPath(lib)
	if err != nil || serr != nil || gamePath != game || filepath.Base(script) != "User.script.txt" {
		t.Fatalf("locate: %v %v %v %v", gamePath, script, err, serr)
	}
	if g2, l2, err := locateGame(game, nil); err != nil || g2 != game || l2 != lib {
		t.Fatalf("locate --game: %v %v %v", g2, l2, err)
	}

	if err := install(game, script, p); err != nil {
		t.Fatal(err)
	}
	status(game, script, p)

	// startpos, packs, user.script
	if string(mustRead(t, filepath.Join(game, startpos))) != "OUR STARTPOS" {
		t.Fatal("startpos not installed")
	}
	if !bytes.Equal(mustRead(t, filepath.Join(game, backupDir, startpos)), vsp) {
		t.Fatal("startpos backup wrong")
	}
	sl := decodeScript(mustRead(t, script))
	if len(sl) != 3 || sl[2] != "mod zz_gn_world.pack;" {
		t.Fatalf("user.script: %q", sl)
	}
	// merged localisation: replaced in place, ours appended, rest untouched
	lb, err := readPackFile(filepath.Join(game, locPack), locName)
	if err != nil {
		t.Fatal(err)
	}
	_, mrows, err := parseLoc(lb)
	if err != nil || len(mrows) != len(rows)+1 || mrows[0].Text != "ours\tone\nline\\" || mrows[len(rows)].Key != "new_gn_key" || mrows[5] != rows[5] {
		t.Fatalf("merged loc wrong: %v rows=%d", err, len(mrows))
	}
	py(t, filepath.Join(repo, "tools/packtool.py"), "list", filepath.Join(game, locPack))
	// exe equals the reference tool's output on another copy
	ref := filepath.Join(tmp, "ref_Napoleon.exe")
	mustWrite(t, ref, exeBytes)
	py(t, filepath.Join(repo, "tools/exe_patch.py"), "patch", "--exe", ref)
	if !bytes.Equal(mustRead(t, filepath.Join(game, "Napoleon.exe")), mustRead(t, ref)) {
		t.Fatal("patched exe differs from exe_patch.py output")
	}
	os.Remove(ref)
	os.Remove(ref + ".gn_backup")

	// re-install is idempotent: nothing changes
	mid := snapshot(t, tmp)
	if err := install(game, script, p); err != nil {
		t.Fatal(err)
	}
	sameTree(t, mid, snapshot(t, tmp), "reinstall")

	// Steam "verify files" restores vanilla exe + startpos; reinstall patches again, backups stay vanilla
	mustWrite(t, filepath.Join(game, "Napoleon.exe"), exeBytes)
	mustWrite(t, filepath.Join(game, startpos), vsp)
	if err := install(game, script, p); err != nil {
		t.Fatal(err)
	}
	sameTree(t, mid, snapshot(t, tmp), "after verify+reinstall")

	// unknown exe: refused before anything else changes
	mustWrite(t, filepath.Join(game, "Napoleon.exe"), append(bytes.Clone(exeBytes), 1))
	mid2 := snapshot(t, tmp)
	if err := install(game, script, p); err == nil || !strings.Contains(err.Error(), "not a game version") {
		t.Fatalf("unknown exe accepted: %v", err)
	}
	sameTree(t, mid2, snapshot(t, tmp), "refused install")
	mustWrite(t, filepath.Join(game, "Napoleon.exe"), p.Exe.apply(exeBytes))

	// uninstall (twice): everything back byte-identical, nothing left over
	for i := 0; i < 2; i++ {
		if err := uninstall(game); err != nil {
			t.Fatal(err)
		}
	}
	sameTree(t, before, snapshot(t, tmp), "uninstall")
	if sum(mustRead(t, filepath.Join(game, "Napoleon.exe"))) != p.Exe.SHA256 {
		t.Fatal("exe not vanilla after uninstall")
	}
}

// The release payload (installer/release.sh makes payload/ before go test) must load as the installer reads it.
func TestReleasePayloadLoads(t *testing.T) {
	if !exists("payload/manifest.json") {
		t.Skip("no payload/ (made by tools/make_payload.py)")
	}
	if _, err := loadPayload(os.DirFS("payload")); err != nil {
		t.Fatal(err)
	}
}
