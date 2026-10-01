#!/bin/bash
# Stellt vendor/ wieder her (Pyodide-Runtime + tzdata-Wheel + Fonts).
# Nach einem frischen Clone einmal ausführen — vendor/ ist nicht versioniert (~50 MB).
#
# SA-011 (Security-Audit run-1): Jede geladene Datei wird gegen einen erwarteten
# SHA-256 geprüft. Ohne das lief ~50 MB WASM ungeprüft in den Browser jedes
# zahlenden Kunden — mit wasm-unsafe-eval und einem bereits erlaubten
# connect-src-Ziel, also einem CSP-konformen Exfiltrationskanal.
#
# Reihenfolge ist wichtig und nicht beliebig: der Core-Tarball wird gegen ein
# LITERAL hier im Skript geprüft, die Wheels danach gegen pyodide-lock.json.
# Andersherum wäre es zirkulär — die Lock-Datei kommt selbst aus dem Tarball.
#
# Alle Downloads laufen über curl, nicht über urllib: Python holt hier nichts aus
# dem Netz, es parst nur. (Hält das Skript mit dem lokalen python3-Wächter
# verträglich und macht den Datenfluss offensichtlich.)
set -euo pipefail
cd "$(dirname "$0")"

PYODIDE_VERSION=0.26.4

# SHA-256 des Core-Tarballs.
#
# GRENZE DIESER ANGABE, offen dokumentiert: Pyodide veröffentlicht keine
# Checksummen — es gibt keine SHA256SUMS-Datei im Release, und die GitHub-API
# liefert für die Assets von 2024 digest=null. Dieser Wert wurde deshalb am
# 15.08.2026 selbst bestimmt (Trust On First Use), nicht von unabhängiger Stelle
# bestätigt. Belastbarkeit kommt aus dem Quercheck: der an diesem Tag frisch
# geladene Tarball war byte-identisch mit dem vendor/, das seit Juni 2026 in
# Produktion läuft — zwei Abrufe zu verschiedenen Zeitpunkten, gleiche Bytes.
#
# Was der Pin leistet: er erkennt jede künftige Veränderung. Was er nicht
# leistet: er beweist nicht, dass der Ursprung schon 2024 unverfälscht war.
#
# BEI VERSIONSWECHSEL MUSS DIESER WERT NEU BESTIMMT WERDEN.
PYODIDE_CORE_SHA256=70dba93432f3653155998cc9001f9c200182343c2f95165a2f9e9e4673fa35e8

# Google rotiert die Font-Dateien gelegentlich. Schlägt die Prüfung fehl, ist das
# in aller Regel eine legitime Rotation und kein Angriff — dann den neuen Hash
# nach kurzer Sichtprüfung hier eintragen. Orbitron 700 und 900 teilen sich
# dieselbe Datei (Google liefert einen variablen Font).
FONT_SHA256_Orbitron_700=c25a9f9da5d9f3db1bf2a01474722dc9b377675b7bbab6d0dfda6902794fd1ed
FONT_SHA256_Orbitron_900=c25a9f9da5d9f3db1bf2a01474722dc9b377675b7bbab6d0dfda6902794fd1ed
FONT_SHA256_ShareTechMono_400=41e6b9f297f7d9a2df2aaa274092f76d2f72711a15ca455f7f4f4f92caf16b72

# Prüft $1 gegen den erwarteten Hash $2. Bei Abweichung: Datei weg, Abbruch.
# Die kaputte Datei wird gelöscht, damit ein zweiter Lauf nicht auf einem
# halb geprüften vendor/ aufsetzt.
verify_sha256() {
  local file="$1" want="$2" label="$3" got
  got=$(sha256sum "$file" | cut -d' ' -f1)
  if [ "$got" != "$want" ]; then
    echo "" >&2
    echo "ABBRUCH: $label hat einen unerwarteten SHA-256." >&2
    echo "  erwartet: $want" >&2
    echo "  bekommen: $got" >&2
    echo "" >&2
    echo "  Entweder wurde die Quelle verändert, oder die Version wurde" >&2
    echo "  angehoben, ohne den Hash im Skript nachzuziehen. NICHT einfach" >&2
    echo "  den Hash überschreiben — erst klären, woher die Abweichung kommt." >&2
    rm -f "$file"
    exit 1
  fi
  echo "  ✓ $label"
}

