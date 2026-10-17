#!/usr/bin/env bash
# Legt für das aktuelle VERSION-Tag ein GitHub-Release an und hängt die signierte APK sowie das Flatpak-Bundle mit SHA256SUMS +
# GPG-Signatur an; dieselben Dateien gehen auf die eigene Download-Seite (Hauptweg, Obtainium- und Zap-Store-Quelle).
# Vorlage: Alien Pass make-release.sh, Release-Sperre nach Alien Pass v1.22 / Alien Notes v1.14 (v1.5). GitHub: gh CLI, Token aus dem gh-Keyring (nie als Argument).
# Vorher: mobile/build-apk.sh, desktop/build-desktop.sh (beide aus dem getaggten Stand), SHA256SUMS signieren, Tag pushen (git push origin vX.Y).
# Schalter: --pruefen (nur die Release-Sperre, kein Upload), --nur-seite (Download-Seite neu), --nur-server (GitHub steht schon, nur Server).
set -euo pipefail
cd "$(dirname "$0")"
# Der ganze Ablauf steckt in main(): bash liest ein Skript während des Laufs nach — so gilt genau die beim Start gelesene (und unten mit dem
# Tag verglichene) Fassung, auch wenn die Datei währenddessen geändert wird (Release-Audit v1.5 R2-1 #3)
main() {
case "${1:-}" in ""|--pruefen|--nur-seite|--nur-server) ;; *) echo "FEHLER: unbekannter Schalter ${1} (erlaubt: --pruefen, --nur-seite, --nur-server)"; exit 1;; esac
[ "$#" -le 1 ] || { echo "FEHLER: höchstens ein Schalter"; exit 1; }

OWNER="Alien-Investor"
REPO="btc-steuertool"
APP_ID="org.alieninvestor.steuertool"
NAME=$(grep '^VERSION_NAME=' VERSION | cut -d= -f2 | tr -d '[:space:]')
CODE=$(grep '^VERSION_CODE=' VERSION | cut -d= -f2 | tr -d '[:space:]')
[[ "$NAME" =~ ^[0-9]+\.[0-9]+(\.[0-9]+)?$ ]] && [[ "$CODE" =~ ^[1-9][0-9]*$ ]] || { echo "FEHLER: VERSION_NAME/VERSION_CODE ungültig in VERSION"; exit 1; }
TAG="v${NAME}"
APK="mobile/build/release/btc-steuertool-${NAME}.apk"
FILE="btc-steuertool-${NAME}.apk"
DL="root@api.alien-investor.org:/var/www/alien-investor/html/downloads/steuertool/"
DLURL="https://api.alien-investor.org/downloads/steuertool/"
CERT_COLON="26:C5:E0:94:A8:B7:65:0C:A6:65:01:4D:0C:3A:8B:A6:82:B1:7C:05:F5:3C:6C:DE:F0:55:D0:7C:E9:84:BF:0B"
CERT_HEX="26c5e094a8b7650ca665014d0c3a8ba682b17c05f53c6cdef055d07ce984bf0b"

# Download-Seite als Obtainium-Quelle: GENAU EIN relativer Link auf die aktuelle APK. Obtainium (HTML-Quelle) sortiert die Links
# natürlich und nimmt den letzten, die Version zieht es per Regex aus dem Dateinamen — er muss VERSION_NAME exakt enthalten.
# Flatpak, SHA256SUMS und Signatur stehen als Text (nicht als Link) da, damit Obtainium sie nie als Kandidaten sieht.
download_page() {  # $1 = Zieldatei
  cat > "$1" <<EOF
<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>BTC Steuertool – Download</title>
</head>
<body>
<h1>BTC Steuertool ${NAME}</h1>
<p><a href="${FILE}">${FILE}</a></p>
<p>Android-APK, signiert mit dem Zertifikat (SHA-256) / signed with certificate (SHA-256):<br>
<code>${CERT_COLON}</code></p>
<p>Linux-Desktop (Flatpak) im selben Ordner / in the same folder: <code>${BUNDLE}</code>, <code>SHA256SUMS</code>, <code>SHA256SUMS.asc</code>
(GPG <code>100F 9E25 BFAE A807 DBC3&nbsp; 57D7 50C0 D785 83BF CB81</code>).</p>
<p>Obtainium: diese Adresse als Quelle eintragen / add this address as source. Spiegel / mirror: github.com/Alien-Investor/btc-steuertool/releases</p>
</body>
</html>
EOF
  [ "$(grep -o '<a ' "$1" | wc -l)" = 1 ] && grep -q "href=\"${FILE}\"" "$1" \
    || { echo "FEHLER: Download-Seite hat nicht genau einen Link auf ${FILE}"; exit 1; }
}

