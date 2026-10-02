#!/usr/bin/env python3
"""make_shots.py — Screenshots für den Steuertool-Trailer (DE + EN), Android-Optik, Beispieldaten aus examples/, 412×880 bei 3×.
Voraussetzung: web/build.sh und  python3 -m http.server 8741 --directory web/dist
Die Android-Hülle wird nur für die Optik nachgestellt (window.Capacitor mit SaveFile-Stub → App-Kopf, DROID-Texte); gespeichert wird nichts.
Ausgabe shots/<name>-<lang>.png"""
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent; OUT = ROOT / "shots"; OUT.mkdir(exist_ok=True)
STUB = "window.Capacitor={isNativePlatform:()=>true,Plugins:{SaveFile:{save:async()=>({saved:false})}}};"


def scroll_to(pg, selector, offset=20):
    pg.evaluate("([s,o])=>{const e=document.querySelector(s); window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - o)}", [selector, offset])


def scroll_to_text(pg, needle, offset=60):
    """Scrollt im Report zu einer Textstelle (pre ohne eigenen Scrollbereich)."""
    pg.evaluate("""([n,o])=>{const pre=document.getElementById('report-view'); const t=pre.firstChild; const i=t.textContent.indexOf(n);
        if(i<0) throw new Error('nicht gefunden: '+n); const r=document.createRange(); r.setStart(t,i); r.setEnd(t,i+n.length);
        window.scrollTo(0, r.getBoundingClientRect().top + window.scrollY - o)}""", [needle, offset])


def tab(pg, group, pattern):
    pg.evaluate("""([g,p])=>{const b=[...document.querySelectorAll('#'+g+' .tab-btn')].find(x=>new RegExp(p,'i').test(x.textContent));
        if(!b) throw new Error('Tab fehlt: '+p); b.click()}""", [group, pattern])


def shot(pg, name, lang):
    pg.wait_for_timeout(400)
    pg.screenshot(path=str(OUT / f"{name}-{lang}.png")); print("  ✓", name, lang)


with sync_playwright() as p:
    b = p.chromium.launch()
    for lang in ("de", "en"):
        ctx = b.new_context(viewport={"width": 412, "height": 880}, device_scale_factor=3, is_mobile=True, has_touch=True)
        ctx.add_init_script(STUB)
        pg = ctx.new_page(); pg.goto(f"http://localhost:8741/index.html?lang={lang}")
        pg.wait_for_function("document.documentElement.classList.contains('app')")
        # Keine Hosternamen ins Video brennen (Regel App-Trailer 01.10.2026): die GitHub-Zeile der Datenschutz-Leiste nur fürs Bild ausblenden
        pg.evaluate("[...document.querySelectorAll('#privacy-strip span')].filter(s=>/GitHub/.test(s.textContent)).forEach(s=>s.style.display='none')")
        shot(pg, "start", lang)                                   # App-Kopf + Datenschutz-Leiste (ohne Internet-Berechtigung)
        scroll_to(pg, "#dropzone", 140); shot(pg, "dropzone", lang)   # Dateien antippen, nichts wird hochgeladen
        pg.click("#btn-demo")
        pg.wait_for_function("files.length > 0 && !document.getElementById('btn-run').disabled", timeout=60000)
        pg.evaluate("ensureWorker()")   # Rechenkern vorab laden, damit kein „wird geladen“-Hinweis im Bild steht
        pg.wait_for_function("!document.getElementById('py-loading').classList.contains('show')", timeout=120000)
        scroll_to(pg, "#file-table", 90); shot(pg, "files", lang)    # erkannte Broker, noKYC orange
        pg.click("#btn-run"); pg.wait_for_function("window.__GUI_DONE === true", timeout=120000)
        assert pg.evaluate("window.__GUI_ERROR") is None
        tab(pg, "year-tabs", "2024"); tab(pg, "doc-tabs", "steuerreport|tax report")
        scroll_to(pg, "#results-card", 10); shot(pg, "report", lang)
        scroll_to_text(pg, "GEBÜHREN IN BITCOIN", 140); shot(pg, "fees", lang)
        tab(pg, "doc-tabs", "nachweis|evidence"); scroll_to(pg, "#results-card", 10); shot(pg, "proof", lang)
        tab(pg, "doc-tabs", "nokyc"); scroll_to(pg, "#results-card", 10); shot(pg, "nokyc", lang)
        scroll_to(pg, "#btn-download-all", 520); shot(pg, "save", lang)
        pg.evaluate("window.scrollTo(0,0)"); pg.click(".app-help"); shot(pg, "help", lang)
        ctx.close()
    b.close()
