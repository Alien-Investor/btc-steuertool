# BTC Steuertool — Projektbeschreibung

## Projektziel
CLI-Tool das aus CSV-Exporten von BitBox-Hardware-Wallets und Broker-Konten steuerlich
relevante Jahresberichte für das deutsche Finanzamt erstellt. Dieselbe Engine läuft
unverändert als freie Web-Version (`web/`, Pyodide im Browser) — siehe Abschnitt
„Web-Version“.

Alle BTC werden in Selbstverwahrung gehalten (BitBox). Käufe laufen über einen oder
mehrere Broker. Die BitBox-CSVs dokumentieren die Überträge zwischen Wallets und Börsen.

---

## Steuerrechtliche Grundlagen (Deutschland, Privatanleger)

- **Methode:** FiFo (First In, First Out), **walletbezogen** (BMF 06.03.2025 Rn. 61 f.): jede Wallet
  bzw. jedes Börsenkonto ist ein eigener Bestand; bei Überträgen zwischen eigenen Wallets wandern
  Anschaffungsdatum und -kosten mit (Abschnitt „Walletbezogenes FiFo“)
- **Haltefrist:** Gewinne aus BTC-Veräußerungen sind **steuerfrei**, wenn zwischen Anschaffung
  und Veräußerung mehr als ein Jahr liegt (§ 23 Abs. 1 S. 1 Nr. 2 EStG, §§ 187 Abs. 1, 188 Abs. 2 BGB)
- **Freigrenze private Veräußerungsgeschäfte:**
  - bis einschließlich 2023: **600 EUR** pro Jahr
  - ab 2024: **1.000 EUR** pro Jahr
  - Bei Überschreitung: der **gesamte** steuerpflichtige Gewinn ist zu versteuern
- **Anschaffungskosten eines Lots:** `(eur_kaufpreis + kaufgebühren_eur) / btc_menge`
- **Veräußerungserlös:** `eur_verkaufspreis - verkaufsgebühren_eur`
- **Überträge zwischen eigenen Wallets/Konten:** der übertragene Bestand ist kein steuerpflichtiger Vorgang
- **In BTC entrichtete Gebühren (On-Chain-Fee, Auszahlungsgebühr, Bisq-Handelsgebühr):**
  Veräußerung des Gebührenanteils zum Tagesschlusskurs (BMF 06.03.2025 Rn. 33/54/60/91),
  FiFo-Lot wird verbraucht, Gewinn zählt in die Freigrenze (H8, 15.08.2026). Kurs aus
  `src/data/btc_eur_daily.csv` (Bitstamp, offline; `tools/update_btc_prices.py`).
  Ohne Kurs: Abgang gebucht, Gewinn „nicht ermittelt" + Warnung — nie stillschweigend.
- **Schenkung/Spende (`GIFT_OUT`):** keine Veräußerung, aber Bestandsabgang; Erkennung am
  Wort in der BitBox-Notiz (`bitbox.is_gift_note`, ohne Gutschein/Gift Card/Verneinung — `_NOT_GIFT`), Report weist Anschaffungsdaten aus
  (§ 23 Abs. 1 S. 3 EStG). `sent_to_yourself` mit Gebühr → TRANSFER_OUT mit Menge 0, nur Fee.
- **Sonstige Kryptowährungen (ETH etc.):** werden ignoriert — nur BTC relevant

---

## Datenquellen (Parser)