DREL="desktop/build/release"; DREV=$(grep '^DESKTOP_REV=' VERSION | cut -d= -f2 | tr -d '[:space:]')
[[ "$DREV" =~ ^[1-9][0-9]*$ ]] || { echo "FEHLER: DESKTOP_REV ungültig in VERSION"; exit 1; }
DTAG="$NAME"; [ "$DREV" = 1 ] || DTAG="$NAME-r$DREV"
BUNDLE="btc-steuertool-$DTAG-linux-x86_64.flatpak"

# ── Tag zuerst (Release-Audit R2-1 #3): EINMAL auf einen Commit festlegen, Prüfskripte = Tag, Prüffunktionen AUS DEM TAG laden ──
# Vorher kamen die Funktionen aus der release-quellen.sh des Arbeitsbaums und wurden erst danach mit dem Tag verglichen. Alle Vergleiche nehmen
# $TC, und vor dem Upload muss der Tag noch derselbe sein (R1 b-B5).
TOBJ="$(git rev-parse -q --verify "refs/tags/$TAG" || true)"; TC="$( [ -n "$TOBJ" ] && git rev-parse -q --verify "$TOBJ^{commit}" || true)"
[ -n "$TOBJ" ] && [ -n "$TC" ] || { echo "FEHLER: Tag $TAG fehlt lokal – erst git tag $TAG"; exit 1; }
tag_unveraendert() { [ "$(git rev-parse -q --verify "refs/tags/$TAG" || true)" = "$TOBJ" ] || { echo "FEHLER: Tag $TAG wurde während des Laufs versetzt"; exit 1; }; }
for f in make-release.sh release-quellen.sh; do cmp -s "$f" <(git show "$TC:$f") || { echo "FEHLER: $f im Arbeitsbaum ≠ $TAG"; exit 1; }; done
source <(git show "$TC:release-quellen.sh")
cmp -s VERSION <(git show "$TC:VERSION") || { echo "FEHLER: VERSION im Arbeitsbaum ≠ $TAG"; exit 1; }

# ── Release-Sperre: APK ──
# Nur eine APK hochladen, die mobile/build-apk.sh vollständig geprüft hat (Prüfdatei mit Hash, danach unverändert), mit dem Release-Zertifikat,
# der App-ID und genau dieser Version. Geprüft und hochgeladen wird eine KOPIE, die sofort bereitgestellt wird: ein paralleler Build kann die APK
# danach nicht mehr unbemerkt austauschen. Alle Uploads nehmen $SAPK bzw. die Kopien in $DST.
[ -f "$APK" ] || { echo "FEHLER: $APK fehlt – erst mobile/build-apk.sh"; exit 1; }
# Aus env.sh nur die beiden Pfade, nicht deren PATH: ein dort vorangestellter Ordner könnte cmp, sha256sum … der Prüfungen ersetzen
# (Release-Audit v1.5 R1 b-H8). apksigner braucht java — es bekommt JAVA_HOME/bin nur für den eigenen Aufruf.
eval "$(bash -c 'source ~/Apps/android-build/env.sh >/dev/null 2>&1; printf "ANDROID_HOME=%q\nJAVA_HOME=%q\n" "$ANDROID_HOME" "${JAVA_HOME:-}"')"
[ -n "$ANDROID_HOME" ] && [ -n "$JAVA_HOME" ] || { echo "FEHLER: ANDROID_HOME/JAVA_HOME aus ~/Apps/android-build/env.sh nicht lesbar"; exit 1; }
BT="$ANDROID_HOME/build-tools/34.0.0"
apksigner() { PATH="$JAVA_HOME/bin:$PATH" "$BT/apksigner" "$@"; }
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
SAPK="$STAGE/$FILE"; cp "$APK" "$SAPK"; SOK="$STAGE/apk.ok"; cp "$APK.ok" "$SOK" 2>/dev/null || : > "$SOK"
OKSUM="$(head -1 "$SOK" || true)"   # 1. Zeile = APK, danach die Quellen-Summen
[[ "$OKSUM" =~ ^[0-9a-f]{64}$ ]] && [ "$(sha256sum "$SAPK" | cut -d' ' -f1)" = "$OKSUM" ] \
  || { echo "FEHLER: APK ohne bestandene Endkontrolle oder danach verändert – erst mobile/build-apk.sh"; exit 1; }
