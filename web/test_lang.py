#!/usr/bin/env python3
"""Test des DE/EN-Toggles: ?lang-Param, Toggle-Button, Beispieldaten-Lauf, Tab-Labels."""
import sys
from playwright.sync_api import sync_playwright

failures = []

def check(name, cond, extra=""):
    print(f"  {'✓' if cond else '✗'} {name}" + (f" — {extra}" if extra and not cond else ""))
    if not cond:
        failures.append(name)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    # 1) Vollversion, Default = DE
    page.goto("http://localhost:8741/index.html")
    print("Vollversion DE (Default):")
    check("Back-Link = '← Zentrale'", page.inner_text("#back-link").strip().lower() == "← zentrale", page.inner_text("#back-link"))
    check("Lang-Button zeigt EN", page.inner_text("#lang-toggle").strip() == "EN")
    check("btn-run deutsch", "berechnen" in page.inner_text("#btn-run").lower())
    check("html lang=de", page.get_attribute("html", "lang") == "de")

    # 2) Toggle auf EN
    page.click("#lang-toggle")
    print("Nach Toggle (EN):")
    check("Back-Link = '← HQ'", page.inner_text("#back-link").strip() == "← HQ", page.inner_text("#back-link"))
    check("Back-Href = /en/", page.get_attribute("#back-link", "href") == "https://alien-investor.org/en/")
    check("Guide-Href = /en/guide", page.get_attribute("#guide-btn", "href") == "https://alien-investor.org/en/steuertool-guide.html")
    check("Lang-Button zeigt DE", page.inner_text("#lang-toggle").strip() == "DE")
    check("btn-run englisch", "calculate" in page.inner_text("#btn-run").lower())
    check("Dropzone englisch", "Drag your CSV exports" in page.inner_text("#dropzone"))
    check("Disclaimer-Hinweis 'German'", "generated in German" in page.inner_text("#disclaimer-text"))
    check("html lang=en", page.get_attribute("html", "lang") == "en")
    check("Titel englisch", "Tax Report" in page.title())

    # 3) localStorage-Persistenz bei Reload
    page.reload()
    print("Nach Reload (localStorage):")
    check("EN bleibt aktiv", page.inner_text("#back-link").strip() == "← HQ")

    # 4) ?lang=de überschreibt localStorage
    page.goto("http://localhost:8741/index.html?lang=de")
    print("?lang=de-Override:")
    check("Back-Link = '← Zentrale'", page.inner_text("#back-link").strip().lower() == "← zentrale")

    # 5) Beispieldaten-Lauf auf EN: Dropzone, Button, kompletter Lauf, Tab-Labels
    page.goto("http://localhost:8741/index.html?lang=en")
    print("Beispieldaten EN:")
    check("Dropzone englisch", "sample data (ZIP)" in page.inner_text("#dropzone"))
    check("Button englisch", page.inner_text("#btn-demo").strip().lower() == "try with sample data")
    check("Kein Preis-CTA mehr", page.query_selector("#demo-cta") is None)
    page.click("#btn-demo")
    page.wait_for_selector("#file-table:not(.hidden)")
    sel_label = page.eval_on_selector("#file-tbody tr select", "s => s.selectedOptions[0].textContent")
    check("Dropdown-Label englisch", "wallet" in sel_label or "21bitcoin" in sel_label, sel_label)
    page.click("#btn-run")
    page.wait_for_function("window.__GUI_DONE === true", timeout=180_000)
    err = page.evaluate("window.__GUI_ERROR || null")
    check("Lauf ohne Fehler", err is None, str(err))
    tabs = page.eval_on_selector_all("#doc-tabs .tab-btn", "els => els.map(e => e.textContent)")
    check("Doc-Tabs englisch", "Tax report" in tabs and "Tax evidence" in tabs, str(tabs))
    log_text = page.inner_text("#log")
    check("Log englisch", "Done:" in log_text and "transactions" in log_text)
    # Report-Inhalt bleibt deutsch
    report = page.inner_text("#report-view")
    check("Report-Inhalt deutsch", "STEUERREPORT" in report or "Steuer" in report or "BITCOIN" in report.upper())

    # 6) Sprachwechsel NACH Berechnung — Tabs müssen umspringen
    page.click("#lang-toggle")
    print("Toggle DE nach Berechnung:")
    tabs = page.eval_on_selector_all("#doc-tabs .tab-btn", "els => els.map(e => e.textContent)")
    check("Doc-Tabs deutsch", "Steuerreport" in tabs and "Steuernachweis" in tabs, str(tabs))
    # Anzahl kommt aus dem Kern (report_years) — seit H8 zaehlt auch ein Jahr,
    # in dem nur eine Gebuehr in BTC anfiel; nicht hart auf 3 festnageln.
    n_years = len(page.evaluate("window.__GUI_RESULT.years"))
    check("Jahres-Tabs noch da", len(page.eval_on_selector_all("#year-tabs .tab-btn", "els => els")) == n_years and n_years >= 3)
    check("Report-Ansicht nicht leer", len(page.inner_text("#report-view")) > 100)

    page.screenshot(path="/tmp/gui-en-screenshot.png", full_page=True)
    browser.close()

print()
if failures:
    print(f"FEHLGESCHLAGEN ({len(failures)}):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALLE SPRACH-TESTS BESTANDEN ✓")
