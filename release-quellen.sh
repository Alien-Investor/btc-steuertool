# release-quellen.sh — Release-Sperre (v1.5, Vorlage Alien Pass v1.22 / Alien Notes v1.14), eingebunden per `source` von
# mobile/build-apk.sh, desktop/build-desktop.sh und make-release.sh. Eine Liste für alle drei: welche Quellen in APK bzw. Flatpak-Bundle
# eingehen. Die Builds halten deren Prüfsummen in der Prüfdatei (.ok) fest, make-release.sh gleicht sie mit dem Tag ab — eine APK oder ein
# Bundle aus einem anderen Stand als dem Tag geht so nicht raus. Alle Pfade relativ zum Repo-Root, Aufrufe mit cwd = Repo-Root.
# Nicht erfasst: web/vendor/ (Pyodide, Schriften; nicht versioniert) — gebunden ist nur web/vendor-setup.sh mit seinen SHA-256-Pins.

# Feste Quellen je Art (Build-Skripte, Hülle, Versionsdatei); dazu kommen immer alle Dateien unter src/ und examples/ (ohne reports/).
feste_quellen() {  # $1 = apk | desktop
  local gemeinsam="VERSION release-quellen.sh web/index.html web/worker.js web/build.sh web/vendor-setup.sh"
  case "$1" in
    apk) printf '%s\n' $gemeinsam mobile/build-apk.sh mobile/build-www.sh mobile/patch-hardening.mjs mobile/patch-signing.mjs \
           mobile/capacitor.config.json mobile/icons.py mobile/package.json mobile/package-lock.json desktop/main.js desktop/icon.png ;;
    desktop) printf '%s\n' $gemeinsam desktop/main.js desktop/preload.js desktop/atomic.js desktop/pack.mjs desktop/build-desktop.sh \
           desktop/package.json desktop/package-lock.json desktop/icon.png desktop/flatpak/btc-steuertool.sh \
           desktop/flatpak/org.alieninvestor.steuertool.desktop desktop/flatpak/org.alieninvestor.steuertool.yml ;;
    *) echo "FEHLER: feste_quellen apk|desktop" >&2; return 1 ;;
  esac
}

# Engine-Teile, die web/build.sh 1:1 nach dist/ kopiert. Im Arbeitsbaum ALLE Dateien (auch unversionierte — die kopiert build.sh mit,
# make-release.sh findet sie dann nicht im Tag und bricht ab), ohne Python-Caches und ohne die generierten Beispiel-Reports.
engine_baum() { find src examples -type f ! -path '*/__pycache__/*' ! -path 'examples/reports/*' | LC_ALL=C sort; }
engine_tag() { git ls-tree -r --name-only "$1" -- src examples | grep -v '^examples/reports/' | LC_ALL=C sort; }   # $1 = Tag

quellen() { { feste_quellen "$1" && engine_baum; } | LC_ALL=C sort; }                      # Build: was jetzt eingeht
quellen_tag() { { feste_quellen "$1" && engine_tag "$2"; } | LC_ALL=C sort; }              # Release: was laut Tag eingehen muss

# Prüfsummen im sha256sum-Format („<hex>  <pfad>“), eine Zeile je Quelle; scheitert, wenn eine feste Quelle fehlt
quellen_summen() { local q; mapfile -t q < <(quellen "$1"); sha256sum -- "${q[@]}"; }

# quellen_an_tag <prüfdatei> <ab-zeile> <apk|desktop> <tag>: jede genannte Quelle = Tag-Fassung, und genau die Quellen laut Tag sind genannt.
quellen_an_tag() {
  local ok="$1" ab="$2" art="$3" tag="$4" want f got n=0
  [ "$(tail -n +"$ab" "$ok" | awk '{print $2}' | LC_ALL=C sort)" = "$(quellen_tag "$art" "$tag")" ] \
    || { echo "FEHLER: Prüfdatei ($art) nennt nicht genau die Quellen von $tag – aus dem getaggten Stand neu bauen"; return 1; }
  while read -r want f; do
    [[ "$want" =~ ^[0-9a-f]{64}$ ]] || { echo "FEHLER: Prüfdatei ($art) Zeile für $f unlesbar"; return 1; }
    git cat-file -e "$tag:$f" 2>/dev/null || { echo "FEHLER: $f nicht im Tag $tag"; return 1; }
    got="$(git show "$tag:$f" | sha256sum | cut -d' ' -f1)"
    [ "$want" = "$got" ] || { echo "FEHLER: $f beim Build ($art) ≠ $tag – aus dem getaggten Stand neu bauen"; return 1; }
    n=$((n+1))
  done < <(tail -n +"$ab" "$ok")
  echo "$art: $n Quellen = $tag."
}

# engine_inhalt <www-verzeichnis> <tag | .>: die 1:1 kopierten Teile im ausgelieferten www/ (APK: assets/public) entsprechen Byte für Byte dem Tag
# (make-release.sh) bzw. dem Arbeitsbaum „.“ (Build) — worker.js, src/, examples/ (Dateimenge exakt) und jeder Eintrag der Beispiel-ZIP
# (die ZIP selbst trägt Bauzeit-Stempel, darum je Eintrag).
_lies() { if [ "$1" = . ]; then cat -- "$2"; else git show "$1:$2"; fi; }
_engine() { if [ "$1" = . ]; then engine_baum; else engine_tag "$1"; fi; }
engine_inhalt() {
  local w="$1" tag="$2" f e p n=0
  cmp -s "$w/worker.js" <(_lies "$tag" web/worker.js) || { echo "FEHLER: worker.js ausgeliefert ≠ $tag"; return 1; }
  [ "$(cd "$w" && find src examples -type f ! -path examples/beispieldaten.zip | LC_ALL=C sort)" = "$(_engine "$tag")" ] \
    || { echo "FEHLER: src/ bzw. examples/ ausgeliefert hat andere Dateien als $tag"; return 1; }
  while read -r f; do cmp -s "$w/$f" <(_lies "$tag" "$f") || { echo "FEHLER: $f ausgeliefert ≠ $tag"; return 1; }; n=$((n+1)); done < <(_engine "$tag")
  [ "$(unzip -Z1 "$w/examples/beispieldaten.zip" 2>/dev/null | grep -c . || true)" -ge 1 ] || { echo "FEHLER: examples/beispieldaten.zip fehlt oder ist leer"; return 1; }
  while read -r e; do
    p="$(_engine "$tag" | awk -v b="$e" -F/ '$NF==b' )"
    [ -n "$p" ] && [ "$(grep -c . <<<"$p")" = 1 ] || { echo "FEHLER: Eintrag $e der Beispiel-ZIP hat keine eindeutige Quelle in $tag"; return 1; }
    cmp -s <(unzip -p "$w/examples/beispieldaten.zip" "$e") <(_lies "$tag" "$p") || { echo "FEHLER: $e in der Beispiel-ZIP ≠ $tag"; return 1; }
  done < <(unzip -Z1 "$w/examples/beispieldaten.zip")
  echo "Engine-Inhalt = $tag ($n Dateien + Beispiel-ZIP)."
}
