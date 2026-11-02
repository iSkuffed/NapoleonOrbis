#!/bin/bash
# Run a script from tools/ghidra against the analysed exe (work/ghidra/ntw, made by:
#   analyzeHeadless work/ghidra ntw -import work/ghidra/Napoleon.exe -max-cpu 4).  Script output only.
cd "$(dirname "$0")/../.."
S=$1; shift
GHIDRA_HEADLESS_MAXMEM=4G ~/.local/opt/ghidra_12.1.4_PUBLIC/support/analyzeHeadless work/ghidra ntw -process Napoleon.exe \
  -noanalysis -readOnly -scriptPath tools/ghidra -postScript "$S" "$@" 2>&1 | sed -n 's/^INFO  [A-Za-z]*\.java> \(.*\) (GhidraScript)  $/\1/p' | uniq
