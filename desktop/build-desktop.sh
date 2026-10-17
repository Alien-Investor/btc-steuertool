#!/usr/bin/env bash
# BTC Steuertool Desktop bauen: web/dist → Electron (Version + Hash gepinnt) → app.asar + Fuses
# → Flatpak ohne Netz, als User-Installation. Kein sudo, keine npm-Installationsskripte. Muster: Alien Pass desktop/build-desktop.sh.
set -euo pipefail
cd "$(dirname "$0")"
# Release-Sperre (v1.5, Vorlage Alien Notes v1.14): alte Prüfdatei zuerst weg — ein abgebrochener Lauf hinterlässt keine gültige
rm -f build/release/bundle.ok

EL_VER="44.7.2"
EL_SHA="777b26a64aee3d185acb9f93c04782bb51eae7c2c61c793963ef24374e5a1539"   # electron-v44.7.2-linux-x64.zip (SHASUMS256.txt des Release, gegengeprüft mit checksums.json aus npm electron@44.7.2; v1.5, gleiche Engine wie Alien Pass v1.22, Sachwert-Tresor v3.11, Alien Notes v1.14, hier am 17.10.2026 geprüft)
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

# Build-Werkzeuge (asar, fuses) immer frisch aus dem Lock — npm prüft die Integrity jedes Pakets (Release-Audit v1.5 R1 a-A5)
npm ci --ignore-scripts --no-audit --no-fund
[ -f ../web/vendor/pyodide/pyodide.asm.wasm ] || { echo "FEHLER: erst web/vendor-setup.sh (Pyodide fehlt)" >&2; exit 1; }

# Prüfsummen der Quellen, aus denen das Bundle entsteht, VOR dem Bau (Liste: release-quellen.sh): make-release.sh vergleicht sie mit dem Tag —
# ein veraltetes oder aus einem anderen Stand gebautes Bundle geht so nicht neben der richtigen APK raus. Ändert sich etwas während des Baus: Abbruch.
source ../release-quellen.sh
DESK_SUMS0="$(cd .. && quellen_summen desktop)" || { echo "FEHLER: Quellenliste unvollständig (release-quellen.sh)" >&2; exit 1; }
# Jede Datei, die das Flatpak-Manifest einbindet (path:), muss in der Quellenliste stehen — icon.svg fehlte (Release-Audit R1 a-A2/b-B2)
while read -r mp; do
  [ "$mp" = ../build/electron ] && continue
  rel="$(realpath -m --relative-to=.. "flatpak/$mp")"
  (cd .. && feste_quellen desktop) | grep -qxF "$rel" || { echo "FEHLER: $rel (Manifest) fehlt in release-quellen.sh" >&2; exit 1; }
done < <(sed -n 's/^ *path: *//p' flatpak/$APP_ID.yml)
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
# Inhalt = Quellen VOR dem Bau (Release-Audit R1 a-A3): ändert eine zweite Sitzung Quellen, baut neu und stellt zurück, passt der Arbeitsbaum
# am Ende wieder — die Kopien im Bundle nicht. Darum jede Kopie gegen DESK_SUMS0: Hülle, www (Engine, vendor, index.html), Dateimenge.
printf '%s\n' "$DESK_SUMS0" > build/quellen.sum
for f in main.js preload.js atomic.js icon.png; do
  [ "$(_hash "build/app/$f")" = "$(cd .. && _summe @desktop/build/quellen.sum "desktop/$f")" ] || { echo "FEHLER: $f im Bundle ≠ Quelle vor dem Bau — neu bauen!" >&2; exit 1; }
done
(cd .. && engine_inhalt desktop/build/app/www @desktop/build/quellen.sum && vendor_inhalt desktop/build/app/www/vendor @desktop/build/quellen.sum \
  && index_inhalt desktop/build/app/www/index.html @desktop/build/quellen.sum web) || { echo "FEHLER: www/ im Bundle ≠ Quellen vor dem Bau — neu bauen!" >&2; exit 1; }
[ "$(cd build/app/www && find . -type f -o -type l | sed 's#^\./##' | LC_ALL=C sort)" = "$(cd .. && web_soll @desktop/build/quellen.sum)" ] \
  || { echo "FEHLER: www/ im Bundle hat andere Dateien als vorgesehen — neu bauen!" >&2; exit 1; }
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
[ "$(cd .. && quellen_summen desktop)" = "$DESK_SUMS0" ] || { echo "FEHLER: Quellen haben sich während des Baus geändert — neu bauen!" >&2; exit 1; }
# Prüfdatei (wird NICHT hochgeladen): 1. Zeile Bundle-Hash, 2. Zeile Electron-Pin, danach die Quellen (make-release.sh gleicht sie mit dem Tag ab)
{ sha256sum "build/release/$BUNDLE" | cut -d' ' -f1; echo "electron $EL_VER $EL_SHA"; echo "$DESK_SUMS0"; } > build/release/bundle.ok
echo "Bundle: desktop/build/release/$BUNDLE"; cat build/release/SHA256SUMS
echo "Signieren (Nutzer): gpg --local-user 100F9E25BFAEA807DBC357D750C0D78583BFCB81 --armor --detach-sign desktop/build/release/SHA256SUMS"
