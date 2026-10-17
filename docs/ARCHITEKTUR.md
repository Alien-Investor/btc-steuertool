# BTC Steuertool — Architektur und Transaktionsmodell

Ausgelagert aus `CLAUDE.md` (17.10.2026), Wortlaut unverändert.

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
