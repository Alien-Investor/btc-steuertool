# Datenformate und Report-Beispiel — BTC Steuertool

Ausgelagert aus `CLAUDE.md` (02.10.2026, Wortlaut unverändert). Vor jeder Arbeit an `src/parsers/` oder an einem neuen Parser lesen.

## Datenquellen

**Leseregeln für alle Parser (seit dem Parser-Audit 03.10.2026, `src/parsers/__init__.py`):** Jeder Parser liest über
`read_rows(...)` mit einer Liste von Pflichtspalten. Fehlt eine, bricht der Lauf hart ab (Datei + Spalte); eine BOM am
Dateianfang wird abgestreift, Schlüssel und Werte getrimmt, Zeilen mit falscher Feldanzahl und Zeilenumbrüche innerhalb
eines Feldes (nicht geschlossenes Anführungszeichen) sind harte Fehler mit Zeilennummer. Zahlen gehen durch `parse_amount`
(Punkt als Dezimaltrenner; ein Komma nur, wenn eindeutig; `-` und leer = 0; NaN/Infinity/≥ 1e15 abgelehnt), ISO-Zeitstempel
durch `parse_iso_datetime` (Zeitzone Pflicht, `Z` erlaubt). Warnungen sind auf 1.000 je Lauf gedeckelt. **Neue Parser
nutzen genau diese Helfer** — `row.get("Spalte", "")` ohne Pflichtspaltenprüfung ist der Fehler, den das Audit gefunden hat.

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

