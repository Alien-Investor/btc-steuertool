#!/usr/bin/env bash
# web/dist (unverändert) → mobile/www, plus Android-CSP als Meta-Tag (die Web-CSP kommt von nginx, die Desktop-CSP aus main.js).
set -euo pipefail
cd "$(dirname "$0")"
../web/build.sh
rm -rf www && cp -r ../web/dist www
CSP="default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'"
python3 - "$CSP" <<'PY'
import sys, pathlib
p = pathlib.Path("www/index.html"); s = p.read_text(encoding="utf-8")
tag = '<meta charset="UTF-8">'
assert s.count(tag) == 1, "Anker fehlt"
s = s.replace(tag, tag + '\n  <meta http-equiv="Content-Security-Policy" content="' + sys.argv[1] + '">')
p.write_text(s, encoding="utf-8")
PY
echo "www/ gebaut: $(du -sh www | cut -f1)"
