#!/usr/bin/env bash
# Drive Napoleon: Total War headless (Proton inside a headless gamescope session).
#
#   tools/ntw.sh start [-- game args]   launch in the background (one session at a time)
#   tools/ntw.sh shot NAME              screenshot -> work/session/NAME.png
#   tools/ntw.sh key KEY...             xdotool key names, e.g. Escape Return
#   tools/ntw.sh hold KEY SECONDS      hold a key, e.g. camera pan with Up/Right
#   tools/ntw.sh click X Y              left click at 1920x1080 screen coords
#   tools/ntw.sh coalition [WAIT] [FACTION]  after start: menus -> Coalition map (austria|britain|prussia|russia)
#   tools/ntw.sh turns N [MAXMIN]      end N turns; each waits until the HUD date changes (prints seconds) or MAXMIN (20)
#   tools/ntw.sh status                 running | exited
#   tools/ntw.sh stop                   kill the game and the session
#
# Session files live in work/session/: session.env (in-session env), gamescope.log, steam-34030.log.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
S="$ROOT/work/session"
GAME="$HOME/.local/share/Steam/steamapps/common/Napoleon Total War"
PROTON="$HOME/.local/share/Steam/compatibilitytools.d/GE-Proton11-5-x86_64/proton"

envval() { grep -m1 "^$1=" "$S/session.env" 2>/dev/null | cut -d= -f2-; }
running() { [ -f "$S/gamescope.pid" ] && kill -0 "$(cat "$S/gamescope.pid")" 2>/dev/null; }
x() { DISPLAY=$(envval DISPLAY) xdotool "$@"; }

case "${1:-}" in
start)
  shift; [ "${1:-}" = "--" ] && shift
  running && { echo "already running"; exit 1; }
  rm -rf "$S"; mkdir -p "$S"
  export STEAM_COMPAT_CLIENT_INSTALL_PATH="$HOME/.local/share/Steam"
  export STEAM_COMPAT_DATA_PATH="$HOME/.local/share/Steam/steamapps/compatdata/34030"
  export SteamAppId=34030 SteamGameId=34030 PROTON_LOG=1 PROTON_LOG_DIR="$S"
  cd "$GAME" || exit 1
  setsid gamescope --backend headless -W 1920 -H 1080 -w 1920 -h 1080 -r 60 -- \
    bash -c 'env > "$0/session.env"; exec "$1" run ./Napoleon.exe "${@:2}"' "$S" "$PROTON" "$@" \
    > "$S/gamescope.log" 2>&1 < /dev/null &
  echo $! > "$S/gamescope.pid"
  for _ in $(seq 30); do [ -s "$S/session.env" ] && break; sleep 1; done
  echo "started pid $(cat "$S/gamescope.pid")" ;;
shot)
  GAMESCOPE_WAYLAND_DISPLAY=$(envval GAMESCOPE_WAYLAND_DISPLAY) XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)} \
    gamescopectl screenshot "$S/$2.png" >/dev/null 2>&1
  for _ in $(seq 20); do [ -s "$S/$2.png" ] && break; sleep 0.25; done
  [ -s "$S/$2.png" ] || { echo "no screenshot"; exit 1; }
  magick "$S/$2.png" -resize 50% "$S/$2_half.png" && echo "$S/$2_half.png (half size: multiply coords by 2)" ;;
key)
  shift; for k in "$@"; do x key --clearmodifiers "$k"; sleep 0.4; done ;;
hold)  # hold KEY for SECONDS (camera pan etc.)
  x keydown "$2"; sleep "$3"; x keyup "$2" ;;
click)
  x mousemove "$2" "$3"; sleep 0.2; x click 1 ;;
coalition)  # from a fresh start: skip intros, open Campaigns of the Coalition, start as FACTION (default austria)
  sleep 25; "$0" key Escape Escape Escape; sleep 8
  "$0" click 958 389; sleep 4; "$0" click 958 594; sleep 6
  case "${3:-austria}" in britain) "$0" click 872 216;; prussia) "$0" click 1044 216;; russia) "$0" click 1214 216;; esac
  sleep 2; "$0" click 958 974
  sleep "${2:-50}"; "$0" status ;;
turns)  # date text (HUD bottom right), thresholded so AI-turn HUD dimming does not count; popups dismissed while waiting
  datesum() {  # fails on a half-written screenshot, so a bad read never counts as a date change
    "$0" shot _date >/dev/null 2>&1 && magick "$S/_date.png" -crop 85x55+1503+935 +repage -colorspace gray -threshold 45% \
      -depth 1 "$S/_date.gray" 2>/dev/null && md5sum < "$S/_date.gray"; }
  battle() {  # pre-battle panel (AI attacked us): both side panels flat grey and identical; terrain is darker and busier
    magick "$S/_date.png" \( -clone 0 -crop 400x200+25+600 \) \( -clone 0 -crop 400x200+1490+600 \) -delete 0 +repage \
      -colorspace gray -format '%[fx:mean] %[fx:standard_deviation]\n' info: 2>/dev/null |
      awk 'NR==1{m=$1} {ok+=($1>0.68 && $2<0.025)} END{exit !(ok==2 && (m-$1)^2<0.0001)}'; }
  "$0" click 392 64   # close the "Where to Start?" advisor if open
  resolve() {  # auto-resolve; screenshots kept so the results screen handling can be checked
    echo "turn $t: battle, auto-resolving"; cp "$S/_date.png" "$S/battle_$t.png"; "$0" click 997 1027; sleep 6
    "$0" shot battle_${t}_after >/dev/null; "$0" click 920 972; sleep 3; }   # results panel: tick (close)
  for t in $(seq "$2"); do
    until d0=$(datesum) && ! { battle && resolve; }; do sleep 1; done; s0=$(date +%s); "$0" click 1540 1030; r=stuck
    while [ $(( $(date +%s) - s0 )) -lt $(( ${3:-20} * 60 )) ]; do
      sleep 10; running || { r=exited; break; }
      for k in 1 2 3; do "$0" click 994 736; sleep 0.5; done; "$0" click 1542 74
      "$0" click 960 716    # diplomacy "War Declared" panel: tick
      "$0" click 1636 530   # "Surrender demanded" (AI besieges us): tick = surrender, keeps the AI turn moving
      d=$(datesum) || continue
      battle && { resolve; continue; }
      [ "$d" != "$d0" ] && { r=ok; break; }
    done
    echo "turn $t: $r $(( $(date +%s) - s0 ))s"; [ $r = ok ] || break
  done ;;
status)
  running && echo running || echo exited ;;
stop)
  pgid=$(cat "$S/gamescope.pid" 2>/dev/null)
  pkill -f '^[A-Z]:.*Napoleon\.exe|^\./Napoleon\.exe' 2>/dev/null; sleep 3
  [ -n "$pgid" ] && { kill -- "-$pgid" 2>/dev/null; sleep 2; kill -9 -- "-$pgid" 2>/dev/null; }
  for r in $(pgrep -f '^gamescopereaper .*Napoleon\.exe'); do pkill -9 -P "$r"; kill -9 "$r"; done 2>/dev/null
  WINEPREFIX="$HOME/.local/share/Steam/steamapps/compatdata/34030/pfx" "$(dirname "$PROTON")/files/bin/wineserver" -k 2>/dev/null
  echo stopped ;;
*) sed -n '2,12p' "$0"; exit 2 ;;
esac
