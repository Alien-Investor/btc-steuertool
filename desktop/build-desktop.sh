#!/usr/bin/env bash
# BTC Steuertool Desktop bauen: web/dist → Electron (Version + Hash gepinnt) → app.asar + Fuses
# → Flatpak ohne Netz, als User-Installation. Kein sudo, keine npm-Installationsskripte. Muster: Alien Pass desktop/build-desktop.sh.
set -euo pipefail
cd "$(dirname "$0")"

EL_VER="44.5.1"
EL_SHA="5bcd217611d6843ececd6c9e9c1fcd1da3ab066c43d8b1a9e4b44689a1fba6f5"   # electron-v44.5.1-linux-x64.zip (wie Alien Pass / Sachwert-Tresor)
APP_ID="org.alieninvestor.steuertool"
CACHE="$HOME/.cache/btc-steuertool-desktop"
ZIP="$CACHE/electron-v$EL_VER-linux-x64.zip"

mkdir -p "$CACHE"
if [ ! -f "$ZIP" ]; then
  curl -fL --proto '=https' --tlsv1.2 -o "$ZIP.part" "https://github.com/electron/electron/releases/download/v$EL_VER/electron-v$EL_VER-linux-x64.zip"
  mv "$ZIP.part" "$ZIP"
fi
echo "$EL_SHA  $ZIP" | sha256sum -c --quiet - || { echo "FEHLER: Hash des Electron-Archivs weicht ab — Build abgebrochen!"; exit 1; }
echo "Electron $EL_VER: Hash OK."

[ -d node_modules/@electron/asar ] && [ -d node_modules/@electron/fuses ] || { echo "FEHLER: erst 'npm ci' in desktop/"; exit 1; }
[ -f ../web/vendor/pyodide/pyodide.asm.wasm ] || { echo "FEHLER: erst web/vendor-setup.sh (Pyodide fehlt)" >&2; exit 1; }

# Eigener Befehl, nicht links von && — sonst greift set -e nicht und ein Fehler würde still übergangen (Alien Pass Audit run-6 #6)
../web/build.sh || { echo "FEHLER: web/build.sh fehlgeschlagen — Build abgebrochen!" >&2; exit 1; }
VNAME=$(grep '^VERSION_NAME=' ../VERSION | cut -d= -f2 | tr -d '[:space:]')
DREV=$(grep '^DESKTOP_REV=' ../VERSION | cut -d= -f2 | tr -d '[:space:]')
[[ "$VNAME" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || { echo "FEHLER: VERSION_NAME fehlt oder ungültig in VERSION" >&2; exit 1; }
[[ "$DREV" =~ ^[1-9][0-9]*$ ]] || { echo "FEHLER: DESKTOP_REV fehlt oder ungültig in VERSION" >&2; exit 1; }
# Reiner Engine-Neubau (nur DESKTOP_REV hoch) bekommt ein -rN im Dateinamen; die App-Version bleibt VERSION_NAME
TAG="$VNAME"; [ "$DREV" = 1 ] || TAG="$VNAME-r$DREV"

rm -rf build && mkdir -p build/app build/electron
unzip -q "$ZIP" -d build/electron
rm -f build/electron/chrome-sandbox build/electron/resources/default_app.asar   # Sandbox kommt im Flatpak über zypak
cp main.js preload.js atomic.js icon.png build/app/
cp -r ../web/dist build/app/www
printf '{"name":"btc-steuertool","productName":"BTC Steuertool","version":"%s","main":"main.js","private":true}\n' "$VNAME" > build/app/package.json
node pack.mjs build/app build/electron

# Genauer Soll-Vergleich statt Sperrliste: jedes zusätzliche Recht bräche das Versprechen „kein Netz, keine Dateien“
WANT=$(printf '[Context]\nshared=ipc;\nsockets=wayland;fallback-x11;\ndevices=dri;')

# Der Builder läuft selbst als Flatpak und sieht nur ~/ — deshalb liegt alles unter desktop/build/
# Erst bauen, dann die Rechte am gebauten Stand prüfen, erst danach installieren
flatpak run org.flatpak.Builder --force-clean --state-dir=build/.flatpak-builder build/fp flatpak/$APP_ID.yml
PRE=$(awk '/^\[/{skip=($0=="[Application]"||$0=="[Build]"||$0 ~ /^\[Extension .*\.Debug\]$/)} !skip' build/fp/metadata | sed '/^$/d')
WANT_META=$(printf '[Context]\nshared=ipc;\nsockets=fallback-x11;wayland;\ndevices=dri;')
if [ "$PRE" != "$WANT_META" ]; then echo "$PRE"; echo "FEHLER: Rechte im gebauten Stand weichen vom Soll ab — nicht installiert!" >&2; exit 1; fi
flatpak run org.flatpak.Builder --user --install --export-only --repo=build/repo --state-dir=build/.flatpak-builder build/fp flatpak/$APP_ID.yml

# Endkontrolle an der installierten App: kein Netz, kein Dateisystem, nur Anzeige + GPU
PERM=$(flatpak info --user --show-permissions "$APP_ID")
echo "$PERM"
if [ "$(echo "$PERM" | sed '/^$/d')" != "$WANT" ]; then echo "FEHLER: Flatpak-Rechte weichen vom Soll ab — abgebrochen!" >&2; exit 1; fi
echo "Endkontrolle OK: kein Netz, kein Dateisystem. Start: flatpak run $APP_ID"

# Release-Datei: Flatpak-Bundle aus demselben Repo wie die geprüfte Installation; die Laufzeit lädt flatpak beim Nutzer von Flathub nach.
mkdir -p build/release
BUNDLE="btc-steuertool-$TAG-linux-x86_64.flatpak"
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo build/repo "build/release/$BUNDLE" "$APP_ID"
(cd build/release && sha256sum "$BUNDLE" > SHA256SUMS)
echo "Bundle: desktop/build/release/$BUNDLE"; cat build/release/SHA256SUMS
echo "Signieren (Nutzer): gpg --local-user 100F9E25BFAEA807DBC357D750C0D78583BFCB81 --armor --detach-sign desktop/build/release/SHA256SUMS"
