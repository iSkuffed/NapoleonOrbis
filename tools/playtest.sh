#!/usr/bin/env bash
# Install a built world for a human playtest, then put the game back.
#   tools/playtest.sh install [WORLD]   default WORLD = pt_w14 = frozen copy of the w9 build (Europe splits, borders, split poi neighbours) = release 0.9.0 (needs work/world/WORLD and work/mods/WORLD{,_loc})
#   tools/playtest.sh uninstall         vanilla startpos, no loc pack, exe restored
#   tools/playtest.sh status
# Play: Steam -> Napoleon -> Campaigns -> Campaigns of the Coalition (Britain, Austria, Prussia or Russia).
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
G="$HOME/.local/share/Steam/steamapps/common/Napoleon Total War/data"
SP="$G/campaigns/mp_eur_napoleon/startpos.esf"; VAN=work/vanilla_loose_backup/campaigns/mp_eur_napoleon/startpos.esf
PY=.venv/bin/python
case "${1:-}" in
install)
  W="${2:-pt_w14}"
  pgrep -f 'Napoleon\.exe' >/dev/null && { echo "close the game first"; exit 1; }
  for p in "work/world/$W/startpos.esf" "work/mods/$W" "work/mods/${W}_loc"; do [ -e "$p" ] || { echo "missing $p"; exit 1; }; done
  $PY tools/packtool.py build "$G/zz_gn_world.pack" "work/mods/$W" >/dev/null
  $PY tools/packtool.py build --type 2 "$G/local_en_gn.pack" "work/mods/${W}_loc" >/dev/null
  cp "work/world/$W/startpos.esf" "$SP"
  $PY tools/exe_patch.py patch >/dev/null
  echo "installed $W"; "$0" status ;;
uninstall)
  pgrep -f 'Napoleon\.exe' >/dev/null && { echo "close the game first"; exit 1; }
  cp "$VAN" "$SP"; cmp -s "$VAN" "$SP"; rm -f "$G/local_en_gn.pack"
  $PY tools/exe_patch.py restore >/dev/null
  echo "uninstalled"; "$0" status ;;
status)
  cmp -s "$VAN" "$SP" && echo "startpos: vanilla" || echo "startpos: modded"
  [ -f "$G/local_en_gn.pack" ] && echo "loc pack: installed" || echo "loc pack: none"
  $PY tools/exe_patch.py status ;;
*) sed -n '2,6p' "$0"; exit 2 ;;
esac
