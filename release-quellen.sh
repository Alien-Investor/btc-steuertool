# release-quellen.sh — Release-Sperre (v1.5, Vorlage Alien Pass v1.22 / Alien Notes v1.14), eingebunden per `source` von
# mobile/build-apk.sh, desktop/build-desktop.sh und make-release.sh. Eine Liste für alle drei: welche Quellen in APK bzw. Flatpak-Bundle
# eingehen. Die Builds halten deren Prüfsummen in der Prüfdatei (.ok) fest, make-release.sh gleicht sie mit dem Tag ab — eine APK oder ein
# Bundle aus einem anderen Stand als dem Tag geht so nicht raus. Alle Pfade relativ zum Repo-Root, Aufrufe mit cwd = Repo-Root.
# web/vendor/ (Pyodide, Schriften) ist nicht versioniert; gebunden über die versionierte Liste web/vendor.sha256 (Release-Audit R1 b-B1).
# Die Capacitor-Dateien der APK über mobile/apk-assets.sha256 (Soll aus dem npm-Tarball @capacitor/android 6.2.2, Integrity = package-lock).

# Feste Quellen je Art (Build-Skripte, Hülle, Versionsdatei, Listen); dazu kommen immer alle Dateien unter src/ und examples/ (ohne reports/).
feste_quellen() {  # $1 = apk | desktop
  local gemeinsam="VERSION release-quellen.sh web/index.html web/worker.js web/build.sh web/vendor-setup.sh web/vendor.sha256"
  case "$1" in
    apk) printf '%s\n' $gemeinsam mobile/build-apk.sh mobile/build-www.sh mobile/patch-hardening.mjs mobile/patch-signing.mjs \
           mobile/capacitor.config.json mobile/apk-assets.sha256 mobile/icons.py mobile/package.json mobile/package-lock.json \
           desktop/main.js desktop/icon.png ;;
    desktop) printf '%s\n' $gemeinsam desktop/main.js desktop/preload.js desktop/atomic.js desktop/pack.mjs desktop/build-desktop.sh \
           desktop/package.json desktop/package-lock.json desktop/icon.png desktop/icon.svg desktop/flatpak/btc-steuertool.sh \
           desktop/flatpak/org.alieninvestor.steuertool.desktop desktop/flatpak/org.alieninvestor.steuertool.yml ;;
    *) echo "FEHLER: feste_quellen apk|desktop" >&2; return 1 ;;
  esac
}

# Engine-Teile, die web/build.sh 1:1 nach dist/ kopiert. Im Arbeitsbaum ALLE Dateien (auch unversionierte — die kopiert build.sh mit,
# make-release.sh findet sie dann nicht im Tag und bricht ab), ohne Python-Caches und ohne die generierten Beispiel-Reports.
engine_baum() { find src examples -type f ! -path '*/__pycache__/*' ! -path 'examples/reports/*' | LC_ALL=C sort; }
# core.quotePath=false: sonst stünden Umlaut-Dateinamen in Anführungszeichen (Release-Audit R1 b-H2)
engine_tag() { git -c core.quotePath=false ls-tree -r --name-only "$1" -- src examples | grep -v '^examples/reports/' | LC_ALL=C sort; }

quellen() { { feste_quellen "$1" && engine_baum; } | LC_ALL=C sort; }                      # Build: was jetzt eingeht
quellen_tag() { { feste_quellen "$1" && engine_tag "$2"; } | LC_ALL=C sort; }              # Release: was laut Tag eingehen muss

# Prüfsummen im sha256sum-Format („<hex>  <pfad>“), eine Zeile je Quelle; scheitert, wenn eine feste Quelle fehlt
quellen_summen() { local q; mapfile -t q < <(quellen "$1"); sha256sum -- "${q[@]}"; }

# Woher eine Soll-Fassung kommt — <rev>: ein Git-Stand (Tag/Commit), „.“ = Arbeitsbaum, „@<datei>“ = Summenliste eines Builds
# (dann gilt eine Datei des Arbeitsbaums nur, wenn ihre Summe dort steht; so prüft build-desktop.sh die Kopien gegen den Stand VOR dem Bau).
_summe() { case "$1" in
  .) sha256sum < "$2" | cut -d' ' -f1 ;;
  @*) awk -v f="$2" '$2==f{print $1}' "${1#@}" ;;
  *) git show "$1:$2" | sha256sum | cut -d' ' -f1 ;; esac; }
_lies() { case "$1" in
  .) cat -- "$2" ;;
  @*) [ -n "$(_summe "$1" "$2")" ] && [ "$(_summe . "$2")" = "$(_summe "$1" "$2")" ] && cat -- "$2" ;;
  *) git show "$1:$2" ;; esac; }
_engine() { case "$1" in
  .) engine_baum ;;
  @*) awk '{print $2}' "${1#@}" | grep -E '^(src|examples)/' | LC_ALL=C sort ;;
  *) engine_tag "$1" ;; esac; }
_hash() { sha256sum < "$1" | cut -d' ' -f1; }
_unzip_muster() { sed 's/[][*?\\]/\\&/g' <<<"$1"; }   # unzip deutet Namen als Muster (Release-Audit R1 b-H5)

