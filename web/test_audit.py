#!/usr/bin/env python3
"""GUI-Regressionstests zum Security-Audit run-1 (02.10.2026). Voraussetzung wie test_gui.py:
`python3 -m http.server 8741 --directory web/dist` läuft, `web/build.sh` ist gelaufen.

Fund 2: zwei BitBox-CSVs mit gleichem Namen in verschiedenen ZIP-Ordnern — beide müssen rechnen
        (Reports byte-gleich zu einem Lauf mit unterschiedlichen Namen, Kollision im Log gemeldet).
Fund 1: nach einer Änderung der Einstufung gelten alte Ergebnisse nicht mehr; eine Änderung WÄHREND
        des Laufs sperrt „Berechnen" weiter und verwirft das Ergebnis dieses Laufs.
"""
import io
import re
import sys
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

EX = (Path(__file__).parent.parent / "examples").resolve()
URL = "http://localhost:8741/index.html?lang=de"
WALLET_B = (b"Time,Type,Amount,Unit,Fee,Fee Unit,Address,Transaction ID,Note\n"
            b"2024-03-01T12:00:00+01:00,received,100000,satoshi,,,bc1qexampleauditcccccccccccccccccccccccccc,"
            b"dddd0000000000000000000000000000000000000000000000000000000000a1,Test\n")
BROKERS = ["Broker/21bitcoin-gesamt.csv", "Broker/Bison-CSV-Gesamt.csv", "Broker/Swissquote_CSV-Gesamt.csv",
           "manual_buys.csv", "fx_cache.json"]

failures = []


def check(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond:
        failures.append(label)


def make_zip(name_a, name_b):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name_a, (EX / "bitbox/wallet1.csv").read_bytes())
        z.writestr(name_b, WALLET_B)
        for b in BROKERS:
            z.writestr(b, (EX / b).read_bytes())
    return buf.getvalue()


def run_zip(page, data):
    page.goto(URL)
    page.set_input_files("#file-input", files=[{"name": "export.zip", "mimeType": "application/zip", "buffer": data}])
    page.wait_for_selector("#file-table:not(.hidden)")
    page.wait_for_function("!document.getElementById('btn-run').disabled")
    page.click("#btn-run")
    page.wait_for_function("window.__GUI_DONE === true", timeout=120000)
    return page.evaluate("({res: window.__GUI_RESULT, err: window.__GUI_ERROR, log: document.getElementById('log').innerText})")


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()

    print("Fund 2: gleichnamige BitBox-Exporte in zwei ZIP-Ordnern")
    ctrl = run_zip(page, make_zip("geraet-a/wallet-a.csv", "geraet-b/wallet-b.csv"))
    coll = run_zip(page, make_zip("geraet-a/wallet.csv", "geraet-b/wallet.csv"))
    check(ctrl["err"] is None and coll["err"] is None, "beide Läufe ohne Fehler")
    check(coll["res"] and ctrl["res"] and coll["res"]["reports"].keys() == ctrl["res"]["reports"].keys(), "gleiche Report-Dateien")
    norm = lambda s: re.sub(r"Erstellt am:.*", "", s)

    def norm_names(k, s, mapping):
        # Der interne Wallet-Abgleich nennt die echten Dateinamen (gewollt) — nur dort
        # die Namen gleichsetzen und Leerraum der Spaltenausrichtung zusammenfassen.
        if not k.startswith("wallet_abgleich_intern_"):
            return norm(s)
        for a, b in mapping:
            s = re.sub(rf"\b{re.escape(a)}\b", b, s)
        return re.sub(r"[ \t]+", " ", norm(s))
    ren = [("wallet-a", "wallet"), ("wallet-b", "wallet_2")]
    same = coll["res"] is not None and all(
        norm_names(k, coll["res"]["reports"][k], []) == norm_names(k, ctrl["res"]["reports"][k], ren)
        for k in ctrl["res"]["reports"])
    check(same, "Reports identisch zum Lauf mit unterschiedlichen Namen (keine Wallet fehlt)")
    check("wallet_2.csv" in coll["log"], "Namenskollision im Log gemeldet")

    print("Fund 1a: Umstufen nach fertigem Lauf verwirft die Ergebnisse")
    check(page.evaluate("lastReports !== null") and page.is_visible("#results-card"), "Ergebnis sichtbar nach Lauf")
    page.evaluate("""(() => { const sel = document.querySelector('#file-tbody tr select');
        sel.value = 'bitbox_nokyc'; sel.dispatchEvent(new Event('change')); })()""")
    check(page.evaluate("lastReports === null && lastInternal.length === 0"), "lastReports verworfen")
    check(not page.is_visible("#results-card"), "Ergebniskarte ausgeblendet")

    print("Fund 1b: Umstufen WÄHREND des Laufs")
    page.goto(URL)
    page.set_input_files("#file-input", files=[{"name": "export.zip", "mimeType": "application/zip",
                                               "buffer": make_zip("a/wallet-a.csv", "b/wallet-b.csv")}])
    page.wait_for_function("!document.getElementById('btn-run').disabled")
    disabled_during = page.evaluate("""(() => {
        document.getElementById('btn-run').click();          // läuft synchron bis zum ersten await → running = true
        const sel = document.querySelector('#file-tbody tr select');
        sel.value = 'bitbox_nokyc'; sel.dispatchEvent(new Event('change'));
        return document.getElementById('btn-run').disabled; })()""")
    check(disabled_during, "„Berechnen“ bleibt während des Laufs gesperrt")
    page.wait_for_function("window.__GUI_DONE === true", timeout=120000)
    err = page.evaluate("window.__GUI_ERROR") or ""
    check("während der Berechnung geändert" in err, "Ergebnis des Laufs verworfen, Hinweis erneut berechnen")
    check(page.evaluate("lastReports === null") and not page.is_visible("#results-card"), "nichts speicherbar")
    check(not page.evaluate("document.getElementById('btn-run').disabled"), "„Berechnen“ danach wieder frei")

    print("Audit v1.4 R2-H1: ein Abbruch der Engine erreicht den Nutzer (nicht „Eingaben geändert“, kein Traceback)")
    page.goto(URL)
    bad = (b"Timestamp,Date,Time,Type,Transaction ID,Fee,Fee unit,Address,Label,Amount,Amount unit,Fiat (EUR),Other\n"
           b"1717243200,,,SENT,ab,0.0001,BTC,x,,-0.08,BTC,,\n")
    page.set_input_files("#file-input", files=[{"name": "t.csv", "mimeType": "text/csv", "buffer": bad}])
    page.wait_for_function("!document.getElementById('btn-run').disabled")
    page.click("#btn-run")
    page.wait_for_function("window.__GUI_DONE === true", timeout=120000)
    err = page.evaluate("window.__GUI_ERROR") or ""
    check("negativer Betrag" in err, f"echte Meldung angezeigt ({err[:80]})")
    check("während der Berechnung geändert" not in err, "kein falscher Hinweis „Eingaben geändert“")
    check("Traceback" not in err and "/lib/python" not in err, "kein Python-Traceback")

    browser.close()

if failures:
    print(f"\n{len(failures)} FEHLER")
    sys.exit(1)
print("\nALLE AUDIT-TESTS BESTANDEN ✓")