CERT="$(apksigner verify --print-certs "$SAPK" 2>/dev/null | grep -m1 'SHA-256 digest' | awk '{print $NF}' || true)"
[ "$CERT" = "$CERT_HEX" ] || { echo "FEHLER: APK nicht mit dem Release-Zertifikat signiert (${CERT:-keins})"; exit 1; }
BADGE="$("$BT/aapt" dump badging "$SAPK" 2>/dev/null || true)"
# feste Zeichenkette, nicht Regex — sonst passte jeder Punkt auf jedes Zeichen (Release-Audit R1 b-H4)
grep -qF "package: name='${APP_ID}' versionCode='${CODE}' versionName='${NAME}'" <<<"$(head -1 <<<"$BADGE")" \
  || { echo "FEHLER: App-ID oder Version der APK passt nicht zu VERSION (${NAME}/${CODE})"; exit 1; }

# An den Tag binden: Hash, Zertifikat und Version passen auch bei einer APK, die VOR den letzten Änderungen gebaut wurde.
# (a) Quellen-Summen aus der .ok (Build-Skripte, Hülle, Engine) = Tag, genau die Quellenliste laut Tag
quellen_an_tag "$SOK" 2 apk "$TC" || exit 1
# (b) Inhalt der APK selbst: alles unter assets/ — Engine, Beispiel-ZIP, vendor/ (web/vendor.sha256), index.html samt CSP-Wert,
#     Capacitor-Dateien (mobile/apk-assets.sha256), capacitor.config.json, exakte Dateimenge
mkdir "$STAGE/apkx"; unzip -q "$SAPK" 'assets/*' -d "$STAGE/apkx"
apk_inhalt "$STAGE/apkx" "$TC" || exit 1
echo "APK an $TAG gebunden."

# ── Release-Sperre: Desktop ──
# Bundle + SHA256SUMS + Signatur + Prüfdatei bundle.ok aus desktop/build/release — nur vollständig, nur passend zur Version, als KOPIE.
# Ein Release trägt IMMER APK + Bundle (ein Release ohne APK bräche Obtainium).
for f in "$BUNDLE" SHA256SUMS SHA256SUMS.asc bundle.ok; do [ -f "$DREL/$f" ] || { echo "FEHLER: $DREL/$f fehlt – erst desktop/build-desktop.sh und signieren"; exit 1; }; done
DST="$STAGE/desktop"; mkdir -p "$DST"; for f in "$BUNDLE" SHA256SUMS SHA256SUMS.asc bundle.ok; do cp "$DREL/$f" "$DST/$f"; done
[ "$(grep -c . "$DST/SHA256SUMS" || true)" = 1 ] && grep -qxF "$(sha256sum "$DST/$BUNDLE" | cut -d' ' -f1)  $BUNDLE" "$DST/SHA256SUMS" \
  || { echo "FEHLER: SHA256SUMS hat nicht genau eine Zeile für $BUNDLE"; exit 1; }