# quellen_an_tag <prüfdatei> <ab-zeile> <apk|desktop> <tag>: jede genannte Quelle = Tag-Fassung, und genau die Quellen laut Tag sind genannt.
quellen_an_tag() {
  local ok="$1" ab="$2" art="$3" tag="$4" want f got n=0 soll
  soll="$(quellen_tag "$art" "$tag")"
  [ "$(tail -n +"$ab" "$ok" | awk '{print $2}' | LC_ALL=C sort)" = "$soll" ] \
    || { echo "FEHLER: Prüfdatei ($art) nennt nicht genau die Quellen von $tag – aus dem getaggten Stand neu bauen"; return 1; }
  # auch eine letzte Zeile ohne Zeilenende (Release-Audit R1 b-B7)
  while read -r want f || [ -n "${want:-}" ]; do
    [[ "$want" =~ ^[0-9a-f]{64}$ ]] || { echo "FEHLER: Prüfdatei ($art) Zeile für $f unlesbar"; return 1; }
    git cat-file -e "$tag:$f" 2>/dev/null || { echo "FEHLER: $f nicht im Tag $tag"; return 1; }
    got="$(git show "$tag:$f" | sha256sum | cut -d' ' -f1)"
    [ "$want" = "$got" ] || { echo "FEHLER: $f beim Build ($art) ≠ $tag – aus dem getaggten Stand neu bauen"; return 1; }
    n=$((n+1)); want=""
  done < <(tail -n +"$ab" "$ok")
  [ "$n" = "$(grep -c . <<<"$soll")" ] || { echo "FEHLER: Prüfdatei ($art): $n statt $(grep -c . <<<"$soll") Quellen geprüft"; return 1; }
  echo "$art: $n Quellen = $tag."
}

# web_soll <rev>: genau diese Dateien liegen im ausgelieferten www/ (web/dist, APK assets/public, Bundle www/)
web_soll() {
  { echo index.html; echo worker.js; _engine "$1"; echo examples/beispieldaten.zip
    _lies "$1" web/vendor.sha256 | awk '{print "vendor/" $2}'; } | LC_ALL=C sort
}

# engine_inhalt <www> <rev>: die 1:1 kopierten Teile entsprechen Byte für Byte der Soll-Fassung — worker.js, src/, examples/ (Dateimenge exakt)
# und die Beispiel-ZIP: genau alle Beispieldateien außer README.md (Release-Audit R1 a-A6), jeder Eintrag einzeln (die ZIP trägt Bauzeit-Stempel).
engine_inhalt() {
  local w="$1" rev="$2" f e p n=0 soll_zip
  [ "$(_hash "$w/worker.js")" = "$(_summe "$rev" web/worker.js)" ] || { echo "FEHLER: worker.js ausgeliefert ≠ $rev"; return 1; }
  [ "$(cd "$w" && find src examples -type f ! -path examples/beispieldaten.zip | LC_ALL=C sort)" = "$(_engine "$rev")" ] \
    || { echo "FEHLER: src/ bzw. examples/ ausgeliefert hat andere Dateien als $rev"; return 1; }
  while read -r f; do [ "$(_hash "$w/$f")" = "$(_summe "$rev" "$f")" ] || { echo "FEHLER: $f ausgeliefert ≠ $rev"; return 1; }; n=$((n+1)); done < <(_engine "$rev")
  soll_zip="$(_engine "$rev" | grep '^examples/' | grep -vx 'examples/README.md' | awk -F/ '{print $NF}' | LC_ALL=C sort)"
  [ -z "$(uniq -d <<<"$soll_zip")" ] || { echo "FEHLER: Beispieldateien mit gleichem Namen — Beispiel-ZIP nicht eindeutig"; return 1; }
  [ -n "$soll_zip" ] && [ "$(unzip -Z1 "$w/examples/beispieldaten.zip" 2>/dev/null | LC_ALL=C sort)" = "$soll_zip" ] \
    || { echo "FEHLER: Beispiel-ZIP hat nicht genau die Beispieldateien von $rev"; return 1; }
  while read -r e; do
    p="$(_engine "$rev" | awk -v b="$e" -F/ '$1=="examples" && $NF==b')"
    [ "$(unzip -p "$w/examples/beispieldaten.zip" "$(_unzip_muster "$e")" | sha256sum | cut -d' ' -f1)" = "$(_summe "$rev" "$p")" ] \
      || { echo "FEHLER: $e in der Beispiel-ZIP ≠ $rev"; return 1; }
  done <<<"$soll_zip"
  echo "Engine-Inhalt = $rev ($n Dateien + Beispiel-ZIP)."
}

