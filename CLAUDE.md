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

- **Methode:** FiFo (First In, First Out) — älteste Lots zuerst verbrauchen
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
  Wort in der BitBox-Notiz (`bitbox.is_gift_note`), Report weist Anschaffungsdaten aus
  (§ 23 Abs. 1 S. 3 EStG). `sent_to_yourself` mit Gebühr → TRANSFER_OUT mit Menge 0, nur Fee.
- **Sonstige Kryptowährungen (ETH etc.):** werden ignoriert — nur BTC relevant

---

## Datenquellen (Parser)

Spalten, Datumsformate, Encoding und relevante Transaktionstypen je Quelle: **`docs/DATENFORMATE.md`** — vor jeder
Parser-Arbeit lesen (dort auch das Beispiel des Text-Reports). Quellen: BitBox (`bitbox/*.csv`, `bitbox/nokyc/`), 21bitcoin,
Bison, Swissquote (Windows-1252, USD/CHF), Bisq (noKYC), Strike, Pocket (CHF/USD), `manual_buys.csv`, `manual_sales.csv`.
Neuer Parser = `src/parsers/` + Erkennung in der GUI (Broker-Sniffing, `BLOCKING_TYPES`) + Beispieldaten in `examples/` + Golden-Test.

## noKYC-Logik (Bisq + manual_buys + bitbox/nokyc/)

`Transaction.no_kyc` und `Lot.no_kyc` seit 2026-06-02 im Modell.
- `manual_buys.csv` hat optionale Spalte `kyc` (seit 2026-06-06): `ja`/`1`/`true` →
  KYC-Kauf (Broker ohne eigenen Parser, z.B. Coinbase) → KYC-Pool + Finanzamt-Report.
  Leer/fehlend → noKYC (Standard, abwärtskompatibel).
- **Zwei strikt getrennte FiFo-Pools** (seit 2026-06-05): KYC-Verkäufe konsumieren
  nur KYC-Lots, noKYC-Verkäufe (manual_sales mit `no_kyc=ja`) nur noKYC-Lots.
  Dadurch kann ein noKYC-Lot nie in der FiFo-Zuordnung eines Finanzamt-Dokuments erscheinen.
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
`--all --nachweis --csv`, byte-genau bis auf „Erstellt am") + FX-Regeln + „kein Netzcode in src/".
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
- Bug-Report ohne Dateinamen und ohne URL. Support nur Technik/Format, nie Steuerfragen.
- Tests: `python3 -m http.server 8741 --directory web/dist` + `python3 web/test_gui.py`
  (Referenz: CLI `--all --nachweis --csv --data-dir` auf eine examples-Kopie unter
  `/tmp/poc-ref/examples`, Reports müssen byte-gleich sein) + `python3 web/test_lang.py`.
  Playwright-Chromium: `python3 -m playwright install chromium`.

---

## Desktop-App (`desktop/`, Flatpak `org.alieninvestor.steuertool`) — seit 02.10.2026

Electron-Hülle nach Alien-Pass-Muster, lädt `web/dist` unverändert über `app://steuertool`. Kein Netz, kein Dateisystem,
Brücke nur `saveFile`, Weiche `DESK` in `web/index.html`. **Vor jeder Änderung `desktop/DESKTOP-INVARIANTEN.md` lesen.**
- Bauen: `desktop/build-desktop.sh` (Electron-Hash, Fuses, Rechte-Endkontrolle vor + nach Installation, Bundle + `SHA256SUMS`).
- Testen: `node desktop/verify-desktop.mjs` (echte Hülle, Reports byte-gleich zur CLI) — braucht einmal den Build (Electron-Cache).
- Version: `VERSION` (`VERSION_NAME`, `DESKTOP_REV` nur für reinen Electron-Neubau). Kurstabellen-Update im Januar = neues Release.
- Handbuch („?“) liegt offline in `web/index.html` (`help-de`/`help-en`) — eine Quelle für Web, Desktop und APK. Inhaltliche
  Änderungen dort brauchen einen Faktencheck (öffentlich).

