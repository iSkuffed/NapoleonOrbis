package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
)

const appID = "34030"

// ---- Valve KeyValues text (libraryfolders.vdf, appmanifest_*.acf): nested "key" "value" / "key" { ... }.
// Values are string or map[string]any.

func parseVDF(s string) (map[string]any, error) {
	pos := 0
	tok := func() (string, bool, error) { // text, isString, err
		for pos < len(s) && strings.ContainsRune(" \t\r\n", rune(s[pos])) {
			pos++
		}
		if pos >= len(s) {
			return "", false, nil
		}
		switch s[pos] {
		case '{', '}':
			pos++
			return s[pos-1 : pos], false, nil
		case '"':
			var b strings.Builder
			for pos++; pos < len(s) && s[pos] != '"'; pos++ {
				c := s[pos]
				if c == '\\' && pos+1 < len(s) {
					pos++
					c = map[byte]byte{'n': '\n', 't': '\t'}[s[pos]]
					if c == 0 {
						c = s[pos] // \\ \" and unknown escapes: the char itself
					}
				}
				b.WriteByte(c)
			}
			if pos >= len(s) {
				return "", false, fmt.Errorf("vdf: unterminated string")
			}
			pos++
			return b.String(), true, nil
		}
		return "", false, fmt.Errorf("vdf: unexpected %q at %d", s[pos], pos)
	}
	var block func(top bool) (map[string]any, error)
	block = func(top bool) (map[string]any, error) {
		m := map[string]any{}
		for {
			k, isStr, err := tok()
			if err != nil {
				return nil, err
			}
			if k == "" && !isStr { // EOF
				if top {
					return m, nil
				}
				return nil, fmt.Errorf("vdf: missing }")
			}
			if k == "}" && !isStr {
				if top {
					return nil, fmt.Errorf("vdf: stray }")
				}
				return m, nil
			}
			v, vStr, err := tok()
			if err != nil {
				return nil, err
			}
			switch {
			case v == "{" && !vStr:
				if m[k], err = block(false); err != nil {
					return nil, err
				}
			case vStr:
				m[k] = v
			default:
				return nil, fmt.Errorf("vdf: no value for %q", k)
			}
		}
	}
	return block(true)
}

func readVDF(path string) (map[string]any, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return parseVDF(string(b))
}

// libraryPaths: the Steam root plus every path in steamapps/libraryfolders.vdf (new and old formats).
func libraryPaths(root string) []string {
	libs := []string{root}
	vdf, err := readVDF(filepath.Join(root, "steamapps", "libraryfolders.vdf"))
	if err != nil {
		return libs
	}
	lf, _ := vdf["libraryfolders"].(map[string]any)
	for _, v := range lf {
		switch e := v.(type) {
		case map[string]any:
			if p, ok := e["path"].(string); ok {
				libs = append(libs, p)
			}
		case string:
			if filepath.IsAbs(e) { // old format: "1" "D:\Games\Steam" (other string keys are not paths)
				libs = append(libs, e)
			}
		}
	}
	return libs
}

// parseRegSteamPath pulls the SteamPath value out of `reg query ... /v SteamPath` output
// ("    SteamPath    REG_SZ    c:/program files (x86)/steam"); "" if absent.
func parseRegSteamPath(out string) string {
	for _, ln := range strings.Split(out, "\n") {
		if f := strings.SplitN(ln, "REG_SZ", 2); len(f) == 2 && strings.TrimSpace(f[0]) == "SteamPath" {
			if v := strings.TrimSpace(f[1]); v != "" {
				return filepath.FromSlash(v)
			}
		}
	}
	return ""
}

func steamRoots() []string {
	if runtime.GOOS == "windows" {
		roots := []string{}
		if out, err := exec.Command("reg", "query", `HKCU\Software\Valve\Steam`, "/v", "SteamPath").Output(); err == nil {
			if p := parseRegSteamPath(string(out)); p != "" {
				roots = append(roots, p)
			}
		}
		return append(roots, `C:\Program Files (x86)\Steam`)
	}
	h, _ := os.UserHomeDir()
	return []string{
		filepath.Join(h, ".local/share/Steam"),
		filepath.Join(h, ".steam/steam"),
		filepath.Join(h, ".var/app/com.valvesoftware.Steam/.local/share/Steam"),
	}
}

func isGameDir(g string) error {
	for _, p := range []string{"Napoleon.exe", "data"} {
		if _, err := os.Stat(filepath.Join(g, p)); err != nil {
			return fmt.Errorf("%s does not look like a Napoleon install (missing %s)", g, p)
		}
	}
	return nil
}

// findGame returns the game dir and the Steam library that holds it.
func findGame(roots []string) (game, lib string, err error) {
	var firstErr error
	for _, root := range roots {
		for _, l := range libraryPaths(root) {
			acf, e := readVDF(filepath.Join(l, "steamapps", "appmanifest_"+appID+".acf"))
			if e != nil {
				continue
			}
			state, _ := acf["AppState"].(map[string]any)
			dir, _ := state["installdir"].(string)
			if dir == "" {
				continue
			}
			g := filepath.Join(l, "steamapps", "common", dir)
			if e := isGameDir(g); e != nil {
				if firstErr == nil {
					firstErr = e
				}
				continue
			}
			return g, l, nil
		}
	}
	if firstErr != nil {
		return "", "", firstErr
	}
	return "", "", fmt.Errorf("Napoleon: Total War (app %s) not found in any Steam library; use --game DIR", appID)
}

// ciJoin joins path parts under base, matching each existing directory entry case-insensitively
// (Wine/Windows ignore case; keeps "User.script.txt" or "Scripts" as they are on disk).
func ciJoin(base string, parts ...string) string {
	p := base
	for _, part := range parts {
		name := part
		if ents, err := os.ReadDir(p); err == nil {
			for _, e := range ents {
				if strings.EqualFold(e.Name(), part) {
					name = e.Name()
					break
				}
			}
		}
		p = filepath.Join(p, name)
	}
	return p
}

// userScriptPath returns where user.script.txt lives (or should be created).
// On Linux lib is the Steam library whose compatdata holds the Proton prefix.
func userScriptPath(lib string) (string, error) {
	var dir string
	if runtime.GOOS == "windows" {
		appdata := os.Getenv("APPDATA")
		if appdata == "" {
			return "", fmt.Errorf("%%APPDATA%% is not set")
		}
		dir = ciJoin(appdata, "The Creative Assembly", "Napoleon", "scripts")
	} else {
		pfx := filepath.Join(lib, "steamapps", "compatdata", appID, "pfx")
		if _, err := os.Stat(filepath.Join(pfx, "drive_c")); err != nil {
			return "", fmt.Errorf("no Proton prefix at %s: run the game once from Steam first", pfx)
		}
		dir = ciJoin(pfx, "drive_c", "users", "steamuser", "AppData", "Roaming", "The Creative Assembly", "Napoleon", "scripts")
	}
	return ciJoin(dir, "user.script.txt"), nil
}

// locateGame resolves the game dir and the Steam library that holds it. override is --game.
func locateGame(override string, roots []string) (game, lib string, err error) {
	if override == "" {
		return findGame(roots)
	}
	if err = isGameDir(override); err != nil {
		return
	}
	// <lib>/steamapps/common/<name>
	return override, filepath.Dir(filepath.Dir(filepath.Dir(filepath.Clean(override)))), nil
}
