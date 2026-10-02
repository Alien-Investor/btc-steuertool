#!/usr/bin/env python3
"""End-to-End-Test der GUI: lädt die Beispiel-CSVs über den echten File-Input,
prüft die automatische Broker-Erkennung und vergleicht die Reports mit der
CLI-Referenz unter /tmp/poc-ref/examples/reports/."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).parent
EXAMPLES = (BASE.parent / "examples").resolve()
REF_DIR = Path("/tmp/poc-ref/examples/reports")
OUT_DIR = Path("/tmp/gui-browser-reports")
OUT_DIR.mkdir(exist_ok=True)

UPLOAD_FILES = [
    EXAMPLES / "bitbox/wallet1.csv",
    EXAMPLES / "bitbox/nokyc/nokyc_wallet.csv",
    EXAMPLES / "Broker/21bitcoin-gesamt.csv",
    EXAMPLES / "Broker/Bison-CSV-Gesamt.csv",
    EXAMPLES / "Broker/bisq.csv",
    EXAMPLES / "Broker/Pocket_2024.csv",
    EXAMPLES / "Broker/strike_2024.csv",
    EXAMPLES / "Broker/Swissquote_CSV-Gesamt.csv",
    EXAMPLES / "fx_cache.json",
    EXAMPLES / "manual_buys.csv",
    EXAMPLES / "manual_sales.csv",
    EXAMPLES / "transfer_zuordnung.csv",
]

EXPECTED_TYPES = {
    "wallet1.csv": "bitbox",
    "nokyc_wallet.csv": "bitbox_nokyc",
    "21bitcoin-gesamt.csv": "btc21",
    "Bison-CSV-Gesamt.csv": "bison",
    "bisq.csv": "bisq",
    "Pocket_2024.csv": "pocket",
    "strike_2024.csv": "strike",
    "Swissquote_CSV-Gesamt.csv": "swissquote",
    "fx_cache.json": "fxcache",
    "manual_buys.csv": "manual_buys",
    "manual_sales.csv": "manual_sales",
    "transfer_zuordnung.csv": "zuordnung",
}

failures = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.on("console", lambda msg: msg.type == "error" and print(f"  console[error] {msg.text}"))
    page.goto("http://localhost:8741/index.html")

    # 1) Upload über den echten File-Input
    page.set_input_files("#file-input", [str(f) for f in UPLOAD_FILES])
    page.wait_for_selector("#file-table:not(.hidden)")

    # 2) Sniffing prüfen
    rows = page.evaluate("""
        Array.from(document.querySelectorAll('#file-tbody tr')).map(tr => ({
            name: tr.cells[0].textContent,
            type: tr.querySelector('select').value,
        }))
    """)
    print("Erkennung:")
    for row in rows:
        expected = EXPECTED_TYPES.get(row["name"])
        ok = row["type"] == expected
        print(f"  {'✓' if ok else '✗'} {row['name']}: {row['type']}" + ("" if ok else f" (erwartet: {expected})"))
        if not ok:
            failures.append(f"Sniffing {row['name']}: {row['type']} != {expected}")

    # 3) Berechnen
    page.click("#btn-run")
    page.wait_for_function("window.__GUI_DONE === true", timeout=180_000)

    error = page.evaluate("window.__GUI_ERROR || null")
    if error:
        print(f"BROWSER-FEHLER: {error}")
        browser.close()
        sys.exit(1)

    result = page.evaluate("window.__GUI_RESULT")
    print(f"\nPipeline: {result['tx_count']} Transaktionen, Jahre {result['years']}")

    # 4) Reports gegen CLI-Referenz diffen (Zeilenenden normalisiert)
    print("\nReport-Vergleich gegen CLI-Referenz:")
    for name, content in result["reports"].items():
        (OUT_DIR / name).write_text(content, encoding="utf-8")
        ref = REF_DIR / name
        if not ref.exists():
            failures.append(f"Referenz fehlt: {name}")
            print(f"  ✗ {name}: keine CLI-Referenz")
            continue
        a = ref.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n")
        b = content.replace("\r\n", "\n").rstrip("\n")
        ok = a == b
        print(f"  {'✓' if ok else '✗'} {name}")
        if not ok:
            failures.append(f"Inhalt weicht ab: {name}")
    missing = set(f.name for f in REF_DIR.glob("*")) - set(result["reports"].keys())
    for m in sorted(missing):
        failures.append(f"Report fehlt im Browser: {m}")
        print(f"  ✗ fehlt im Browser: {m}")

    # 5) UI-Funktionen: Jahres-Tab + noKYC-Badge
    page.click("#year-tabs .tab-btn:first-child")          # ältestes Jahr
    page.click("#doc-tabs .tab-btn:first-child")
    visible_text = page.inner_text("#report-view")
    if "Bitcoin" not in visible_text and "KÄUFE" not in visible_text:
        failures.append("Report-Ansicht leer nach Tab-Wechsel")

    page.screenshot(path="/tmp/gui-screenshot.png", full_page=True)
    browser.close()

print()
if failures:
    print(f"FEHLGESCHLAGEN ({len(failures)}):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALLE TESTS BESTANDEN ✓")
