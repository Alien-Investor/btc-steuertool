#!/usr/bin/env bash
# Legt für das aktuelle VERSION-Tag ein GitHub-Release an und hängt die signierte APK sowie das Flatpak-Bundle mit SHA256SUMS +
# GPG-Signatur an; dieselben Dateien gehen auf die eigene Download-Seite (Hauptweg, Obtainium- und Zap-Store-Quelle).
# Vorlage: Alien Pass make-release.sh. GitHub: gh CLI, Token aus dem gh-Keyring (nie als Argument).
# Vorher: mobile/build-apk.sh, desktop/build-desktop.sh, SHA256SUMS signieren, Tag pushen (git push origin vX.Y).
set -euo pipefail
cd "$(dirname "$0")"

OWNER="Alien-Investor"
REPO="btc-steuertool"
NAME=$(grep '^VERSION_NAME=' VERSION | cut -d= -f2 | tr -d '[:space:]')
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
DTAG="$NAME"; [ "${DREV:-1}" = 1 ] || DTAG="$NAME-r$DREV"
BUNDLE="btc-steuertool-$DTAG-linux-x86_64.flatpak"

# Nur die Download-Seite neu schreiben und hochladen: ./make-release.sh --nur-seite
if [ "${1:-}" = "--nur-seite" ]; then
  code=$(curl -s -o /dev/null -w '%{http_code}' -I "${DLURL}${FILE}")
  [ "$code" = 200 ] || { echo "FEHLER: ${DLURL}${FILE} liefert $code – Seite würde ins Leere zeigen"; exit 1; }
  PAGE=$(mktemp -d); trap 'rm -rf "$PAGE"' EXIT
  download_page "$PAGE/index.html"
  rsync -a --no-o --no-g --chmod=F644 "$PAGE/index.html" "$DL"
  echo "=== Download-Seite: ${DLURL} (Link auf ${FILE}) ==="
  exit 0
fi

[ -f "$APK" ] || { echo "FEHLER: $APK fehlt – erst mobile/build-apk.sh"; exit 1; }
# Ein Release trägt IMMER APK + Bundle (ein Release ohne APK bräche Obtainium).
for f in "$BUNDLE" SHA256SUMS SHA256SUMS.asc; do [ -f "$DREL/$f" ] || { echo "FEHLER: $DREL/$f fehlt – erst desktop/build-desktop.sh und signieren"; exit 1; }; done
(cd "$DREL" && sha256sum -c --quiet SHA256SUMS) || { echo "FEHLER: SHA256SUMS passt nicht zum Bundle"; exit 1; }
gpg --verify "$DREL/SHA256SUMS.asc" "$DREL/SHA256SUMS" 2>&1 | grep -q '100F9E25BFAEA807DBC357D750C0D78583BFCB81' || { echo "FEHLER: Signatur fehlt/falsch (Release-Schlüssel)"; exit 1; }

GH_REPO="$OWNER/$REPO"
gh auth status >/dev/null 2>&1 || { echo "FEHLER: gh nicht angemeldet (gh auth login)"; exit 1; }
git ls-remote --exit-code https://github.com/$GH_REPO.git "refs/tags/$TAG" >/dev/null || { echo "FEHLER: Tag $TAG nicht auf GitHub – erst git push origin $TAG"; exit 1; }

# Release-Notes aus CHANGELOG.md (Abschnitt der aktuellen Version)
CHANGES=$(awk -v v="v${NAME}" '$1=="##" && $2==v {f=1;next} f && $1=="##" {exit} f{print}' CHANGELOG.md)
[ -n "$CHANGES" ] || CHANGES="Siehe CHANGELOG.md."
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

STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
cp "$APK" "$STAGE/$FILE"
echo "=> GitHub: erstelle Release $TAG ..."
printf '%s\n' "$BODY" > "$STAGE/notes.md"
gh release create "$TAG" -R "$GH_REPO" --verify-tag --latest --title "BTC Steuertool $TAG" --notes-file "$STAGE/notes.md" \
  "$STAGE/$FILE" "$DREL/$BUNDLE" "$DREL/SHA256SUMS" "$DREL/SHA256SUMS.asc"
echo "=== GitHub fertig: https://github.com/$GH_REPO/releases/tag/$TAG ==="

# Server: Dateien zuerst, die Download-Seite (Obtainium-Quelle) danach, damit sie nie auf eine fehlende APK zeigt.
echo "=> Server-Downloads: lade nach ${DL#*:} ..."
download_page "$STAGE/index.html"
if rsync -a --no-o --no-g --chmod=D755,F644 "$STAGE/$FILE" "$DREL/$BUNDLE" "$DREL/SHA256SUMS" "$DREL/SHA256SUMS.asc" "$DL" \
   && rsync -a --no-o --no-g --chmod=F644 "$STAGE/index.html" "$DL"; then
  echo "=== Server fertig: ${DLURL}${FILE}, Download-Seite ${DLURL} ==="
else
  echo "WARNUNG: Server-Upload fehlgeschlagen (ssh-add -l?) – GitHub-Release steht; Upload von Hand nachholen."
fi
