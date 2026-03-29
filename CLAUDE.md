# BTC Steuertool — Projektbeschreibung

## Projektziel
CLI-Tool das aus CSV-Exporten von BitBox-Hardware-Wallets und Broker-Konten steuerlich
relevante Jahresberichte für das deutsche Finanzamt erstellt.

Alle BTC werden in Selbstverwahrung gehalten (BitBox). Käufe laufen über einen oder
mehrere Broker. Die BitBox-CSVs dokumentieren die Überträge zwischen Wallets und Börsen.

---

## Steuerrechtliche Grundlagen (Deutschland, Privatanleger)

- **Methode:** FiFo (First In, First Out) — älteste Lots zuerst verbrauchen
- **Haltefrist:** Gewinne aus BTC-Veräußerungen nach > 365 Tagen Haltedauer sind **steuerfrei**
- **Freigrenze private Veräußerungsgeschäfte:**
  - bis einschließlich 2023: **600 EUR** pro Jahr
  - ab 2024: **1.000 EUR** pro Jahr
  - Bei Überschreitung: der **gesamte** steuerpflichtige Gewinn ist zu versteuern
- **Anschaffungskosten eines Lots:** `(eur_kaufpreis + kaufgebühren_eur) / btc_menge`
- **Veräußerungserlös:** `eur_verkaufspreis - verkaufsgebühren_eur`
- **Überträge zwischen eigenen Wallets/Konten:** kein steuerpflichtiger Vorgang
- **On-Chain-Fees bei Überträgen zwischen eigenen Wallets:** steuerlich neutral
- **Sonstige Kryptowährungen (ETH etc.):** werden ignoriert — nur BTC relevant

---

## Datensources

### BitBox-Wallets (`bitbox/`)
Eine oder mehrere eigene Wallets, alle im gleichen Format (CSV, Komma-getrennt, UTF-8):

```
Time,Type,Amount,Unit,Fee,Fee Unit,Address,Transaction ID,Note
```

- `Amount` und `Fee` in **Satoshi** (1 BTC = 100.000.000 Satoshi) → immer in BTC umrechnen
- `Type`: `sent` oder `received`
- `Time`: ISO 8601 mit Timezone-Offset, z.B. `2025-10-10T13:10:52+02:00`
- `Note`-Feld ist beschreibend (z.B. "Übertrag an Wallet 2", "Verkauf an Börse Bison")
- Dateien: beliebige Namen möglich, z.B. `wallet1.csv`, `wallet2.csv` — alle `*.csv` im `bitbox/`-Ordner werden eingelesen

### Broker: 21bitcoin (`Broker/21bitcoin*.csv`)
CSV, Komma-getrennt, UTF-8:

```
id,exchange_name,depot_name,transaction_date,buy_asset,buy_amount,sell_asset,sell_amount,
fee_asset,fee_amount,transaction_type,note,linked_transaction
```

- `transaction_date`: Format `DD.MM.YYYY HH:MM:SS`
- Relevante `transaction_type`-Werte:
  - `trade` mit `buy_asset=BTC`: BTC-Kauf — `buy_amount` = BTC, `sell_amount` = EUR, `fee_amount` = EUR
  - `withdrawal` mit `sell_asset=BTC`: BTC-Auszahlung an eigene Wallet — `sell_amount` = BTC inkl. Netzwerkgebühr
  - `deposit`: EUR-Einzahlung — irrelevant für Steuer
- EUR-Kaufpreis ist direkt vorhanden (`sell_amount` = EUR bezahlt, `buy_amount` = BTC erhalten)

### Broker: Bison (`Broker/Bison-CSV-Gesamt.csv`)
CSV, Semikolon-getrennt (mit Leerzeichen nach Semikolon), UTF-8:

```
Transaction ID; Transaction type; Currency; Asset; Eur (amount); Asset (amount); Asset (market price); Fee; Date (UTC)
```

- `Date`: Format `YYYY-MM-DD HH:MM:SS` (UTC!)
- Relevante Zeilen (nur BTC, ETH ignorieren):
  - `Buy` + `Asset=Btc`: BTC-Kauf — `Eur (amount)` = EUR bezahlt, `Asset (amount)` = BTC erhalten, `Asset (market price)` = EUR/BTC
  - `Sell` + `Asset=Btc`: BTC-Verkauf — `Eur (amount)` = EUR erhalten, `Asset (amount)` = BTC verkauft
  - `Deposit` + `Asset=Btc` (Currency leer): BTC-Eingang von eigener Wallet für Verkauf — Transfer, kein steuerpfl. Vorgang
  - `Withdraw` + `Currency=Eur`: EUR-Auszahlung nach Verkauf — irrelevant
  - `Deposit` + `Currency=Eur`: EUR-Einzahlung — irrelevant
- `Fee` ist immer 0 bei Bison (im Spread enthalten), Preis ist Marktpreis → Gebühr = 0

