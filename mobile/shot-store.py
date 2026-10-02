#!/usr/bin/env python3
"""Store-Screenshots der Android-Fassung (Zap Store: 412×900 @2x = 824×1800, Englisch) aus web/dist.

Voraussetzung: `web/build.sh` und `python3 -m http.server 8741 --directory web/dist`.
Die Android-Hülle wird nur für die Optik nachgestellt (window.Capacitor mit SaveFile-Stub → DROID-Texte, App-Kopf html.app);
gespeichert wird nichts. Ziel: mobile/screenshots/1-start.png, 2-report.png, 3-help.png (versioniert, Quelle für zapstore.yaml).
Aufruf:  python3 mobile/shot-store.py [--lang de]
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

LANG = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv else "en"
URL = f"http://localhost:8741/index.html?lang={LANG}"
OUT = Path(__file__).resolve().parent / "screenshots"
if LANG != "en":
    OUT = OUT / LANG
OUT.mkdir(parents=True, exist_ok=True)
STUB = """window.Capacitor = { isNativePlatform: () => true,
  Plugins: { SaveFile: { save: async () => ({ saved: false }) } } };"""

with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 412, "height": 900}, device_scale_factor=2, is_mobile=True, has_touch=True)
    ctx.add_init_script(STUB)
    page = ctx.new_page()
    page.goto(URL)
    page.wait_for_function("document.documentElement.classList.contains('app')")
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "1-start.png"))

    page.click("#btn-demo")
    page.wait_for_function("files.length > 0 && !document.getElementById('btn-run').disabled", timeout=60000)
    page.click("#btn-run")
    page.wait_for_function("window.__GUI_DONE === true", timeout=120000)
    # Jahr 2024 + Steuernachweis zeigen (Tabs: #year-tabs / #doc-tabs, .tab-btn)
    page.evaluate("""(() => {
        const y = [...document.querySelectorAll('#year-tabs .tab-btn')].find(b => b.textContent.includes('2024')); if (y) y.click();
        const d = [...document.querySelectorAll('#doc-tabs .tab-btn')].find(b => /nachweis|evidence/i.test(b.textContent)); if (d) d.click();
        document.getElementById('results-card').scrollIntoView({block: 'start'}); })()""")
    page.wait_for_timeout(300)
    page.screenshot(path=str(OUT / "2-report.png"))

    page.evaluate("window.scrollTo(0, 0)")
    page.click(".app-help")
    page.wait_for_timeout(400)
    page.screenshot(path=str(OUT / "3-help.png"))
    browser.close()
for f in sorted(OUT.glob("*.png")):
    print("OK", f)
