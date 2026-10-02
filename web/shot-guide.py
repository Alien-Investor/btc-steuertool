#!/usr/bin/env python3
"""shot-guide.py — Screenshots für steuertool-guide.html (DE + EN), Desktop-Breite, Beispieldaten aus examples/.
Voraussetzung: web/build.sh und  python3 -m http.server 8741 --directory web/dist
Ausgabe web/guide-shots/steuertool-guide-<name>[-en].png (DE ohne Suffix, wie die bisherigen Dateinamen der Website)."""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).parent / "guide-shots"; OUT.mkdir(exist_ok=True)
MAX_H = 900   # lange Karten (Report) oben abschneiden, wie die bisherigen Guide-Bilder


def tab(pg, group, pattern):
    pg.evaluate("""([g,p])=>{const b=[...document.querySelectorAll('#'+g+' .tab-btn')].find(x=>new RegExp(p,'i').test(x.textContent));
        if(!b) throw new Error('Tab fehlt: '+p); b.click()}""", [group, pattern])


def card(pg, selector, name, lang):
    el = pg.locator(selector).first
    el.scroll_into_view_if_needed(); pg.wait_for_timeout(400)
    box = el.bounding_box()
    suffix = "" if lang == "de" else "-en"
    pg.screenshot(path=str(OUT / f"steuertool-guide-{name}{suffix}.png"), full_page=True,
                  clip={"x": box["x"], "y": box["y"] + pg.evaluate("window.scrollY"), "width": box["width"], "height": min(box["height"], MAX_H)})
    print("  ✓", name, lang)


with sync_playwright() as p:
    b = p.chromium.launch()
    for lang in ("de", "en"):
        ctx = b.new_context(viewport={"width": 1100, "height": 1000})
        pg = ctx.new_page(); pg.goto(f"http://localhost:8741/index.html?lang={lang}")
        pg.wait_for_selector("#dropzone")
        pg.wait_for_timeout(600)
        pg.screenshot(path=str(OUT / f"steuertool-guide-start{'' if lang == 'de' else '-en'}.png"), clip={"x": 0, "y": 0, "width": 1100, "height": 700})
        print("  ✓ start", lang)
        pg.click("#btn-demo")
        pg.wait_for_function("files.length > 0 && !document.getElementById('btn-run').disabled", timeout=60000)
        pg.evaluate("ensureWorker()")   # Rechenkern vorab laden, damit kein „wird geladen“-Hinweis im Bild steht
        pg.wait_for_function("!document.getElementById('py-loading').classList.contains('show')", timeout=180000)
        card(pg, "#dropzone >> xpath=ancestor::div[contains(@class,'card')][1]", "dateien", lang)
        pg.click("#btn-run"); pg.wait_for_function("window.__GUI_DONE === true", timeout=180000)
        assert pg.evaluate("window.__GUI_ERROR") is None
        card(pg, "#status-card", "log", lang)
        tab(pg, "year-tabs", "2024"); tab(pg, "doc-tabs", "steuerreport|tax report")
        card(pg, "#results-card", "report", lang)
        tab(pg, "doc-tabs", "nokyc")
        card(pg, "#results-card", "nokyc", lang)
        ctx.close()
    b.close()