### Broker: Swissquote (`Broker/Swissquote_CSV-Gesamt.csv`)
CSV, Semikolon-getrennt, **Encoding: Windows-1252** (Umlaute kaputt wenn UTF-8):

```
Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;
Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
```

- `Datum`: Format `DD-MM-YYYY HH:MM:SS`
- Relevante `Transaktionen`-Werte:
  - `Kauf`: BTC-Kauf — `Anzahl` = BTC, `Stückpreis` = Preis/BTC, `Kosten` = Gebühr, `Nettobetrag` = Gesamtbetrag (negativ), `Währung` = EUR oder USD
  - `Crypto Withdrawal`: BTC an eigene Wallet — Transfer, kein steuerpfl. Vorgang
  - `Crypto Deposit`: BTC von eigener Wallet — Transfer, kein steuerpfl. Vorgang
- **Wichtig:** `Währung` kann `USD` oder `CHF` sein → historischen EUR-Kurs abrufen!
- Mehrere Kauf-Zeilen mit gleicher `Auftrag #` gehören zu einer Order (summieren)

### Broker: Strike (`Broker/strike_YYYY.csv`)
CSV, Komma-getrennt, UTF-8 (mehrere Dateien pro Jahr möglich, Pattern: `strike_*.csv`):

```
Transaction ID,Time (UTC),Status,Transaction Type,Amount EUR,Fee EUR,Amount BTC,Fee BTC,Description,Exchange Rate,Transaction Hash
```

- `Time (UTC)`: Format `Mon DD YYYY HH:MM:SS` (UTC)
- Relevante `Transaction Type`-Werte:
  - `Purchase`: BTC-Kauf — `Amount EUR` negativ (abs nehmen), `Fee EUR`, `Amount BTC`, `Exchange Rate`
  - `Send`: BTC-Auszahlung an eigene Wallet — `Amount BTC` negativ (abs nehmen), kein EUR-Betrag
  - `Receive`: BTC-Eingang ohne Kaufpreis (Trinkgeld/Spende) — TRANSFER_IN, `eur_amount = 0`
  - `Deposit`: EUR-Einzahlung — irrelevant

### Broker: Pocket (`Broker/Pocket*.csv`)
CSV, Komma-getrennt, UTF-8 (mehrere Dateien möglich, Pattern: `Pocket*.csv`).
Transaktionen kommen als Dreier-Gruppen (deposit / exchange / withdrawal):

```
type,date,value.currency,value.amount,cost.currency,cost.amount,fee.currency,fee.amount,price.amount
```

- `type=exchange` mit `cost.currency=EUR`: BTC-Kauf
- `type=exchange` mit `cost.currency=BTC`: BTC-Verkauf
- Zugehörige `deposit`-Zeile mit gleichem Timestamp enthält Betrag der Gegenseite

---

## Historische Wechselkurse (für Swissquote USD/CHF)

- API: `https://api.frankfurter.app/{YYYY-MM-DD}?from=USD&to=EUR`
- Nur bei Swissquote-Käufen in USD oder CHF nötig
- **Kurse lokal cachen** (Dict oder JSON-Datei `fx_cache.json`) — kein wiederholter API-Call für gleichen Tag
- Bei API-Fehler: Fehlermeldung mit betroffener Transaktion ausgeben, nicht stillschweigend 0 einsetzen

---

## Technologie-Stack

- **Python 3.10+**
- `pandas` — CSV-Parsing
- `decimal.Decimal` — **alle** Finanzberechnungen (NIEMALS `float` für Geldbeträge!)
- `requests` — Wechselkurs-API
- Keine Datenbank, kein Web-Framework

---

## Architektur

```
btc_steuertool/
├── CLAUDE.md
├── bitbox/                    # Original-CSVs BitBox (unveränderlich, in .gitignore)
├── Broker/                    # Original-CSVs Broker (unveränderlich, in .gitignore)
├── examples/                  # Fiktive Testdaten
├── src/
│   ├── models.py              # Transaction Dataclass + Enums
│   ├── parsers/
│   │   ├── bitbox.py
│   │   ├── broker_21bitcoin.py
│   │   ├── broker_bison.py
│   │   ├── broker_swissquote.py
│   │   ├── broker_strike.py
│   │   ├── broker_pocket.py
│   │   └── manual_sales.py
│   ├── fx_rates.py            # Wechselkurs-Abruf + Caching
│   ├── fifo_engine.py         # FiFo Lot-Verwaltung + Gewinnberechnung
│   ├── tax_report.py          # Report-Generierung (Text + CSV)
│   ├── formal_report.py       # Formaler Steuernachweis (--nachweis)
│   └── main.py                # CLI-Einstieg
├── fx_cache.json              # Gecachte Wechselkurse (wird automatisch angelegt)
├── reports/                   # Generierte Berichte (wird automatisch angelegt)
└── requirements.txt
```

---

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