Spalten, Datumsformate, Encoding und relevante Transaktionstypen je Quelle: **`docs/DATENFORMATE.md`** — vor jeder
Parser-Arbeit lesen (dort auch das Beispiel des Text-Reports). Quellen: BitBox (`bitbox/*.csv`, `bitbox/nokyc/`), 21bitcoin,
Bison, Swissquote (Windows-1252, USD/CHF), Bisq (noKYC, Export DE oder EN), Strike, Pocket (CHF/USD), Sammelimport
CoinTracking/Blockpit (`sammelimport.py`, Konto = Wallet, Format unbestätigt → Warnung im Report), Wallet-Software Sparrow/Electrum/
Trezor Suite/Ledger Wallet (`wallets/`, `wallets/nokyc/`, `wallet_export.py` erkennt das Programm an der Kopfzeile, Format aus dem Quellcode
unbestätigt → Warnung; Quelle `<art>:<Dateiname>`, Ledger je Konto), `manual_buys.csv`, `manual_sales.csv`.
Neuer Parser = `src/parsers/` + Erkennung in der GUI (Broker-Sniffing, `BLOCKING_TYPES`) + Beispieldaten in `examples/` + Golden-Test.
Jeder Parser liest über `parsers.read_rows(..., required=...)`, Zahlen über `parsers.amount`/`parse_amount`, ISO-Zeiten über
`parse_iso_datetime` (Audit 03.10.2026: `row.get(...)` ohne Pflichtspaltenprüfung verlor ganze Dateien still). Harte Fehler nennen
Datei und Zeile; `main._parse_file` setzt den Dateibezug nach.

## noKYC-Logik (Bisq + manual_buys + bitbox/nokyc/)

`Transaction.no_kyc` und `Lot.no_kyc` seit 2026-06-02 im Modell.
- `manual_buys.csv` hat optionale Spalte `kyc` (seit 2026-06-06): `ja`/`1`/`true` →
  KYC-Kauf (Broker ohne eigenen Parser, z.B. Coinbase) → KYC-Pool + Finanzamt-Report.
  Leer/fehlend → noKYC (Standard, abwärtskompatibel).
- **KYC und noKYC strikt getrennt:** Töpfe je (Klasse, Wallet); KYC-Vorgänge sehen nie noKYC-Lots,
  Überträge zwischen den Klassen werden nie verbunden. Kommt ein noKYC-Kauf/-Abgang in einer
  KYC-Wallet an → harter Abbruch (stünde sonst mit Datum/Betrag im Nachweis).
- `TaxReport` filtert `no_kyc=True` aus offiziellen Käufen, Verkäufen und Lots heraus
- Separate Datei `nokyc_intern_YYYY.txt` zeigt noKYC-Käufe, -Verkäufe (mit FiFo-Zuordnung
  und Haltefrist), Wallet-Aktivität (`bitbox/nokyc/`) und verbleibende Bestände
- Neue noKYC-Quellen: einfach `no_kyc=True` im Parser setzen — Rest automatisch


## Historische Wechselkurse (Swissquote/Pocket USD/CHF) — offline seit 02.10.2026

- **Kein Netzcode im Tool.** Quelle: `src/data/ecb_eur_daily.csv` (EZB-Referenzkurse USD/CHF
  je 1 EUR, wie veröffentlicht, seit 2010). Aktualisieren nur durch den Autor:
  `python tools/update_fx_rates.py` (hängt an, ändert nie vorhandene Zeilen).
- Wochenende/Feiertag → letzter veröffentlichter Kurs davor. Datum nach Tabellenende →
  `RuntimeError` mit Erklärung, nie stiller Altkurs.
- Umrechnung `1/Referenzkurs`, 5 signifikante Stellen, `normalize()` — exakt die Werte der
  früheren frankfurter-API (Stichproben + `tests/test_golden.py`), alte Reports bleiben byte-gleich.
- `fx_cache.json` im Datenverzeichnis ist nur noch manueller Override (wird nie geschrieben).
- Wurde ein Tabellenkurs benutzt, nennt der Steuernachweis unter „Datenquellen" EZB + Datenstand.
- `requests` und `pandas` sind keine Abhängigkeiten mehr (pandas wurde nie importiert);
  das Tool läuft mit der Standardbibliothek. `requests` brauchen nur die `tools/`-Skripte.

## Tests

