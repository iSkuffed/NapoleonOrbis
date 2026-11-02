Napoleon: Orbis - the whole world for Napoleon: Total War (beta)

Install
1. Close the game.
2. Run the installer (Windows: napoleon-orbis-installer-windows-amd64.exe) and pick 1) Install.
   It finds the Steam copy of the game by itself. If it can't, run it from a command prompt:
   napoleon-orbis-installer-windows-amd64.exe install --game "C:\path\to\Napoleon Total War"
   Linux (Steam + Proton): run the game once first, then ./napoleon-orbis-installer-linux-amd64 install
3. Start the game: Campaigns of the Coalition.

What it changes: adds the mod pack and a names pack to data\, replaces the Coalition campaign's start file
(the original is backed up), adds one line to your user.script.txt, and patches Napoleon.exe so the bigger map works
(the original is kept as Napoleon.exe.gn_backup).

After Steam "verify integrity of game files" or a game update, run Install again.
Uninstall: run the installer and pick 2) Uninstall. Everything goes back to how it was.

Windows may warn that the installer is from an unknown publisher (it is not signed): More info -> Run anyway.

Source, issues and updates: https://github.com/iSkuffed/NapoleonOrbis