# vendor_inhalt <vendor-verzeichnis> <rev>: genau die Dateien aus web/vendor.sha256 der Soll-Fassung, jede mit ihrer Summe
vendor_inhalt() {
  local v="$1" rev="$2" liste want f
  liste="$(_lies "$rev" web/vendor.sha256)" && [ -n "$liste" ] || { echo "FEHLER: web/vendor.sha256 in $rev nicht lesbar"; return 1; }
  [ "$(cd "$v" && find . -type f -o -type l | sed 's#^\./##' | LC_ALL=C sort)" = "$(awk '{print $2}' <<<"$liste" | LC_ALL=C sort)" ] \
    || { echo "FEHLER: vendor/ ausgeliefert hat andere Dateien als web/vendor.sha256 ($rev)"; return 1; }
  while read -r want f; do [ "$(_hash "$v/$f")" = "$want" ] || { echo "FEHLER: vendor/$f ausgeliefert ≠ web/vendor.sha256 ($rev)"; return 1; }; done <<<"$liste"
  echo "vendor/ = web/vendor.sha256 ($rev, $(grep -c . <<<"$liste") Dateien)."
}

# index_inhalt <datei> <rev> <web|apk>: index.html genau so, wie web/build.sh (Platzhalter) und für die APK mobile/build-www.sh (CSP-Zeile
# direkt nach <meta charset>) sie aus der Soll-Fassung erzeugen — auch der CSP-Wert (Release-Audit R1 b-H1).
index_inhalt() {
  local datei="$1" rev="$2" art="$3" name stand csp tag='<meta charset="UTF-8">'
  name="$(_lies "$rev" VERSION | sed -n 's/^VERSION_NAME=//p')"
  case "$rev" in .|@*) stand="$(git log -1 --format=%cd --date=format:%d.%m.%Y)" ;; *) stand="$(git log -1 --format=%cd --date=format:%d.%m.%Y "$rev")" ;; esac
  [ -n "$name" ] && [ -n "$stand" ] || { echo "FEHLER: Version/Stand für index.html ($rev) nicht bestimmbar"; return 1; }
  _index_soll() { _lies "$rev" web/index.html | sed -e "s/__APP_VERSION__/$name/" -e "s/__WEB_STAND__/$stand/"; }
  if [ "$art" = apk ]; then
    csp="$(_lies "$rev" mobile/build-www.sh | sed -n 's/^CSP="\(.*\)"$/\1/p')"
    [ -n "$csp" ] && [ "$(grep -c . <<<"$csp")" = 1 ] && [[ "$csp" != *\\* ]] || { echo "FEHLER: CSP in mobile/build-www.sh ($rev) nicht eindeutig"; return 1; }
    [ "$(_lies "$rev" web/index.html | grep -cF "$tag")" = 1 ] || { echo "FEHLER: <meta charset> nicht genau einmal in web/index.html ($rev)"; return 1; }
    cmp -s "$datei" <(_index_soll | awk -v tag="$tag" -v csp="$csp" '{ i = index($0, tag)
        if (i && !d) { print substr($0, 1, i + length(tag) - 1); print "  <meta http-equiv=\"Content-Security-Policy\" content=\"" csp "\">" substr($0, i + length(tag)); d = 1 }
        else print }') || { echo "FEHLER: index.html (APK) ≠ $rev"; return 1; }
  else
    cmp -s "$datei" <(_index_soll) || { echo "FEHLER: index.html ≠ $rev"; return 1; }
  fi
  echo "index.html = $rev ($art)."
}

# apk_inhalt <entpackt> <rev>: alles unter assets/ der APK — www-Teil wie oben, Capacitor-Dateien gegen mobile/apk-assets.sha256,
# capacitor.config.json inhaltlich = mobile/capacitor.config.json (Release-Audit R1 b-B1), Dateimenge exakt. assets/dexopt/ (ART-Profile
# aus dem Build, kein ausführbarer Code) nur nach Namen.
apk_inhalt() {
  local d="$1" rev="$2" pins want f
  engine_inhalt "$d/assets/public" "$rev" && vendor_inhalt "$d/assets/public/vendor" "$rev" && index_inhalt "$d/assets/public/index.html" "$rev" apk || return 1
  pins="$(_lies "$rev" mobile/apk-assets.sha256)" && [ -n "$pins" ] || { echo "FEHLER: mobile/apk-assets.sha256 in $rev nicht lesbar"; return 1; }
  while read -r want f; do [ "$(_hash "$d/$f")" = "$want" ] || { echo "FEHLER: $f in der APK ≠ mobile/apk-assets.sha256 ($rev)"; return 1; }; done <<<"$pins"
  [ -n "$(jq -S . "$d/assets/capacitor.config.json" 2>/dev/null)" ] \
    && [ "$(jq -S . "$d/assets/capacitor.config.json" 2>/dev/null)" = "$(_lies "$rev" mobile/capacitor.config.json | jq -S . 2>/dev/null)" ] \
    || { echo "FEHLER: capacitor.config.json der APK ≠ $rev"; return 1; }
  [ "$(cd "$d" && find assets -type f -o -type l | LC_ALL=C sort)" = "$( { web_soll "$rev" | sed 's#^#assets/public/#'; awk '{print $2}' <<<"$pins"
        printf '%s\n' assets/capacitor.config.json assets/dexopt/baseline.prof assets/dexopt/baseline.profm; } | LC_ALL=C sort)" ] \
    || { echo "FEHLER: assets/ der APK hat andere Dateien als $rev vorsieht"; return 1; }
  echo "APK-Inhalt (assets/) = $rev."
}