mkdir -p vendor/pyodide vendor/fonts

# 1. Pyodide-Core (Runtime: pyodide.js, wasm, stdlib, lock)
cd vendor/pyodide
TARBALL=$(mktemp -t pyodide-core-XXXXXX.tar.bz2)
trap 'rm -f "$TARBALL"' EXIT
echo "Pyodide-Core ${PYODIDE_VERSION}:"
curl -sSL --fail -o "$TARBALL" \
  "https://github.com/pyodide/pyodide/releases/download/${PYODIDE_VERSION}/pyodide-core-${PYODIDE_VERSION}.tar.bz2"
verify_sha256 "$TARBALL" "$PYODIDE_CORE_SHA256" "pyodide-core-${PYODIDE_VERSION}.tar.bz2"
tar xjf "$TARBALL" --strip-components=1
rm -f "$TARBALL"
trap - EXIT

# 2. Wheels: tzdata inkl. Abhängigkeits-Closure laut pyodide-lock.json
#    (pandas seit 10/2026 nicht mehr — der Kern nutzt nur die Standardbibliothek)
#    Python löst nur die Closure auf und gibt "dateiname sha256" aus — der
#    sha256 steht im selben Dict direkt neben dem file_name und wurde bis
#    15.08.2026 eingelesen und weggeworfen. Genau das war SA-011.
echo "Wheels:"
python3 - <<'PY' > /tmp/.pyodide-wheels.$$
import json
lock = json.load(open('pyodide-lock.json'))
pkgs = lock['packages']
needed, todo = set(), ['tzdata']
while todo:
    k = todo.pop().lower()
    if k in needed or k not in pkgs:
        continue
    needed.add(k)
    todo.extend(pkgs[k]['depends'])
for k in sorted(needed):
    print(pkgs[k]['file_name'], pkgs[k]['sha256'])
PY

while read -r fn sha; do
  curl -sSL --fail -o "$fn" "https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/${fn}"
  verify_sha256 "$fn" "$sha" "$fn"
done < /tmp/.pyodide-wheels.$$
rm -f /tmp/.pyodide-wheels.$$

# 3. Fonts (Orbitron 700/900 + Share Tech Mono, latin) + lokales fonts.css
cd ../fonts
echo "Fonts:"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
export GFONTS_CSS=/tmp/.gfonts.$$
curl -sSL --fail -A "$UA" -o "$GFONTS_CSS" \
  "https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=Share+Tech+Mono&display=swap"

# Python parst nur das CSS und gibt "dateiname url css-block" aus (Block
# base64-kodiert, damit er auf eine Zeile passt).
python3 - <<'PY' > /tmp/.fontplan.$$
import base64, os, re
css = open(os.environ['GFONTS_CSS']).read()
seen = set()
for subset, block in re.findall(r'/\* ([a-z-]+) \*/\s*(@font-face \{.*?\})', css, re.S):
    if subset != 'latin':
        continue
    src = re.search(r'url\((https://[^)]+\.woff2)\)', block).group(1)
    fam = re.search(r"font-family: '([^']+)'", block).group(1)
    weight = re.search(r'font-weight: (\d+)', block).group(1)
    fn = f"{fam.replace(' ', '')}-{weight}.woff2"
    if fn in seen:
        continue
    seen.add(fn)
    print(fn, src, base64.b64encode(block.replace(src, fn).encode()).decode())
PY

: > fonts.css
while read -r fn src block; do
  curl -sSL --fail -o "$fn" "$src"
  # Variablenname aus dem Dateinamen: Orbitron-700.woff2 -> FONT_SHA256_Orbitron_700
  var="FONT_SHA256_$(echo "${fn%.woff2}" | tr '-' '_')"
  verify_sha256 "$fn" "${!var:?Kein erwarteter Hash fuer $fn im Skript hinterlegt}" "$fn"
  echo "$block" | base64 -d >> fonts.css
  echo "" >> fonts.css
done < /tmp/.fontplan.$$
rm -f /tmp/.fontplan.$$ "$GFONTS_CSS"

cd ../..
echo ""
echo "vendor/ wiederhergestellt und vollstaendig verifiziert: $(du -sh vendor | cut -f1)"