CSV, Komma-getrennt, UTF-8 (Bisq-Classic-Export „Portfolio → Verlauf → Als CSV exportieren" bzw. „Portfolio → History →
Export to CSV"; Bisq speichert als `tradeHistory.csv`). Spaltenköpfe und die Werte in `Angebotstyp`/`Status` kommen aus
Bisqs Sprachdatei — der Parser kennt **Deutsch und Englisch** (`bisq.LANGUAGES`, Quelle: Bisq `ClosedTradesView.ColumnNames`
+ `displayStrings.properties` / `displayStrings_de.properties`, Stand 10/2026). Andere Oberflächensprachen → interne Warnung,
keine Transaktion. Der englische Export ist aus dem Quellcode abgeleitet; Kopfzeile und Datumsform (`10 Mar 2021 10:40:20`) decken sich mit einer
veröffentlichten Beispieldatei eines echten Exports (rotki-Testdaten) — ein eigener Export des Autors fehlt noch.

```
Handels-ID,Datum/Zeit,Markt,Preis,Abweichung,Betrag in BTC,Betrag,Währung,
Transaktionsgebühr,Handelsgebühr BTC,Handelsgebühr BSQ,Käufer-Kaution,
Verkäufer-Kaution,Angebotstyp,Status

Trade ID,Date/Time,Market,Price,Deviation,Amount in BTC,Amount,Currency,
Transaction Fee,Trade Fee BTC,Trade Fee BSQ,Buyer Deposit,Seller Deposit,
Offer type,Status
```

- Nur `Status=Abgeschlossen`/`Completed` + `Angebotstyp=BTC kaufen`/`Buy BTC` wird geparst; `BTC verkaufen`/`Sell BTC` → Warnung
  (manual_sales.csv). Andere Status (`Abgebrochen`/`Canceled`, `Vermittelt`/`Arbitrated`, `Mediiert`/`Mediated`) werden gezählt.
- `Betrag in BTC`/`Amount in BTC` → btc_amount, `Betrag`/`Amount` → eur_amount (Bisq rundet Fiat-Volumen auf ganze EUR),
  `Preis`/`Price` → eur_price_per_btc. Zahlen immer mit Punkt, ohne Tausendertrennung (bitcoinj `MonetaryFormat`, sprachunabhängig).
- Gebühren: `Transaktionsgebühr`/`Transaction Fee` + `Handelsgebühr BTC`/`Trade Fee BTC` (beide in BTC) × Preis = fee_eur, zusätzlich fee_btc
- Kautionen (`Käufer-/Verkäufer-Kaution`, `Buyer/Seller Deposit`) sind KEINE Gebühren — werden ignoriert
- **Datum/Zeit** = lokale Systemzeit ohne Zeitzone (als Europe/Berlin gelesen), Form nach Javas `DateFormat.DEFAULT` der
  Bisq-Locale (Sprache + Land). Deutsch immer `15.03.2024 14:22:10`. Englisch je Land: `15 Mar 2024 14:22:10` (GB, DE, AT, CH),
  `Mar 15, 2024 2:22:10 PM` (US; ab Java 20 mit schmalem Leerzeichen U+202F vor PM), `… p.m.` (CA), `… pm` (AU),
  `15-Mar-2024 …` (IN), `15/03/2024 …` (NZ), September auch als `Sept`. `bisq.parse_datetime_en` nimmt alle; unlesbar → harter Fehler.
- **Altcoin-Märkte** (`Markt`/`Market` ohne `BTC/`-Präfix, z. B. `XMR/BTC`, `BSQ/BTC`): `XMR kaufen`/`Buy XMR` = BTC hergegeben =
  Veräußerung von BTC; `XMR verkaufen`/`Sell XMR` = Anschaffung von BTC gegen Altcoin. Beides laute interne Warnung mit Anweisung
  (manual_sales.csv bzw. manual_buys.csv mit EUR-Wert), nie stilles Zählen.
- Datei wird mit `utf-8-sig` gelesen (BOM aus Excel/LibreOffice stört nicht); GUI-Erkennung an `Handels-ID,Datum/Zeit,` bzw. `Trade ID,Date/Time,`
- **`no_kyc=True`** — erscheint NICHT im offiziellen Finanzamt-Report

### Sammelimport: CoinTracking / Blockpit (`Broker/cointracking*.csv`, `Broker/blockpit*.csv`, `Broker/sammelimport*.csv`)

Parser `src/parsers/sammelimport.py`. Erkennung am Inhalt (fünf Kopfzeilen), Trennzeichen `,` oder `;`. **Aus der
Dokumentation und veröffentlichten Beispieldateien abgeleitet, noch nicht an einem echten Export bestätigt** — jede Datei
erzeugt eine sichtbare Warnung im Steuerreport (Dateiname im offiziellen Kanal redigiert).

```
CT_IMPORT  "Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
           [,"Liquidity pool (optional)","Tx-ID (optional)","Buy Value in Account Currency (optional)","Sell Value in Account Currency (optional)"]
CT_EXPORT  "Type","Buy","Cur.","Sell","Cur.","Fee","Cur.","Exchange","Group","Comment","Date"          (leer = "-")
CT_FULL    Type,Buy,Cur.,Value in BTC,Value in EUR,Sell,Cur.,Value in BTC,Value in EUR,Spread,Exchange,Group,Date
BP_NEW     Date (UTC),Integration Name,Label,Outgoing Asset,Outgoing Amount,Incoming Asset,Incoming Amount,Fee Asset,Fee Amount,Trx. ID,Comments,Source Type,Source Name
BP_OLD     Blockpit ID;Timestamp;Source Type;Source Name;Integration;Transaction Type;Outgoing Asset;Outgoing Amount;Incoming Asset;Incoming Amount;Fee Asset;Fee Amount;Transaction ID;Note;Merge ID
```

- Quellen: CoinTracking-Importseite (`cointracking.info/import/import_csv/`), Blockpit-Hilfecenter („How to export my transactions
  as a CSV file"), veröffentlichte Beispieldateien (rotki-Testdaten: CT_EXPORT, BP_OLD, Bisq EN), Formatwissen aus BittyTax (CT_FULL,
  BP_NEW-Vorlage). Kein fremder Code.
- **Konto = Wallet:** Spalte `Exchange` (CT) bzw. `Source Name` (Blockpit, interner Name; nicht der selbst vergebene
  `Integration Name`) wird `source` und `wallet`; `direct=False`. Der Kontoname erscheint als „Quelle" in den Reports und
  unter „Datenquellen" im Nachweis (`parsers.aggregate_sources`). Leer/„no exchange" → `CoinTracking`/`Blockpit`.
- **Zeit:** CT ohne Zeitzone → Europe/Berlin (Zeit der Kontoeinstellung, Annahme deutscher Nutzer); Blockpit `Date (UTC)`/`Timestamp`
  → UTC. Formen `TT.MM.JJJJ HH:MM[:SS]`, `JJJJ-MM-TT HH:MM[:SS]`, ISO mit Offset/`Z`. Schrägstrich-Daten (`5/9/2017`) → harter Fehler.
- **Abbildung (nur BTC, Zeilen ohne BTC-Bezug still übersprungen):** Trade BTC←EUR/USD/CHF → BUY (Gebühr Fiat → `fee_eur`,
  Gebühr BTC → `fee_btc` + Einstand wie Bisq); Trade Fiat←BTC → SELL (Erlös vor Gebühr); Trade BTC↔Krypto (auch USDT) nur mit
  EUR-Wert der BTC-Seite (CT_FULL `Value in EUR`, USD/CHF umgerechnet), sonst laute Warnung; Deposit → TRANSFER_IN; Withdrawal →
  TRANSFER_OUT mit Betrag **ohne** Gebühr (`fee_btc` separat — Annahme wie BitBox/21bitcoin, am echten Export prüfen);
  `Fee`/`Other Fee` in BTC → Gebührenabgang (Menge 0); BTC-Gebühr an einer Nicht-BTC-Zeile ebenso; Income/Mining/Staking/Airdrop/
  Gift(in)/Reward/Lending mit EUR-Wert → BUY mit Hinweis „Einordnung des Zuflusses prüfen", sonst Warnung; Spend/Payment mit EUR-Wert
  → SELL, sonst Warnung; Gift(out)/Donation → GIFT_OUT; Lost/Stolen/Margin → Warnung, Bestand bleibt; `Non-Taxable (In/Out)` →
  wie Deposit/Withdrawal; unbekannte Typen mit BTC → Warnung.
- **noKYC:** Kontoname nennt Bisq/RoboSats/Hodl Hodl/Peach/AgoraDesk, oder Dateiname enthält `nokyc` (GUI-Typ „CoinTracking/Blockpit-Export
  (noKYC)") → `no_kyc=True`.
- **Doppelt geladene Wallet:** gleiche TX-ID in gleicher Richtung wie BitBox/Broker-Export → Warnung (`main._warn_double_loaded_wallets`).
- Fixtures: `tests/fixtures/sammel_*.csv` (eigene Werte), Tests `tests/test_sammelimport.py`. Bewusst **nicht** in `examples/`, solange das
  Format unbestätigt ist.

### Broker: Strike (`Broker/strike_YYYY.csv`)
CSV, Komma-getrennt, UTF-8 (mehrere Dateien pro Jahr möglich, Pattern: `strike_*.csv`):

```
Transaction ID,Time (UTC),Status,Transaction Type,Amount EUR,Fee EUR,Amount BTC,Fee BTC,Description,Exchange Rate,Transaction Hash
```

- `Time (UTC)`: Format `Mon DD YYYY HH:MM:SS` (UTC)
- Relevante `Transaction Type`-Werte:
  - `Purchase`: BTC-Kauf — `Amount EUR` negativ (abs nehmen), `Fee EUR`, `Amount BTC`, `Exchange Rate`
  - `Send`: BTC-Auszahlung an eigene Wallet — `Amount BTC` negativ (abs nehmen), kein EUR-Betrag.
    `Amount BTC` **enthält** die Netzwerkgebühr `Fee BTC` (geprüft am echten Export gegen den
    BitBox-Eingang derselben TX-ID): übertragen = `|Amount BTC| − Fee BTC`, die Gebühr ist eine
    Veräußerung des Gebührenanteils (`fee_btc`). `Transaction Hash` = On-Chain-TX-ID.
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
- Pocket hält keinen Bestand (`direct=True`): ein Kauf wird dem Eingang in der eigenen
  Wallet zugeordnet (Lieferung), ein Verkauf dem Abgang, aus dem er bedient wurde.

### Manuelle Käufe (`manual_buys.csv`)
CSV, Komma-getrennt, UTF-8. Unbekannte Spalten sind ein harter Fehler.

```
date,btc_amount,eur_amount,note,kyc,wallet
2024-03-10,0.01000000,550.00,P2P Kauf,,
2024-12-01,0.00200000,190.00,Coinbase Kauf,ja,wallet1
```

- `date` = `YYYY-MM-DD` (12:00 UTC), `eur_amount` = gezahlter Gesamtbetrag
- `kyc`: `ja`/`1`/`true` → KYC-Kauf (Broker ohne Parser, im Finanzamt-Report); leer → noKYC
- `wallet` (optional): eigene Wallet, an die geliefert wurde — Dateiname des BitBox-Exports
  ohne `.csv` oder ein Broker. Leer → Lieferung über den passenden Eingang automatisch.
  Unbekannter Name oder KYC-Kauf in eine noKYC-Wallet (und umgekehrt) → harter Fehler.

### Manuelle Verkäufe (`manual_sales.csv`)

```
date,btc_amount,eur_amount,note,no_kyc,wallet
2024-06-15,0.00300000,195.00,Privatverkauf,,wallet1
```

- `no_kyc`: `ja` → Verkauf aus dem noKYC-Bestand (nur interner Report). **Umgekehrte
  Polarität** zu `kyc` in `manual_buys.csv`.
- `wallet` (optional): Wallet, aus der verkauft wurde. Leer → aus dem passenden Abgang der
  Wallet ermittelt; ohne Abgang aus Beständen ohne bekannten Verwahrort, mit Warnung.

### Übertrags-Zuordnung (`transfer_zuordnung.csv`)
Nur nötig, wenn die automatische Zuordnung (TX-ID, sonst Betrag in ±48 h) nicht greift —
typisch: mehrere Bisq-Käufe in einer Auszahlung, Eingang mehr als 48 h nach dem Abgang.

```
datum_abgang,von,menge_abgang,datum_eingang,nach,menge_eingang,notiz
2024-11-05,bisq,0.00250000,2024-11-25,nokyc_wallet,0.00394500,Sammelauszahlung
2024-11-20,manual,0.00150000,2024-11-25,nokyc_wallet,0.00394500,Sammelauszahlung
```

- Eine Zeile = eine Verbindung „abgebend → aufnehmend“. Abgebend: Abgang (BitBox `sent`,
  Broker-Auszahlung) oder Direktkauf (Pocket, Bisq, manual); aufnehmend: Eingang oder
  Direktverkauf. Mehrere Zeilen mit demselben Eingang = Sammelauszahlung.
- Datum (deutsches Kalenderdatum), Wallet und Menge wie in Warnung bzw. internem
  Wallet-Abgleich. Wallet: BitBox-Dateiname ohne `.csv`, Broker oder `manual`.
- Bei einem Direktkauf wandert genau dessen Lot (abzüglich einer BTC-Handelsgebühr).
- Nicht auffindbare oder mehrdeutige Zeile, KYC↔noKYC → harter Fehler.

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