## Android-App (`mobile/`, Capacitor 6.2.2, `org.alieninvestor.steuertool`) — seit 02.10.2026

Capacitor-Hülle nach Alien-Pass-Muster, enthält `web/dist` unverändert. Keine Berechtigung (auch kein INTERNET), FLAG_SECURE, kein Backup,
Brücke nur `SaveFile` (Android-Speichern-Dialog), Weiche `DROID` in `web/index.html`. **Vor jeder Änderung `mobile/MOBILE-INVARIANTEN.md` lesen.**
- Bauen: `mobile/build-apk.sh` (Capacitor-Pin, Härtung, Signatur, Endkontrolle an der fertigen APK). `mobile/android/` ist generiert.
- Link-Liste und CSP liest die APK aus `desktop/main.js` — eine Quelle für beide Hüllen.
- Gemeinsamer App-Kopf (Flatpak + APK, `html.app`): Sprache links, „?“ rechts wie die anderen Alien-Apps, Darstellung im Fuß.
- `VERSION_CODE` in `VERSION` je Release hochzählen.

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
├── bitbox/, Broker/           # Original-CSVs (unveränderlich, in .gitignore)
├── examples/                  # Fiktive Testdaten (Golden-Test, Beispieldaten der GUI)
├── src/
│   ├── models.py              # Transaction Dataclass + Enums
│   ├── parsers/               # bitbox, broker_21bitcoin/_bison/_swissquote/_strike/_pocket, bisq, manual_buys/_sales
│   ├── fx_rates.py            # EZB-Wechselkurse aus src/data/ (offline)
│   ├── btc_prices.py          # BTC-Tagesschlusskurse aus src/data/ (Gebühren in BTC)
│   ├── fifo_engine.py         # FiFo Lot-Verwaltung + Gewinnberechnung
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
```

---

## FiFo-Engine (`fifo_engine.py`)

### Lot-Struktur
```python
@dataclass
class Lot:
    purchase_date: datetime
    btc_amount: Decimal       # verbleibende BTC in diesem Lot
    cost_per_btc: Decimal     # (eur_amount + fee_eur) / btc_amount
    source: str
```

### Regeln
1. Jeder `BUY` erzeugt ein neues Lot: `cost_per_btc = (eur_amount + fee_eur) / btc_amount`
2. **Zwei getrennte Pools**: KYC-Lots und noKYC-Lots (je eine Deque, älteste zuerst).
   `tx.no_kyc` entscheidet, in welchen Pool ein Kauf geht und aus welchem ein Verkauf konsumiert.
3. Bei `SELL`: Lots des passenden Pools von vorne aufbrauchen bis BTC-Menge erreicht
4. Für jedes verbrauchte Lot berechnen:
   - `holding_days = (sell_date - lot.purchase_date).days` (nur Anzeige)
   - **Steuerfreiheit per Kalenderdatum** (§§ 187/188 BGB): steuerfrei wenn
     `sale.date() > purchase.date() + 1 Jahr` (Jahrestag; 29.02. → 28.02.).
     Korrekt auch in Schaltjahren — nicht einfach `> 365 Tage`.
   - `gain = (net_sell_price_per_btc - lot.cost_per_btc) * used_btc_amount`
   - `net_sell_price_per_btc = (eur_amount - fee_eur) / total_btc_sold`
5. `TRANSFER_OUT` / `TRANSFER_IN`: keine Lot-Änderung für den übertragenen Bestand (Kostenbasis bleibt)
6. `fee_btc > 0` (jeder Typ): Gebühren-Abgang über `_consume(kind=FEE)` zum Tagesschlusskurs
   (`btc_prices.price_for_date(de_date)`), Ergebnis in `engine.fee_results` — Gewinne zählen
   in Jahressumme + Freigrenze; ohne Kurs `is_priced=False`, Gewinn 0 + Warnung
7. `GIFT_OUT`: `_consume(kind=GIFT)`, Gewinn je Match 0, Ergebnis in `engine.gift_results`

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
