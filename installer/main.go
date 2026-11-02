// Napoleon: Orbis installer: install | uninstall | status.
package main

import (
	"bufio"
	"flag"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
)

var stdin = bufio.NewReader(os.Stdin)

func readLine() string { s, _ := stdin.ReadString('\n'); return strings.TrimSpace(s) }

// openPayload: --payload DIR, else the embedded payload (build tag embedpayload), else payload/ next to the binary.
func openPayload(dir string) (*Payload, error) {
	var fsys fs.FS
	switch {
	case dir != "":
		fsys = os.DirFS(dir)
	case embeddedPayload() != nil:
		fsys = embeddedPayload()
	default:
		exe, _ := os.Executable()
		fsys = os.DirFS(filepath.Join(filepath.Dir(exe), "payload"))
	}
	return loadPayload(fsys)
}

func run(cmd, game, payloadDir string, yes bool) error {
	gamePath, lib, err := locateGame(game, steamRoots())
	if err != nil {
		return err
	}
	switch cmd {
	case "status":
		p, _ := openPayload(payloadDir)
		script, err := userScriptPath(lib) // optional here: status prints "(not found)" if it fails
		if err != nil {
			script = ""
		}
		status(gamePath, script, p)
		return nil
	case "install", "uninstall":
		fmt.Printf("Game: %s\n", gamePath)
		var p *Payload
		var script string
		if cmd == "install" {
			if p, err = openPayload(payloadDir); err != nil {
				return err
			}
			if script, err = userScriptPath(lib); err != nil {
				return err
			}
		}
		if !yes {
			fmt.Printf("%s? [y/N] ", cmd)
			if a := strings.ToLower(readLine()); a != "y" && a != "yes" {
				fmt.Println("Cancelled.")
				return nil
			}
		}
		if cmd == "install" {
			return install(gamePath, script, p)
		}
		return uninstall(gamePath)
	}
	return fmt.Errorf("unknown command %q (use install, uninstall or status)", cmd)
}

func main() {
	if len(os.Args) == 1 { // double-click: tiny menu, then wait so the console window stays open
		fmt.Print("Napoleon: Orbis installer\n  1) Install\n  2) Uninstall\n  3) Status\nChoose: ")
		cmd := map[string]string{"1": "install", "2": "uninstall", "3": "status"}[readLine()]
		err := fmt.Errorf("no such option")
		if cmd != "" {
			err = run(cmd, "", "", false)
		}
		if err != nil {
			fmt.Println("Error:", err)
		}
		fmt.Print("Press Enter to exit.")
		readLine()
		return
	}
	fl := flag.NewFlagSet("gninstall", flag.ExitOnError)
	game := fl.String("game", "", "Napoleon install dir (default: auto-detect via Steam)")
	payload := fl.String("payload", "", "payload dir (default: embedded, else payload/ next to this program)")
	yes := fl.Bool("yes", false, "do not ask for confirmation")
	fl.Usage = func() {
		fmt.Fprintln(os.Stderr, "usage: installer install|uninstall|status [--game DIR] [--payload DIR] [--yes]")
		fl.PrintDefaults()
	}
	fl.Parse(os.Args[1:]) // flags may come before the command ...
	cmd := fl.Arg(0)
	fl.Parse(fl.Args()[min(1, fl.NArg()):]) // ... or after it
	if cmd == "" || fl.NArg() > 0 {
		fl.Usage()
		os.Exit(2)
	}
	if err := run(cmd, *game, *payload, *yes); err != nil {
		fmt.Fprintln(os.Stderr, "Error:", err)
		os.Exit(1)
	}
}
