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
    # Alle Dateien abwarten: intakeFile läuft asynchron je Datei; ein Klick auf „Berechnen“
    # vor der letzten Datei löst „Dateien wurden während der Berechnung geändert“ aus
    page.wait_for_function(f"document.querySelectorAll('#file-tbody tr').length === {len(UPLOAD_FILES)}")

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
        if name.endswith(".csv"):
            # CSV byte-gleich (seit v1.3 liest der Bootstrap die Reports als Bytes, CRLF bleibt)
            ok = ref.read_bytes() == content.encode("utf-8")
        else:
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

    # 6) Erkennung ohne Rechnen: englischer Bisq-Export (Fixture) und eine CSV mit BOM
    print("\nErkennung Sonderfälle (nur Sniffing):")
    fixture_en = (BASE.parent / "tests" / "fixtures" / "bisq_en.csv").read_bytes()
    bisq_de_bom = b"\xef\xbb\xbf" + (EXAMPLES / "Broker/bisq.csv").read_bytes()
    # Wallet-Software (v1.4): alle Kopfzeilen-Generationen, Dateiname mit „nokyc" → noKYC
    wallets = {f"wallet-{n}": (BASE.parent / "tests" / "fixtures" / n).read_bytes() for n in (
        "sparrow.csv", "sparrow_alt.csv", "electrum.csv", "electrum_46.csv", "electrum_45.csv",
        "trezor.csv", "trezor_semikolon.csv", "ledger.csv")}
    wallets["wallet-ledger-nokyc.csv"] = wallets["wallet-ledger.csv"]
    # Semikolon nur bei Trezor zulässig — eine in Excel umgespeicherte Sparrow-Datei sperrt (Audit v1.4)
    wallets["semi-sparrow.csv"] = wallets["wallet-sparrow.csv"].replace(b",", b";")
    page2 = browser.new_page()
    page2.goto("http://localhost:8741/index.html")
    sammel = {f"sammel-{n}": (BASE.parent / "tests" / "fixtures" / n).read_bytes() for n in (
        "sammel_ct_import.csv", "sammel_ct_export.csv", "sammel_ct_full.csv", "sammel_blockpit_new.csv", "sammel_blockpit_old.csv")}
    page2.set_input_files("#file-input", files=[
        {"name": "tradeHistory.csv", "mimeType": "text/csv", "buffer": fixture_en},
        {"name": "bisq-bom.csv", "mimeType": "text/csv", "buffer": bisq_de_bom},
    ] + [{"name": n, "mimeType": "text/csv", "buffer": b} for n, b in sammel.items()]
      + [{"name": n, "mimeType": "text/csv", "buffer": b} for n, b in wallets.items()])
    page2.wait_for_selector("#file-table:not(.hidden)")
    page2.wait_for_function(f"document.querySelectorAll('#file-tbody tr').length === {2 + len(sammel) + len(wallets)}")
    rows2 = page2.evaluate("""
        Array.from(document.querySelectorAll('#file-tbody tr')).map(tr => ({
            name: tr.cells[0].textContent, type: tr.querySelector('select').value }))
    """)
    for row in rows2:
        expected = "sammel" if row["name"].startswith("sammel-") else "bisq"
        if row["name"].startswith("wallet-"):
            expected = "wallet_nokyc" if "nokyc" in row["name"] else "wallet"
        if row["name"].startswith("semi-"):
            expected = "unknown"
        ok = row["type"] == expected
        print(f"  {'✓' if ok else '✗'} {row['name']}: {row['type']}" + ("" if ok else f" (erwartet: {expected})"))
        if not ok:
            failures.append(f"Sniffing {row['name']}: {row['type']} != {expected}")

    # 7) Rechenlauf mit Wallet-Exporten (Sparrow, Trezor, Ledger + Broker, eine Datei noKYC):
    #    Reports byte-gleich zur CLI auf denselben Daten — prüft Platzierung (wallets/, wallets/nokyc/)
    #    und dass die neuen Module in SRC_FILES stehen
    print("\nRechenlauf mit Wallet-Exporten gegen CLI:")
    import shutil, subprocess, tempfile
    fx = BASE.parent / "tests" / "fixtures"
    sparrow_cold = ("Date (UTC),Label,Value (BTC),Balance (BTC),Fee (BTC),Txid\n"
                    "2022-05-02 14:00:00,,0.01000000,0.01000000,,c0c0000000000000000000000000000000000000000000000000000000000001\n"
                    "2023-06-01 10:00:00,Konsolidierung,-0.00001000,0.00999000,0.00001000,c0c0000000000000000000000000000000000000000000000000000000000002\n").encode()
    upload = {"21bitcoin-gesamt.csv": (EXAMPLES / "Broker/21bitcoin-gesamt.csv").read_bytes(),
              "cold.csv": sparrow_cold, "tresor.csv": (fx / "trezor.csv").read_bytes(),
              "ledger_nokyc.csv": (fx / "ledger.csv").read_bytes()}
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "Broker").mkdir(); (d / "wallets" / "nokyc").mkdir(parents=True)
        (d / "Broker/21bitcoin-gesamt.csv").write_bytes(upload["21bitcoin-gesamt.csv"])
        (d / "wallets/cold.csv").write_bytes(upload["cold.csv"])
        (d / "wallets/tresor.csv").write_bytes(upload["tresor.csv"])
        (d / "wallets/nokyc/ledger_nokyc.csv").write_bytes(upload["ledger_nokyc.csv"])
        subprocess.run([sys.executable, "-m", "src.main", "--all", "--nachweis", "--csv", "--data-dir", str(d)],
                       cwd=BASE.parent, check=True, capture_output=True)
        cli = {f.name: f.read_bytes() for f in (d / "reports").iterdir()}
    page3 = browser.new_page()
    page3.goto("http://localhost:8741/index.html")
    page3.set_input_files("#file-input", files=[{"name": n, "mimeType": "text/csv", "buffer": b} for n, b in upload.items()])
    page3.wait_for_function(f"document.querySelectorAll('#file-tbody tr').length === {len(upload)}")
    page3.click("#btn-run")
    page3.wait_for_function("window.__GUI_DONE === true", timeout=180_000)
    err3 = page3.evaluate("window.__GUI_ERROR || null")
    if err3:
        failures.append(f"Wallet-Lauf: Browser-Fehler {err3}")
        print(f"  ✗ Browser-Fehler: {err3}")
    else:
        got = page3.evaluate("window.__GUI_RESULT")["reports"]
        for name in sorted(set(cli) | set(got)):
            if name not in got or name not in cli:
                failures.append(f"Wallet-Lauf: {name} nur in {'CLI' if name in cli else 'Browser'}")
                print(f"  ✗ {name}: nur in {'CLI' if name in cli else 'Browser'}")
                continue
            norm = lambda b: b"\n".join(l for l in b.replace(b"\r\n", b"\n").split(b"\n") if b"Erstellt am" not in l)
            ok = norm(cli[name]).rstrip(b"\n") == norm(got[name].encode("utf-8")).rstrip(b"\n")
            print(f"  {'✓' if ok else '✗'} {name}")
            if not ok:
                failures.append(f"Wallet-Lauf: {name} weicht von der CLI ab")
    browser.close()

print()
if failures:
    print(f"FEHLGESCHLAGEN ({len(failures)}):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("ALLE TESTS BESTANDEN ✓")
