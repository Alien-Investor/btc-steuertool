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

    print("v1.4: Diagnose für Bug-Reports (geschwärzt) und „Log speichern“")
    import re as _re
    # Diagnose nach dem Abbruch oben: die Meldung ist enthalten, Dateiname und Betrag nicht
    page.click("#bug-link")
    page.click("#bug-diag-create")
    page.wait_for_function("document.getElementById('bug-diag').value.length > 0", timeout=120000)
    diag = page.evaluate("document.getElementById('bug-diag').value")
    check("negativer Betrag" in diag and "Abbruch" in diag, "Abbruchmeldung in der Diagnose")
    check("t.csv" not in diag and "0.08" not in diag, "kein Dateiname, kein Betrag")
    with page.expect_download() as dl:
        page.click("#bug-diag-save")
    check(dl.value.suggested_filename == "steuertool-diagnose.txt", "Diagnose speicherbar")
    page.click("#bug-send")
    body = page.evaluate("document.getElementById('bug-sent-body').value")
    check(diag.strip() in body, "Diagnose steht im Mail-Text")
    page.click("#bug-cancel")
    # Beispieldaten (mit noKYC-Wallet, Bisq, manual_buys): keine Namen, keine Beträge, kein noKYC
    page.goto(URL)
    page.click("#btn-demo")
    page.wait_for_selector("#file-table:not(.hidden)")
    page.click("#btn-run")
    page.wait_for_function("window.__GUI_DONE === true", timeout=180000)
    page.click("#bug-link")
    page.click("#bug-diag-create")
    page.wait_for_function("document.getElementById('bug-diag').value.length > 0", timeout=120000)
    diag = page.evaluate("document.getElementById('bug-diag').value")
    check("ohne Abbruch" in diag and "nicht aufgeschlüsselt" in diag, "Diagnose der Beispieldaten erstellt")
    for bad in ("nokyc", "wallet1", "Bisq", "P2P", "gesamt"):
        check(bad.lower() not in diag.lower(), f"„{bad}“ nicht in der Diagnose")
    # Die Kopfzeile nennt den Stand der Web-Version (ein gewolltes Datum) — nur den Rest prüfen
    body = "\n".join(l for l in diag.splitlines() if not l.startswith("Plattform:"))
    check(not _re.search(r"\d+[.,]\d{2,}|\b\d{4}-\d{2}-\d{2}\b|\b[0-9a-f]{16,}\b", body), "keine Beträge, Daten, IDs")
    page.click("#bug-cancel")
    with page.expect_download() as dl:
        page.click("#btn-log-save")
    path = dl.value.path()
    content = open(path, encoding="utf-8").read()
    check(dl.value.suggested_filename == "steuertool-log-INTERN.txt" and content.startswith("!! INTERN"),
          "Log speichern: Datei als intern gekennzeichnet")

    print("Versionsanzeige: Fuß und Diagnose")
    import re as _re2
    foot = page.inner_text("#app-version")
    check(bool(_re2.fullmatch(r"Web · Stand \d{2}\.\d{2}\.\d{4}", foot)), f"Fuß zeigt den Stand der Web-Version ({foot})")
    page.click("#lang-toggle")
    check(page.inner_text("#app-version").startswith("Web · as of "), "Fuß englisch")
    page.click("#lang-toggle")

    print("Audit v1.4 R3: Abbruch aus einer noKYC-Datei — Nutzer sieht die Meldung, Diagnose nur den allgemeinen Satz")
    page.goto(URL)
    nk = (b"Date (UTC),Label,Value (BTC),Balance (BTC),Fee (BTC),Txid\n"
          b"2024-01-02 03:04:05,Treffen Erbe,0.10000000,0.10000000,,\n")
    page.set_input_files("#file-input", files=[{"name": "geheim_nokyc.csv", "mimeType": "text/csv", "buffer": nk}])
    page.wait_for_function("!document.getElementById('btn-run').disabled")
    page.click("#btn-run")
    page.wait_for_function("window.__GUI_DONE === true", timeout=120000)
    err = page.evaluate("window.__GUI_ERROR") or ""
    check("Txid fehlt" in err, "Nutzer sieht die echte Meldung")
    page.click("#bug-link")
    page.click("#bug-diag-create")
    page.wait_for_function("document.getElementById('bug-diag').value.length > 0", timeout=120000)
    diag = page.evaluate("document.getElementById('bug-diag').value")
    check("Version: Stand " in diag, "Diagnose nennt den Stand")
    check("private Angaben" in diag and "Txid" not in diag and "geheim" not in diag.lower(),
          "Diagnose: nur der allgemeine Satz")
    check("weitere Dateien (nicht aufgeschlüsselt): 1" in diag, "noKYC-Datei nur gezählt")

    print("Audit v1.4 R3: Rechenkern lädt nicht — Meldung statt Hängen, zweiter Versuch klappt")
    page2 = browser.new_page()
    page2.route("**/pyodide.js", lambda route: route.abort())
    page2.goto(URL)
    page2.click("#btn-demo")
    page2.wait_for_selector("#file-table:not(.hidden)")
    page2.click("#btn-run")
    page2.wait_for_function("window.__GUI_DONE === true", timeout=150000)
    err = page2.evaluate("window.__GUI_ERROR") or ""
    check("Rechenkern konnte nicht geladen werden" in err, f"verständliche Meldung ({err[:70]})")
    page2.unroute("**/pyodide.js")
    page2.evaluate("window.__GUI_DONE = false; window.__GUI_ERROR = null")
    page2.click("#btn-run")
    page2.wait_for_function("window.__GUI_DONE === true", timeout=180000)
    check(not page2.evaluate("window.__GUI_ERROR"), "zweiter Versuch ohne Neuladen erfolgreich")

    browser.close()

    print("Querfund Alien Pass v1.20: Neon-Scrollbalken nur bei Maus/Trackpad, Touch behält den System-Balken")
    # Zur Laufzeit erzeugtes CSS entginge der CSSOM-Prüfung nach dem Laden (Release-Audit v1.5 R1 c H1) — es gibt keins und soll keins geben
    page_src = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")
    # auch `style`/STYLE, <style> per innerHTML/insertAdjacentHTML, <link rel=stylesheet> per JS (R2-2 H-2): genau ein <style im ganzen Text
    check(not re.search(r"createElement\(\s*['\"`]style|insertRule|adoptedStyleSheets|new CSSStyleSheet", page_src, re.I)
          and len(re.findall(r"<style", page_src, re.I)) == 1
          and re.findall(r"stylesheet", page_src, re.I) == ["stylesheet"] and '<link href="vendor/fonts/fonts.css" rel="stylesheet">' in page_src,
          "kein zur Laufzeit erzeugtes CSS in index.html (genau ein <style>-Block)")
    # Headless blendet Balken per --hide-scrollbars aus (Breite dann immer 0) — für die Messung abschalten
    sb = p.chromium.launch(ignore_default_args=["--hide-scrollbars"])
    # Balkenbreite = offsetWidth − clientWidth ohne Rahmen (das Bug-Menü hat 1 px Rahmen)
    BAR = """el => { const cs = getComputedStyle(el);
      return el.offsetWidth - el.clientWidth - parseFloat(cs.borderLeftWidth) - parseFloat(cs.borderRightWidth); }"""
    HELP = """() => { document.getElementById('help-btn').click();
      const ov = document.getElementById('help-overlay');
      return {mq: matchMedia('(hover:hover) and (pointer:fine)').matches, open: !ov.classList.contains('hidden'),
              tall: ov.scrollHeight > ov.clientHeight, bar: (%s)(ov)}; }""" % BAR
    # quer: Überlauf des Menüs; abgeschnitten: Optionen, deren Text im eigenen Kasten nicht ganz sichtbar ist (Ellipse, R2-2 H-3)
    MENU = """() => { const m = document.getElementById('bug-menu');
      return {open: !m.classList.contains('hidden'), tall: m.scrollHeight > m.clientHeight, bar: (%s)(m),
              quer: m.scrollWidth - m.clientWidth,
              abgeschnitten: [...m.querySelectorAll('.bug-opt span')].filter(e => e.scrollWidth > e.clientWidth).length}; }""" % BAR
    # Bedingung exakt (verankert): eine erweiterte Liste wie „…, (min-resolution: 2dppx)“ träfe sonst auch Handys (R1 c N1)
    CSSOM = r"""() => { const all = rs => [...rs].flatMap(r => r.cssRules ? [r, ...all(r.cssRules)] : [r]);
      const rules = [...document.styleSheets].flatMap(s => { try { return all(s.cssRules); } catch (_) { return []; } })
        .filter(r => /::-webkit-scrollbar/.test(r.selectorText || ''));
      return {n: rules.length, bedingt: rules.filter(r => r.parentRule
        && /^\(hover: ?hover\) and \(pointer: ?fine\)$/.test(r.parentRule.conditionText || '')).length}; }"""

    def open_menu(pg, url):
        pg.goto(url)
        pg.click("#bug-link")
        pg.click("#bug-pick-btn")
        return pg.evaluate(MENU)

    # Handy-Profil mit echter Pixeldichte: Playwright setzt sonst DPR 1, echte Geräte haben 2,6–3 (R1 c N1)
    for name, opts, want in [("Desktop (Maus)", {"viewport": {"width": 1280, "height": 800}}, 10),
                             ("Mobil-Emulation (Touch, DPR 1)", {"viewport": {"width": 360, "height": 740},
                                                                 "is_mobile": True, "has_touch": True}, 0),
                             ("Handy-Profil (Touch, DPR 2.625)", {"viewport": {"width": 412, "height": 915}, "device_scale_factor": 2.625,
                                                                  "is_mobile": True, "has_touch": True}, 0)]:
        ctx = sb.new_context(**opts)
        pg = ctx.new_page()
        pg.goto(URL)
        if want:
            c = pg.evaluate(CSSOM)
            check(c["n"] >= 6 and c["bedingt"] == c["n"],
                  f"alle {c['n']} ::-webkit-scrollbar-Regeln nur unter genau (hover:hover) and (pointer:fine) ({c['bedingt']} bedingt)")
        r = pg.evaluate(HELP)
        check(r["open"] and r["tall"], f"{name}: Handbuch offen und scrollbar")
        check(r["mq"] == bool(want), f"{name}: Medienbedingung {'trifft zu' if want else 'greift nicht'}")
        check(r["bar"] == want, f"{name}: Balken im Handbuch {r['bar']} px, erwartet {want}")
        m = open_menu(pg, URL)
        check(m["open"] and m["tall"], f"{name}: Bug-Menü offen und scrollbar")
        check(m["bar"] == want, f"{name}: Balken im Bug-Menü {m['bar']} px, erwartet {want}")
        ctx.close()

    print("Release-Audit v1.5 R1 c N2: Bug-Menü läuft bei 360 px nicht seitlich über (DE/EN)")
    ctx = sb.new_context(viewport={"width": 360, "height": 740}, is_mobile=True, has_touch=True)
    pg = ctx.new_page()
    for url in (URL, URL.replace("lang=de", "lang=en")):
        m = open_menu(pg, url)
        check(m["open"] and m["quer"] <= 0 and m["abgeschnitten"] == 0,
              f"{url[-7:]}: kein seitlicher Überlauf ({m['quer']} px), kein Name abgeschnitten ({m['abgeschnitten']})")
    ctx.close()

    print("Bug-Dialog bei 360×640 (z. B. Galaxy A5): Titel und Senden-Knopf per Scrollen erreichbar (DE/EN)")
    ctx = sb.new_context(viewport={"width": 360, "height": 640}, is_mobile=True, has_touch=True)
    pg = ctx.new_page()
    for url in (URL, URL.replace("lang=de", "lang=en")):
        pg.goto(url)
        pg.wait_for_timeout(500)
        pg.evaluate("openBugReport()")
        r = pg.evaluate("""() => { const o = document.getElementById('bug-overlay');
            o.scrollTop = 0; const t = document.getElementById('bug-title').getBoundingClientRect().top;
            o.scrollTop = o.scrollHeight; const s = document.getElementById('bug-send').getBoundingClientRect().bottom;
            return { t, s, h: innerHeight }; }""")
        check(r["t"] >= 0 and r["s"] <= r["h"], f"{url[-7:]}: Titel oben bei {r['t']:.0f} px, Senden unten bei {r['s']:.0f} von {r['h']} px")
    ctx.close()
    sb.close()

if failures:
    print(f"\n{len(failures)} FEHLER")
    sys.exit(1)
print("\nALLE AUDIT-TESTS BESTANDEN ✓")