`python -m unittest discover tests` — Golden-Snapshot (`tests/golden/`, examples mit
`--all --nachweis --csv`, byte-genau bis auf „Erstellt am") + FX-Regeln + „kein Netzcode in src/"
+ `tests/test_audit_run1.py` (offizielle Dokumente ohne „noKYC"/„P2P", Schenkungs-Erkennung, Warnjahr, fx_cache-Prüfung)
+ `tests/test_wallet_exporte.py` (Sparrow/Electrum/Trezor/Ledger, Fixtures `tests/fixtures/`)
+ `tests/test_wallet_fifo.py` (Zuordnung, Engine, Reports-Datenschutz, Audit-Regressionen, **Mengenbilanz** auf
examples + 300 Zufallsabläufen: gekauft = Bestand + verbraucht je Klasse).
Gewollte Report-Änderung: `python tests/test_golden.py --update`, Diff im Commit begründen.

---

## Web-Version (`web/`) — seit 02.10.2026 frei, kein Fork der Engine

`web/index.html` (GUI, Broker-Sniffing, ZIP-Entpacker, DE/EN-i18n) + `web/worker.js`
(Pyodide 0.26.4 im Web-Worker, lädt `src/` 1:1 ins WASM-Dateisystem). `web/build.sh` baut
`web/dist/` (kopiert `../src`, `../examples`, `vendor/`, erzeugt `beispieldaten.zip`).
`web/vendor-setup.sh` holt Pyodide + tzdata-Wheel + Fonts mit SHA-256-Prüfung (nicht
versioniert, ~15 MB). Reports bleiben deutsch (Finanzamt-Dokumente), die UI ist zweisprachig.

Regeln:
- **Engine nie in JS nachbauen** — `src/` ist die einzige Implementierung; die GUI bekommt
  `internal_reports`, `report_years()` usw. aus dem Python-Bootstrap, sie leitet nichts neu her.
- CSVs als Bytes ins Pyodide-FS schreiben (Swissquote = Windows-1252). `tzdata` muss geladen
  bleiben (Steuernachweis nutzt Europe/Berlin). `import zoneinfo` im Worker-Init vorziehen.
- Pyodide erst bei Nutzungsabsicht laden (Mobile), Desktop darf eager vorwärmen. Nie den
  WASM-Compile an einen Tap hängen, auf den der Nutzer wartet (Datei-Picker).
- Kein `accept`-Attribut am File-Input (GrapheneOS-Picker grayt sonst CSVs aus).
- Nicht erkannte Dateien sperren die Berechnung; `BLOCKING_TYPES` ist die einzige Liste.
- Bug-Report ohne Dateinamen und ohne URL. Support nur Technik/Format, nie Steuerfragen. Die optionale Diagnose schwärzt
  ausschließlich `src/diagnose.py` (Python, eine Stelle; GUI liefert nur Rohangaben, noKYC-fähige Typen nur gezählt;
  erste Zeile unbekannter Dateien nur als Struktur über eine Positivliste von Spaltenwörtern; Meldungen nur mit Wörtern
  aus den eigenen Meldungsvorlagen (Texte in raise/warn* und Variablen template/hint/…_TEXT in src/, nie Docstrings),
  Zitate ganz geschwärzt, „Gelesen:“ nur als Struktur, Namen aus `parsers.seen_names` auch bei Abbruch; Abbrüche als
  `parsers.PrivateError` → nur ein allgemeiner Satz; der Bootstrap gibt Fehler als Daten zurück, nicht als Exception);
  Leck-Tests `tests/test_diagnose.py` + `web/test_audit.py`. „Log speichern“ = volles Log, nur intern.
- Tests: `python3 -m http.server 8741 --directory web/dist` + `python3 web/test_gui.py`
  (Referenz: CLI `--all --nachweis --csv --data-dir` auf eine examples-Kopie unter
  `/tmp/poc-ref/examples`, Reports müssen byte-gleich sein) + `python3 web/test_lang.py` + `python3 web/test_audit.py`.
  Playwright-Chromium: `python3 -m playwright install chromium`.

---

## Desktop-App (`desktop/`, Flatpak `org.alieninvestor.steuertool`) — seit 02.10.2026

Electron-Hülle nach Alien-Pass-Muster, lädt `web/dist` unverändert über `app://steuertool`. Kein Netz, kein Dateisystem,
Brücke nur `saveFile`, Weiche `DESK` in `web/index.html`. **Vor jeder Änderung `desktop/DESKTOP-INVARIANTEN.md` lesen.**
- Bauen: `desktop/build-desktop.sh` (Electron-Hash, Fuses, Rechte-Endkontrolle vor + nach Installation, Bundle + `SHA256SUMS`).
- Testen: `node desktop/verify-desktop.mjs` (echte Hülle, Reports byte-gleich zur CLI) — braucht einmal den Build (Electron-Cache).
- Version: `VERSION` (`VERSION_NAME`, `DESKTOP_REV` nur für reinen Electron-Neubau). Kurstabellen-Update im Januar = neues Release.
  `web/build.sh` schreibt `VERSION_NAME` und das Datum des letzten Commits in `dist/index.html` (Platzhalter `__APP_VERSION__`/`__WEB_STAND__`,
  Anzeige im Fuß: Apps „v1.4“, Web „Web · Stand …“) — nie von Hand in index.html eintragen.
- Handbuch („?“) liegt offline in `web/index.html` (`help-de`/`help-en`) — eine Quelle für Web, Desktop und APK. Inhaltliche
  Änderungen dort brauchen einen Faktencheck (öffentlich).
- **Beim nächsten Release mitnehmen (Querfund Alien Pass v1.18, 03.10.2026, kein eigenes Release):** `openOutside` in `desktop/main.js` bremst mit
  `Date.now()` — wird die Systemuhr zurückgestellt (NTP, Resume mit falscher RTC), bleibt der Spenden-Knopf still tot, bis die Uhr den alten Stand erreicht.
  Fix wie Alien Pass `desktop/main.js`: `let lastOut=-Infinity;` und `const t=performance.now();`. Optional der Harness-Direktaufruf der Handler
  (`app.emit('web-contents-created',{},fake)`, Vorlage Alien Pass `desktop/test/harness.cjs`): Chromium kanonisiert URLs vor den Handlern, ein Rohstring an
  `shell.openExternal` fiele sonst nie auf. Die PRIMARY-Funde aus Pass betreffen das Steuertool nicht (keine Überwachung der X11-Auswahl).
  **Nachtrag Alien Notes v1.7 (03.10.2026):** Den Uhr-Fix mit Test absichern — Harness patcht `Date.now` (1 h zurück) und ruft den Handler direkt auf, muss dann
  öffnen (Vorlage Notes `desktop/test/harness.cjs` „Bremse übersteht eine zurückgestellte Uhr“; gegen den alten Code rot). Ebenfalls aus Notes: `verify-desktop` verlangt je
  Schritt eine Endmarke „Schritt vollständig“ (ein stilles vorzeitiges Ende bliebe sonst grün). Die X11-Funde aus Notes run-5 betreffen das Steuertool nicht.

## Android-App (`mobile/`, Capacitor 6.2.2, `org.alieninvestor.steuertool`) — seit 02.10.2026

Capacitor-Hülle nach Alien-Pass-Muster, enthält `web/dist` unverändert. Keine Berechtigung (auch kein INTERNET), FLAG_SECURE, kein Backup,
Brücke nur `SaveFile` (Android-Speichern-Dialog), Weiche `DROID` in `web/index.html`. **Vor jeder Änderung `mobile/MOBILE-INVARIANTEN.md` lesen.**
- Bauen: `mobile/build-apk.sh` (Capacitor-Pin, Härtung, Signatur, Endkontrolle an der fertigen APK). `mobile/android/` ist generiert.
- Link-Liste und CSP liest die APK aus `desktop/main.js` — eine Quelle für beide Hüllen.
- Gemeinsamer App-Kopf (Flatpak + APK, `html.app`): Sprache links, „?“ rechts wie die anderen Alien-Apps, Darstellung im Fuß.
- `VERSION_CODE` in `VERSION` je Release hochzählen.

## Release (Flatpak + APK gemeinsam, seit v1.0 am 02.10.2026)

Skill `app-release` (Abschnitt „Besonderheiten BTC Steuertool“). Kurz: Tests + Gerätetest mit großem Datensatz → `CHANGELOG.md` →
Commit/Push → `desktop/build-desktop.sh`, `mobile/build-apk.sh` → Nutzer signiert `SHA256SUMS` → Tag pushen → `./make-release.sh`
(GitHub-Release + `api.alien-investor.org/downloads/steuertool/`, Download-Seite mit genau einem APK-Link) → Nutzer: `publish-zapstore.sh`
→ Website (`btc-steuertool.html` DE/EN, `apps.html`) mit Faktencheck. Store-Screenshots: `mobile/shot-store.py`.
**Web-Version immer mit ausrollen** (Web, Flatpak und APK zeigen denselben Stand): `web/build.sh`, dann
`rsync -a --chmod=D755,F644 web/dist/ root@api.alien-investor.org:/var/www/alien-investor/html/steuertool/` (vorher `-an --itemize-changes`),
danach `cmp` der Live-Dateien gegen `web/dist`. Auch nach reinen Engine- oder GUI-Fixes ohne App-Release.

## Technologie-Stack

- **Python 3.10+**
- Nur Standardbibliothek (`csv` fürs Parsing)
- `decimal.Decimal` — **alle** Finanzberechnungen (NIEMALS `float` für Geldbeträge!)
- Keine Datenbank, kein Web-Framework

---

## Architektur

```
btc-steuertool-public/
├── CLAUDE.md, README.md, ANLEITUNG.md, VERSION   # VERSION: App-Version für Flatpak + APK
├── docs/DATENFORMATE.md       # Formate aller Quellen + Report-Beispiel
├── bitbox/, wallets/, Broker/ # Original-CSVs (unveränderlich, in .gitignore)
├── examples/                  # Fiktive Testdaten (Golden-Test, Beispieldaten der GUI)
├── src/
│   ├── models.py              # Transaction Dataclass + Enums
│   ├── parsers/               # bitbox, wallet_export (+ _sparrow/_electrum/_trezor/_ledger), broker_21bitcoin/_bison/_swissquote/_strike/_pocket, bisq, sammelimport, manual_buys/_sales, transfer_zuordnung
│   ├── fx_rates.py            # EZB-Wechselkurse aus src/data/ (offline)
│   ├── btc_prices.py          # BTC-Tagesschlusskurse aus src/data/ (Gebühren in BTC)
│   ├── transfer_matching.py   # Zuordnung Abgang ↔ Eingang (walletbezogenes FiFo)
│   ├── fifo_engine.py         # FiFo je Wallet, Umbuchungen, Gewinnberechnung, Jahresend-Snapshots
│   ├── wallet_report.py       # Umbuchungen, Bestand je Wallet, neutrale Labels, wallet_abgleich_intern
│   ├── tax_report.py          # Report-Generierung (Text + CSV)
│   ├── formal_report.py       # Formaler Steuernachweis (--nachweis)
│   └── main.py                # CLI-Einstieg
├── tools/                     # update_fx_rates.py, update_btc_prices.py (nur Autor, Netz)
├── tests/                     # test_golden.py + golden/
├── web/                       # GUI (index.html, worker.js), build.sh → web/dist
├── desktop/                   # Flatpak-Hülle (Electron)
├── mobile/                    # Android-Hülle (Capacitor)
├── fx_cache.json              # Optional: manuelle Wechselkurse (Override)
└── reports/                   # Generierte Berichte (wird automatisch angelegt)
```


## Einheitliches Transaktionsmodell (`models.py`)

```python
from enum import Enum
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime

class TxType(Enum):
    BUY            = "buy"           # BTC-Kauf bei Broker
    SELL           = "sell"          # BTC-Verkauf bei Broker
    TRANSFER_OUT   = "transfer_out"  # Übertrag von Broker/Wallet zu eigener Wallet
    TRANSFER_IN    = "transfer_in"   # Empfang von Broker/Wallet auf eigener Wallet
    GIFT_OUT       = "gift_out"      # unentgeltliche Übertragung (Schenkung/Spende)

@dataclass
class Transaction:
    date: datetime            # timezone-aware, intern immer UTC
    type: TxType
    btc_amount: Decimal       # immer positiv, in BTC (nicht Satoshi)
    eur_amount: Decimal       # Kaufpreis oder Verkaufserlös (vor Gebühren), 0 bei Transfer
    eur_price_per_btc: Decimal  # 0 bei Transfer
    fee_eur: Decimal          # Gebühren in EUR (0 wenn nicht bekannt)
    fee_btc: Decimal          # in BTC entrichtete Gebühr — verlässt den Bestand zusätzlich (H8)
    source: str               # z.B. "21bitcoin", "bison", "bitbox:wallet1"
    tx_id: str                # On-Chain TX-ID oder Broker-interne ID
    note: str
    no_kyc: bool              # noKYC-Bestand (nur interne Dateien)
    wallet: str               # FiFo-Topf; leer → source. ANY_WALLET "*" = manual_sales ohne Wallet
    direct: bool              # Anbieter ohne Bestand (Pocket, Bisq, manual): liefert an / verkauft aus eigener Wallet
```

---

## FiFo-Engine (`fifo_engine.py`)

`run_engine(transactions)` in `main.py` ist der einzige Start (CLI und GUI-Bootstrap). Sie hängt einen
Vergleichslauf `mode="global"` an (alte Rechnung, nur für `wallet_abgleich_intern_JJJJ.txt`).

1. Jeder `BUY` erzeugt ein Lot in seiner Wallet: `cost_per_btc = (eur_amount + fee_eur) / btc_amount`.
2. Veräußerung (`SELL`, Gebühr, `GIFT_OUT`) verbraucht die ältesten Lots **der eigenen Wallet**.
3. Steuerfreiheit per Kalenderdatum Europe/Berlin (§§ 187/188 BGB, Jahrestag; 29.02. → 28.02.),
   nicht `> 365 Tage`. `gain = (net_sell_price_per_btc − cost_per_btc) × Menge`.
4. `fee_btc > 0`: Veräußerung des Gebührenanteils zum Tagesschlusskurs (`engine.fee_results`, zählt in
   Freigrenze), aus der sendenden Wallet; beim Kauf (Bisq) aus dem eigenen Lot. Ohne Kurs Warnung.
5. `GIFT_OUT`: Bestandsabgang, Gewinn 0 (`engine.gift_results`).

## Walletbezogenes FiFo (seit 10/2026) — Regeln

- **Zuordnung** (`transfer_matching`): Stufe 0 `transfer_zuordnung.csv`, 1 gleiche TX-ID, 1b Kauf mit
  Spalte `wallet`, 2 Betrag (mit/ohne Gebühr) im Fenster ±48 h beidseitig (Lieferung bis 30 Tage).
  Mehrdeutig über verschiedene Wallets → nicht verbinden, Warnung. Verbindungen: TRANSFER, LIEFERUNG
  (Direktkauf → Eingang, es wandert **das Lot dieses Kaufs**, zeitlich nächster Kauf), VERKAUF
  (Abgang → Direktverkauf, verhindert Doppelverbrauch).
- **Umbuchung zweiphasig:** Lots verlassen die Quelle beim Abgang, kommen beim Eingang an, werden nach
  **Anschaffungsdatum** einsortiert. Unterwegs zählen sie zum 31.12. zur Ziel-Wallet.
- **Ohne Gegenstück:** Abgang → Wallet „extern“ (Warnung, keine Veräußerung). Eingang → holt FiFo aus
  „extern“, Rest ohne Anschaffungsdaten (keine erfundenen Lots). Verkauf ohne Wallet und ohne Abgang →
  nur aus Beständen ohne bekannten Verwahrort (extern, nicht gelieferte Direktkäufe).
- **Datumslose manual-Zeilen** (12:00 UTC): verbundener Verkauf frühestens beim Abgang, Kauf zur früheren
  Lieferung — nur innerhalb des Kalendertags.
- **Datenschutz:** offizielle Dokumente nennen Wallets in Selbstverwahrung nur nach Art, „BitBox-Wallet (n)“, „Sparrow-Wallet (n)“
  (`models.WALLET_KINDS`/`own_wallet`, nur KYC gezählt; neue Wallet-Software dort eintragen, nie `startswith("bitbox:")` prüfen),
  Echtnamen nur in `wallet_abgleich_intern`. Fehlermeldungen nennen nur Wallets derselben Klasse.
- **KYC/noKYC-Sperre (Release-Audit v1.4, zwei Runden):** gleiche TX-ID zwischen JEDEM noKYC-Abgang (auch GIFT_OUT, nur Gebühr,
  teilweise verbunden) und einem KYC-Eingang bricht ab; ohne TX-ID auch ein bis 1 % kleinerer Eingang bei unbekannter Gebühr.
  Eine Quelle (außer `manual`) in beiden Klassen bricht ab. Dedup je Quelle und Klasse. Offizielle Dokumente nur für
  `report_years(official=True)` — ein Jahr allein mit noKYC-Vorgängen verriete sich sonst durch einen leeren Report.
- **GUI-Fehler:** im `catch` von `runCalc` den Vergleich `inputVersion !== myVersion` VOR `invalidateResults()` (das zählt hoch);
  sonst erreicht kein Abbruch den Nutzer (R2-H1, bestand in v1.2–v1.3). Der Worker kürzt Python-Tracebacks auf die Meldung.
- **`mode="global"` muss die alte Rechnung exakt reproduzieren** — Änderungen an der walletbezogenen
  Logik nie in den globalen Zweig tragen (Audit-Fund: Bisq-Gebühr-Fix wirkte sonst auch dort).
- **Git:** `git add` und `git commit` immer getrennt ausführen (kombiniert sieht der OpSec-Hook ein
  leeres Staging). Seit 03.10.2026 lässt der Hook „wallet“ in Code-/Doku-Dateinamen und unter `tests/golden/`,
  `examples/` durch (`wallet_report.py`, `test_wallet_fifo.py`, `wallet_abgleich_intern_*`, `nokyc_wallet.csv`);
  gesperrt bleiben Datendateien mit „wallet“ (`bitbox/*.csv`, `*.json`) sowie Seed/Secret/Keys.

---

## CLI-Interface (`main.py`)

```bash
python src/main.py --year 2024          # Report für Steuerjahr 2024
python src/main.py --year 2024 --csv    # Zusätzlich CSV-Export nach reports/
python src/main.py --all                # Reports für alle Jahre mit Transaktionen
python src/main.py --all --csv          # Alle Jahre + CSV
python src/main.py --year 2024 --nachweis  # Formaler Steuernachweis
python src/main.py --data-dir /pfad/    # Anderes Datenverzeichnis
```

---

## Wichtige Implementierungshinweise

- Alle Datumsangaben intern als **timezone-aware datetime in UTC** speichern
- BitBox-Timestamps haben Timezone-Offset (`+01:00`, `+02:00`) → korrekt parsen
- Bison-Timestamps sind UTC → als UTC markieren
- Satoshi-Beträge **sofort** beim Parsen in BTC umrechnen: `Decimal(satoshi) / Decimal(100_000_000)`
- Bei Swissquote: mehrere Kauf-Zeilen mit gleicher `Auftrag #` → zu **einer** Transaktion zusammenfassen
- Bison-CSV: Leerzeichen nach Semikolon beim Parsen trimmen
- Original-CSV-Dateien **niemals** verändern
