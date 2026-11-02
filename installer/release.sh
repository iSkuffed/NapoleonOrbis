#!/usr/bin/env bash
# Release build: installer/release.sh WORLD VERSION  ->  installer/dist/NapoleonOrbis-VERSION-{windows,linux}.zip
# (payload of work/world/WORLD embedded in each binary; README_PLAYERS.txt + CREDITS.txt + LICENSE beside it)
set -eu
cd "$(dirname "$0")/.."; W=$1 V=$2; export PATH=$HOME/.local/go/bin:$PATH
.venv/bin/python tools/make_payload.py "$W" "$V"
cd installer; rm -rf dist; mkdir dist
go vet ./... && go test ./... >/dev/null
for os in windows linux; do
  ext=; [ $os = windows ] && ext=.exe
  bin=napoleon-orbis-installer-$os-amd64$ext
  CGO_ENABLED=0 GOOS=$os GOARCH=amd64 go build -tags embedpayload -ldflags="-s -w" -o dist/$bin .
  (cd dist && cp ../README_PLAYERS.txt ../CREDITS.txt ../../LICENSE . && zip -q -9 NapoleonOrbis-$V-$os.zip $bin README_PLAYERS.txt CREDITS.txt LICENSE && rm README_PLAYERS.txt CREDITS.txt LICENSE)
done
rm -rf payload; ls -la dist
