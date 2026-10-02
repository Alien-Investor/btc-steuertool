"""Parser für manuelle Käufe (manual_buys.csv).

Für private BTC-Käufe die in keiner Broker-CSV auftauchen:
P2P-Handel (Bisq, Robosats, HodlHodl), Bargeld-Käufe, noKYC-Trades —
oder Käufe bei KYC-Brokern ohne eigenen Parser (Spalte kyc=ja).

Format (UTF-8, Komma-getrennt, Spalte kyc optional):
    date,btc_amount,eur_amount,note,kyc
    2024-03-10,0.01000000,550.00,Bisq P2P Kauf,
    2024-07-22,0.00500000,280.00,Robosats,
    2024-09-01,0.00300000,180.00,Coinbase Kauf,ja

- date: YYYY-MM-DD (wird als 12:00 UTC interpretiert)
- btc_amount: BTC gekauft (positiv)
- eur_amount: EUR bezahlt (Gesamtbetrag inkl. Gebühren)
- note: Freitext (z.B. Quelle, Trade-ID)
- kyc: "ja"/"1"/"true" → Kauf bei einem KYC-Broker ohne eigenen Parser:
  landet im KYC-FiFo-Pool und erscheint im offiziellen Finanzamt-Report.
  Leer oder fehlend → noKYC (Standard, nur im internen Report).
- wallet (optional): eigene Wallet, an die geliefert wurde — Dateiname des
  BitBox-Exports ohne .csv (z.B. wallet1) oder ein Broker. Dann liegt das Lot
  von Anfang an dort (walletbezogenes FiFo, BMF Rn. 62). Leer → die Lieferung
  wird über den passenden Eingang automatisch zugeordnet.

Hinweis: Der Report weist manuell eingegebene Käufe als solche aus.
Ein Report mit korrekten Anschaffungskosten reicht in der Regel; im Einzelfall kann das
Finanzamt aber Adressen, Transaktions-Hashes und Bestände anfordern (BMF 06.03.2025 Rn. 101, 104).
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType
from . import validate_header, read_rows, amount, LINE_KEY

LABEL = "manual_buys.csv"
_KNOWN_COLUMNS = {"date", "btc_amount", "eur_amount", "note", "kyc", "wallet"}
# Die Schwesterdatei manual_sales.csv nutzt 'no_kyc' mit UMGEKEHRTER Bedeutung.
_COLUMN_HINTS = {
    "no_kyc": "hier heisst die Spalte 'kyc' und hat die UMGEKEHRTE Bedeutung: "
              "kyc=ja bedeutet Kauf bei einem KYC-Broker",
}


def parse(filepath: Path) -> list[Transaction]:
    transactions = []
    rows, header = read_rows(filepath, label=LABEL)
    validate_header(header, _KNOWN_COLUMNS, LABEL, _COLUMN_HINTS)
    for row in rows:
        tx = _parse_row(row, row[LINE_KEY])
        if tx is not None:
            transactions.append(tx)
    return transactions


def _parse_row(row: dict, line: int) -> Transaction | None:
    date_str = row.get("date", "")
    btc_str = row.get("btc_amount", "")
    eur_str = row.get("eur_amount", "")

    if not date_str and not btc_str and not eur_str:
        return None  # komplett leere Zeile (z.B. Leerzeile am Dateiende)
    if not date_str or not btc_str or not eur_str:
        # Teilweise gefüllte Zeile NICHT still überspringen — fehlender Kauf = falsche FiFo-Kette
        raise ValueError(
            f"manual_buys.csv Zeile {line}: Pflichtfeld fehlt "
            f"(date='{date_str}', btc_amount='{btc_str}', eur_amount='{eur_str}')"
        )

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=12, tzinfo=timezone.utc
        )
    except ValueError as e:
        raise ValueError(f"manual_buys.csv Zeile {line}: ungültiges Datum — {e}") from e
    btc_amount = amount(row, "btc_amount", label=LABEL, filename="")
    eur_amount = amount(row, "eur_amount", label=LABEL, filename="")

    note = row.get("note", "") or "Manueller Kauf"
    eur_price_per_btc = eur_amount / btc_amount if btc_amount else Decimal("0")
    # Spalte kyc=ja → KYC-Kauf (Broker ohne eigenen Parser); Standard bleibt noKYC
    kyc = row.get("kyc", "").lower() in ("ja", "1", "true", "yes", "x")

    return Transaction(
        date=date,
        type=TxType.BUY,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=Decimal("0"),
        source="manual",
        tx_id=f"manual-buy-{date_str}-{btc_str}",
        note=note,
        no_kyc=not kyc,
        direct=True,  # Lieferung an eine eigene Wallet (Zuordnung über den Eingang)
        # Name wie geschrieben; main._resolve_manual_wallets ordnet ihn einer
        # eingelesenen Wallet zu (leer → Quelle „manual“)
        wallet=row.get("wallet", ""),
    )
