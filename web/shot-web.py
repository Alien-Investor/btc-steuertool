#!/usr/bin/env python3
"""shot-demo.py — Screenshots der BTC-Steuertool-Web-Version (DE + EN).

Schiesst die oeffentliche Web-App (eigene Domain, Waechter-freigegeben) fuer
Nostr-/Website-Posts. Bilder sind Wegwerf-Artefakte: NICHT versionieren,
immer frisch schiessen -> zeigt garantiert den aktuellen Tool-Stand.

Aufruf:
    python3 shot-demo.py            # -> ~/Downloads/steuertool-web-{de,en}.png
    python3 shot-demo.py --out DIR  # anderer Zielordner

Browser: gebuendeltes Chromium von Playwright (NICHT der Chrome-Channel des MCP,
der ist nicht installiert). Falls es fehlt, einmalig:
    python3 -m playwright install chromium
Playwright gegen api.alien-investor.org ist im Waechter-Hook freigegeben.
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

DEMO = "https://api.alien-investor.org/steuertool/?lang={lang}"

out = Path.home() / "Downloads"
args = sys.argv[1:]
if "--out" in args:
    i = args.index("--out")
    out = Path(args[i + 1]).expanduser().resolve()
out.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 860},
                              device_scale_factor=2)
    for lang in ("de", "en"):
        page = ctx.new_page()
        page.goto(DEMO.format(lang=lang), wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(2500)
        dest = out / f"steuertool-web-{lang}.png"
        page.screenshot(path=str(dest))
        print(f"OK  {dest}")
        page.close()
    browser.close()