@dataclass
class Transaction:
    date: datetime            # timezone-aware, intern immer UTC
    type: TxType
    btc_amount: Decimal       # immer positiv, in BTC (nicht Satoshi)
    eur_amount: Decimal       # Kaufpreis oder Verkaufserlös (vor Gebühren), 0 bei Transfer
    eur_price_per_btc: Decimal  # 0 bei Transfer
    fee_eur: Decimal          # Gebühren in EUR (0 wenn nicht bekannt)
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
2. Lots in einer Liste sortiert nach Kaufdatum (älteste zuerst)
3. Bei `SELL`: Lots von vorne aufbrauchen bis BTC-Menge erreicht
4. Für jedes verbrauchte Lot berechnen:
   - `holding_days = (sell_date - lot.purchase_date).days`
   - `is_tax_free = holding_days > 365`
   - `gain = (net_sell_price_per_btc - lot.cost_per_btc) * used_btc_amount`
   - `net_sell_price_per_btc = (eur_amount - fee_eur) / total_btc_sold`
5. `TRANSFER_OUT` / `TRANSFER_IN`: keine Lot-Änderung (Kostenbasis bleibt)

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

## Output-Format (Text-Report)

```
=== Bitcoin Steuerreport Deutschland — 2024 ===
Erstellt: 2025-03-26  |  Methode: FiFo  |  Haltefrist: 365 Tage

KÄUFE 2024
Datum        Quelle       BTC-Betrag    Kurs EUR/BTC    Gebühr EUR   Einstand EUR
2024-01-15   21bitcoin      0.00823126    41.000,00          6,00        343,88
...

STEUERPFLICHTIGE VERÄUSSERUNGEN 2024 (Haltedauer ≤ 365 Tage)
------------------------------------------------------------------
Verkauf: 2024-09-15  Bison  0.13908920 BTC  @  96.590,18 EUR/BTC  =  13.434,65 EUR
  Lot 1: Kauf 2024-02-01  0.05000000 BTC  @  45.000,00 EUR/BTC  →  Gewinn:  2.579,50 EUR  (227 Tage)
  Lot 2: Kauf 2024-03-15  0.08908920 BTC  @  61.000,00 EUR/BTC  →  Gewinn:    222,70 EUR  (184 Tage)
  Summe Gewinn steuerpflichtig: 2.802,20 EUR

STEUERFREIE VERÄUSSERUNGEN 2024 (Haltedauer > 365 Tage)
------------------------------------------------------------------
Verkauf: 2024-06-01  Bison  0.00500000 BTC  @  65.000,00 EUR/BTC  =  325,00 EUR
  Lot 1: Kauf 2022-05-10  0.00500000 BTC  @  32.000,00 EUR/BTC  →  Gewinn:    165,00 EUR  (752 Tage) STEUERFREI

ZUSAMMENFASSUNG 2024
  Gesamterlöse Veräußerungen:          13.759,65 EUR
  Anschaffungskosten (FiFo):            8.952,25 EUR
  Gebühren gesamt:                         80,20 EUR
  ─────────────────────────────────────────────────
  Gewinn steuerpflichtig (≤ 365 Tage):  2.802,20 EUR
  Gewinn steuerfrei (> 365 Tage):         165,00 EUR
  Freigrenze 2024 (1.000 EUR):          → ÜBERSCHRITTEN — voller Betrag zu versteuern
```

---

## Transfer-Matching (`transfer_matcher.py`)

Dient der Plausibilitätsprüfung und Kennzeichnung von Überträgen:

- Matcher versucht, Broker-Withdrawals mit BitBox-Received-Transaktionen zu verknüpfen
- Matching-Kriterien: BTC-Betrag ± On-Chain-Fee, Zeitfenster ± 24h
- Nicht gematchte Transfers werden im Report als Warnung ausgegeben
- Matching ist **nicht** steuerrelevant — ändert keine FiFo-Berechnungen

---

## Bekannte Ergebnisse (eigene Referenzwerte eintragen)

Trage hier nach dem ersten erfolgreichen Lauf deine eigenen Referenzwerte ein,
um spätere Code-Änderungen auf Korrektheit prüfen zu können:

| Jahr | Käufe BTC | Steuerpfl. Gewinn | Steuerfreier Gewinn | Hinweis |
|------|-----------|-------------------|---------------------|---------|
| ...  | ...       | ...               | ...                 | ...     |

---

## Wichtige Implementierungshinweise

- Alle Datumsangaben intern als **timezone-aware datetime in UTC** speichern
- BitBox-Timestamps haben Timezone-Offset (`+01:00`, `+02:00`) → korrekt parsen
- Bison-Timestamps sind UTC → als UTC markieren
- Satoshi-Beträge **sofort** beim Parsen in BTC umrechnen: `Decimal(satoshi) / Decimal(100_000_000)`
- Bei Swissquote: mehrere Kauf-Zeilen mit gleicher `Auftrag #` → zu **einer** Transaktion zusammenfassen
- Bison-CSV: Leerzeichen nach Semikolon beim Parsen trimmen
- Original-CSV-Dateien **niemals** verändern
