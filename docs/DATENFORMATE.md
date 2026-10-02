# Datenformate und Report-Beispiel — BTC Steuertool

Ausgelagert aus `CLAUDE.md` (02.10.2026, Wortlaut unverändert). Vor jeder Arbeit an `src/parsers/` oder an einem neuen Parser lesen.

## Datenquellen

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
  - `withdrawal` mit `sell_asset=BTC`: BTC-Auszahlung an eigene Wallet — `sell_amount` = BTC, die
    ankommen; `fee_amount` (BTC) kommt OBENDRAUF (15.08.2026 gegen BitBox-`received` geprüft:
    41 von 52 Auszahlungen treffen exakt `sell_amount`, keine `sell_amount − fee`) → `fee_btc`
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

### Broker: Bisq (`Broker/bisq*.csv`)

CSV, Komma-getrennt, deutschsprachig (Bisq-Export "Portfolio → Trades → Exportieren"):

```
Handels-ID,Datum/Zeit,Markt,Preis,Abweichung,Betrag in BTC,Betrag,Währung,
Transaktionsgebühr,Handelsgebühr BTC,Handelsgebühr BSQ,Käufer-Kaution,
Verkäufer-Kaution,Angebotstyp,Status
```

- Nur `Status=Abgeschlossen` + `Angebotstyp=BTC kaufen` wird geparst
- `Betrag in BTC` → btc_amount, `Betrag` → eur_amount, `Preis` → eur_price_per_btc
- Gebühren: `Transaktionsgebühr` + `Handelsgebühr BTC` (beide in BTC) × Preis = fee_eur
- Kautionen sind KEINE Gebühren — werden ignoriert
- **`no_kyc=True`** — erscheint NICHT im offiziellen Finanzamt-Report

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

- `type=exchange` mit `cost.currency=EUR` (oder `CHF`/`USD`): BTC-Kauf
- `type=exchange` mit `cost.currency=BTC`: BTC-Verkauf
- Zugehörige `deposit`-Zeile mit gleichem Timestamp enthält Betrag der Gegenseite
- **CHF/USD-Käufe** (Pocket ist ein Schweizer Dienst): EUR-Kurs aus der gebündelten
  EZB-Tabelle via `fx_rates` — wie bei Swissquote

---

---

## Output-Format (Text-Report)

```
=== Bitcoin Steuerreport Deutschland — 2024 ===
Erstellt: 2025-03-26  |  Methode: FiFo  |  Veräußerungsfrist: ein Jahr  |  § 23 EStG

KÄUFE 2024
Datum        Quelle       BTC-Betrag    Kurs EUR/BTC    Gebühr EUR   Einstand EUR
2024-01-15   21bitcoin      0.00823126    41.000,00          6,00        343,88
...

STEUERPFLICHTIGE VERÄUSSERUNGEN (Veräußerung innerhalb eines Jahres)
------------------------------------------------------------------
Verkauf: 2024-09-15  Bison  0.13908920 BTC  @  96.590,18 EUR/BTC  =  13.434,65 EUR
  Lot 1: Kauf 2024-02-01  0.05000000 BTC  @  45.000,00 EUR/BTC  →  Gewinn:  2.579,50 EUR  (227 Tage)
  Lot 2: Kauf 2024-03-15  0.08908920 BTC  @  61.000,00 EUR/BTC  →  Gewinn:    222,70 EUR  (184 Tage)
  Summe Gewinn steuerpflichtig: 2.802,20 EUR

STEUERFREIE VERÄUSSERUNGEN (Veräußerung nach mehr als einem Jahr)
------------------------------------------------------------------
Verkauf: 2024-06-01  Bison  0.00500000 BTC  @  65.000,00 EUR/BTC  =  325,00 EUR
  Lot 1: Kauf 2022-05-10  0.00500000 BTC  @  32.000,00 EUR/BTC  →  Gewinn:    165,00 EUR  (752 Tage) STEUERFREI

ZUSAMMENFASSUNG 2024
  Gesamterlöse Veräußerungen:          13.759,65 EUR
  Anschaffungskosten (FiFo):            8.952,25 EUR
  Gebühren gesamt:                         80,20 EUR
  ─────────────────────────────────────────────────
  Gewinn steuerpflichtig (bis 1 Jahr):  2.802,20 EUR
  Gewinn steuerfrei (über 1 Jahr):        165,00 EUR
  Freigrenze 2024 (1.000 EUR):          → ÜBERSCHRITTEN — voller Betrag zu versteuern
```
