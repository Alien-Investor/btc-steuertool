#!/bin/bash
# Baut dist/ der Steuertool Web-App (statisch auslieferbar, z. B. unter /steuertool/).
# src/ und examples/ kommen aus dem Repo-Root (eine Ebene höher).
set -euo pipefail
cd "$(dirname "$0")"

rm -rf dist
mkdir -p dist

# Versionsanzeige: App-Version aus VERSION, für die Web-Version das Datum des letzten Commits
VERSION_NAME=$(sed -n 's/^VERSION_NAME=//p' ../VERSION)
WEB_STAND=$(git -C .. log -1 --format=%cd --date=format:%d.%m.%Y 2>/dev/null || date +%d.%m.%Y)
[[ "$VERSION_NAME" =~ ^[0-9]+(\.[0-9]+){1,2}$ ]] || { echo "FEHLER: VERSION_NAME '$VERSION_NAME' ungültig" >&2; exit 1; }
sed -e "s/__APP_VERSION__/$VERSION_NAME/" -e "s/__WEB_STAND__/$WEB_STAND/" index.html > dist/index.html
grep -q "__APP_VERSION__\|__WEB_STAND__" dist/index.html && { echo "FEHLER: Versions-Platzhalter nicht ersetzt" >&2; exit 1; }
cp worker.js dist/        # Pyodide-Worker (gleich-origin, kein blob: → keine CSP-Änderung)
cp -rL ../src dist/src
cp -rL ../examples dist/examples
# web/vendor/ ist nicht versioniert: gebaut wird nur mit genau den Dateien aus web/vendor.sha256 (v1.5, Release-Audit R1 b-B1)
[ -f vendor.sha256 ] && [ -z "$(find vendor -type l)" ] || { echo "FEHLER: web/vendor.sha256 fehlt oder Symlink in web/vendor/" >&2; exit 1; }
[ "$(cd vendor && find . -type f | sed 's#^\./##' | LC_ALL=C sort)" = "$(awk '{print $2}' vendor.sha256 | LC_ALL=C sort)" ] \
  || { echo "FEHLER: web/vendor/ hat andere Dateien als web/vendor.sha256 — web/vendor-setup.sh" >&2; exit 1; }
(cd vendor && sha256sum -c --strict --quiet ../vendor.sha256) || { echo "FEHLER: web/vendor/ weicht von web/vendor.sha256 ab — web/vendor-setup.sh" >&2; exit 1; }
cp -r vendor dist/vendor

# Aufräumen: Python-Caches und generierte Beispiel-Reports gehören nicht ins Deployment
find dist -name __pycache__ -type d -prune -exec rm -rf {} +
rm -rf dist/examples/reports

# Beispieldaten als ZIP (Drag&Drop-Weg zum Ausprobieren)
python3 -I - <<'PY'   # -I: kein Modul aus dem Arbeitsordner (Release-Audit R1 b-B1)
import zipfile, pathlib
files = [
    "examples/bitbox/wallet1.csv", "examples/bitbox/nokyc/nokyc_wallet.csv",
    "examples/Broker/21bitcoin-gesamt.csv", "examples/Broker/Bison-CSV-Gesamt.csv",
    "examples/Broker/bisq.csv", "examples/Broker/Pocket_2024.csv",
    "examples/Broker/strike_2024.csv", "examples/Broker/Swissquote_CSV-Gesamt.csv",
    "examples/fx_cache.json", "examples/manual_buys.csv", "examples/manual_sales.csv",
    "examples/transfer_zuordnung.csv",
]
with zipfile.ZipFile("dist/examples/beispieldaten.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in files:
        z.write(pathlib.Path("dist") / f, pathlib.Path(f).name)
print("beispieldaten.zip erzeugt")
PY

echo "dist/ gebaut: $(find dist -type f | wc -l) Dateien, $(du -sh dist | cut -f1)"