# Signatur nur mit dem Release-Schlüssel aus dem Tag (gpgv, eigener Schlüsselbund) und am Hauptschlüssel-Fingerabdruck der VALIDSIG-Zeile —
# vorher reichte die Zeichenkette irgendwo in der Ausgabe, auch in der Benutzerkennung eines fremden Schlüssels (Release-Audit R1 b-B6)
git show "$TC:alien-investor-release-key.asc" | gpg --batch --dearmor > "$STAGE/release-key.gpg" 2>/dev/null || { echo "FEHLER: Release-Schlüssel aus $TAG nicht lesbar"; exit 1; }
GVS="$(gpgv --keyring "$STAGE/release-key.gpg" --status-fd 1 "$DST/SHA256SUMS.asc" "$DST/SHA256SUMS" 2>/dev/null || true)"
# … und nur eine gute Signatur eines gültigen Schlüssels: gpgv meldet auch für einen widerrufenen Schlüssel VALIDSIG (R2-1 #7)
grep -q '^\[GNUPG:\] GOODSIG ' <<<"$GVS" && grep -qE '^\[GNUPG:\] VALIDSIG [0-9A-F]+ .* 100F9E25BFAEA807DBC357D750C0D78583BFCB81$' <<<"$GVS" \
  && ! grep -qE '^\[GNUPG:\] (REVKEYSIG|EXPKEYSIG|EXPSIG|BADSIG|ERRSIG|KEYREVOKED|KEYEXPIRED|SIGEXPIRED)( |$)' <<<"$GVS" \
  || { echo "FEHLER: Signatur fehlt/falsch (Release-Schlüssel, gültig, nicht widerrufen)"; exit 1; }
# Bundle an den Tag binden: bundle.ok (nicht hochgeladen) = Bundle-Hash, Electron-Pin, Quellen-Summen; Pin und Quellen müssen dem Tag entsprechen
[ "$(head -1 "$DST/bundle.ok")" = "$(sha256sum "$DST/$BUNDLE" | cut -d' ' -f1)" ] || { echo "FEHLER: Bundle ≠ Prüfdatei bundle.ok – neu bauen (desktop/build-desktop.sh)"; exit 1; }
TBS="$(git show "$TC:desktop/build-desktop.sh")"
PIN="electron $(sed -n 's/^EL_VER="\([0-9.]*\)"$/\1/p' <<<"$TBS") $(sed -n 's/^EL_SHA="\([0-9a-f]\{64\}\)".*/\1/p' <<<"$TBS")"
[ "$(sed -n 2p "$DST/bundle.ok")" = "$PIN" ] || { echo "FEHLER: Electron im Bundle ≠ Pin in $TAG ($PIN)"; exit 1; }
quellen_an_tag "$DST/bundle.ok" 3 desktop "$TC" || exit 1
echo "Desktop-Bundle an $TAG gebunden (${PIN% *})."

# Nur die Download-Seite neu schreiben und hochladen: ./make-release.sh --nur-seite — erst NACH der Release-Sperre,
# und die APK auf dem Server muss byte-gleich die geprüfte lokale sein
if [ "${1:-}" = "--nur-seite" ]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' -I "${DLURL}${FILE}" || true)
  [ "$code" = 200 ] || { echo "FEHLER: ${DLURL}${FILE} liefert $code – Seite würde ins Leere zeigen"; exit 1; }
  SRVSUM="$( { curl -sf "${DLURL}${FILE}" || echo "curl-fehler"; } | sha256sum | cut -d' ' -f1)"
  [ "$SRVSUM" = "$OKSUM" ] || { echo "FEHLER: APK auf dem Server ist nicht die geprüfte lokale (${SRVSUM:0:12}…)"; exit 1; }
  download_page "$STAGE/index.html"
  rsync -a --no-o --no-g --chmod=F644 "$STAGE/index.html" "$DL" || { echo "FEHLER: Upload der Download-Seite gescheitert (ssh-add -l?)"; exit 1; }
  echo "=== Download-Seite: ${DLURL} (Link auf ${FILE}) ==="
  exit 0
fi

GH_REPO="$OWNER/$REPO"
gh auth status >/dev/null 2>&1 || { echo "FEHLER: gh nicht angemeldet (gh auth login)"; exit 1; }
tag_github() {
  RTAG="$(git ls-remote --exit-code https://github.com/$GH_REPO.git "refs/tags/$TAG" | cut -f1 || true)"
  [ -n "$RTAG" ] || { echo "FEHLER: Tag $TAG nicht auf GitHub – erst git push origin $TAG"; exit 1; }
  [ "$RTAG" = "$TOBJ" ] || { echo "FEHLER: Tag $TAG zeigt auf GitHub auf einen anderen Stand als lokal geprüft"; exit 1; }
}
tag_github

# Release-Notes aus CHANGELOG.md des TAGS (Abschnitt der aktuellen Version), nicht aus dem Arbeitsbaum
CHANGES=$(git show "$TC:CHANGELOG.md" | awk -v v="v${NAME}" '$1=="##" && $2==v {f=1;next} f && $1=="##" {exit} f{print}')
[ -n "$CHANGES" ] || { echo "FEHLER: CHANGELOG.md in $TAG hat keinen Abschnitt „## v${NAME}“"; exit 1; }
# Kein Platzhalter in den öffentlichen Release-Notes (wie Alien Notes v1.14, erweitert R1 b-H3): jede [eckige Klammer] (auch mehrzeilig, bis
# 300 Zeichen), {geschweifte Klammer}, ???, XX/XXX (auch in „XX.10.2026“), vX.Y und TODO/TBD/FIXME in jeder Schreibweise stoppen den Lauf;
# Markdown-Links [Text](…) und Kästchen [ ]/[x] zählen nicht. rc 1 = kein Treffer; ein Treffer (0) ODER ein grep-Fehler (2) stoppen.
# -z liest alles als einen Datensatz (mehrzeilig).
PHRC=0; grep -qzP '\[(?![ xX]\])[^\]]{1,300}\](?!\()|\{[^}]{1,80}\}|\?\?\?|\bX{2,}\b|\bvX\.Y\b|(?i)\b(TODO|TBD|FIXME)\b' <<<"$CHANGES" || PHRC=$?
[ "$PHRC" = 1 ] || { echo "FEHLER: Platzhalter im CHANGELOG-Abschnitt v${NAME} (oder Prüfung gescheitert, rc=$PHRC) – erst auflösen"; exit 1; }
BODY="## BTC Steuertool ${TAG}
${CHANGES}
---
### Android
Installation/Update über **Obtainium** mit der Download-Seite als Quelle (Anleitung im README und auf
https://alien-investor.org/btc-steuertool.html#obtainium), über den Zap Store, oder die APK direkt installieren.

Signatur-Fingerprint (SHA-256), über alle Versionen gleich – mit AppVerifier prüfen:
\`\`\`text
AppVerifier: ${CERT_COLON}
apksigner:   ${CERT_HEX}
\`\`\`

### Linux-Desktop (Flatpak)
\`${BUNDLE}\` + \`SHA256SUMS\` + \`SHA256SUMS.asc\`, signiert mit dem GPG-Release-Schlüssel von Alien Investor
([alien-investor-release-key.asc](https://github.com/Alien-Investor/btc-steuertool/blob/main/alien-investor-release-key.asc), auch auf alien-investor.org):
\`\`\`text
100F 9E25 BFAE A807 DBC3  57D7 50C0 D785 83BF CB81
\`\`\`
\`\`\`text
gpg --import alien-investor-release-key.asc
gpg --verify SHA256SUMS.asc SHA256SUMS
sha256sum -c SHA256SUMS
flatpak install --user ${BUNDLE}
\`\`\`
Update: \`flatpak uninstall --user org.alieninvestor.steuertool\` (die App speichert keine Steuerdaten, nur Sprache und Darstellung), dann neu installieren.

Kein Netz, keine Cloud, keine Telemetrie. Keine Steuerberatung — die Reports sind eine Rechenhilfe, die Verantwortung für die Erklärung bleibt bei dir."

if [ "${1:-}" = "--pruefen" ]; then
  printf '%s\n\n' "----- Release-Notiz (so ginge sie raus) -----" "$BODY"   # Release-Audit R1 b-H6
  echo "=== Release-Sperre bestanden: $FILE ($OKSUM), $BUNDLE, Tag $TAG ($TC) = GitHub. Nichts hochgeladen. ==="
  exit 0
fi
# Unmittelbar vor dem ersten Upload: Tag lokal und auf GitHub noch genau der geprüfte (R1 b-B5)
tag_unveraendert; tag_github

# GitHub (Spiegel): die geprüften Kopien. ./make-release.sh --nur-server: GitHub-Release steht schon, nur die Server-Downloads nachholen —
# mit allen Prüfungen oben; das GitHub-Release muss es geben und dieselben Dateien tragen
if [ "${1:-}" != "--nur-server" ]; then
  echo "=> GitHub: erstelle Release $TAG ..."
  printf '%s\n' "$BODY" > "$STAGE/notes.md"
  gh release create "$TAG" -R "$GH_REPO" --verify-tag --latest --title "BTC Steuertool $TAG" --notes-file "$STAGE/notes.md" \
    "$SAPK" "$DST/$BUNDLE" "$DST/SHA256SUMS" "$DST/SHA256SUMS.asc" \
    || { echo "FEHLER: GitHub-Release $TAG gescheitert (R1 b-H7) – auf GitHub nachsehen: ein halbes Release/Entwurf von Hand löschen"
         echo "         (gh release delete $TAG -R $GH_REPO), dann ./make-release.sh erneut. Server unverändert."; exit 1; }
  echo "=== GitHub fertig: https://github.com/$GH_REPO/releases/tag/$TAG ==="
else
  gh release download "$TAG" -R "$GH_REPO" -p "$FILE" -D "$STAGE/gh" >/dev/null 2>&1 || { echo "FEHLER: GitHub-Release $TAG oder dessen APK fehlt – erst den vollen Weg"; exit 1; }
  [ "$(sha256sum "$STAGE/gh/$FILE" | cut -d' ' -f1)" = "$OKSUM" ] || { echo "FEHLER: APK im GitHub-Release $TAG ist nicht die geprüfte lokale"; exit 1; }
  for f in "$BUNDLE" SHA256SUMS SHA256SUMS.asc; do
    gh release download "$TAG" -R "$GH_REPO" -p "$f" -D "$STAGE/gh" >/dev/null 2>&1 && cmp -s "$STAGE/gh/$f" "$DST/$f" || { echo "FEHLER: $f im GitHub-Release $TAG fehlt oder ≠ lokal geprüft"; exit 1; }
  done
fi

# Server: Dateien zuerst, die Download-Seite (Obtainium-Quelle) danach, damit sie nie auf eine fehlende APK zeigt.
echo "=> Server-Downloads: lade nach ${DL#*:} ..."
download_page "$STAGE/index.html"
if rsync -a --no-o --no-g --chmod=D755,F644 "$SAPK" "$DST/$BUNDLE" "$DST/SHA256SUMS" "$DST/SHA256SUMS.asc" "$DL" \
   && rsync -a --no-o --no-g --chmod=F644 "$STAGE/index.html" "$DL"; then
  echo "=== Server fertig: ${DLURL}${FILE}, Download-Seite ${DLURL} ==="
else
  echo "WARNUNG: Server-Upload fehlgeschlagen (ssh-add -l?) – GitHub-Release steht; nachholen mit ./make-release.sh --nur-server (nicht von Hand)."
  exit 1   # ein gescheiterter Upload endet nie mit 0: das Release ist erst mit den Server-Dateien fertig
fi
}
main "$@"; exit $?
