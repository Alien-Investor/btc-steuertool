"""Parser für manuelle Käufe (manual_buys.csv).

Für private BTC-Käufe die in keiner Broker-CSV auftauchen:
P2P-Handel (Bisq, Robosats, HodlHodl), Bargeld-Käufe, noKYC-Trades etc.

Format (UTF-8, Komma-getrennt):
    date,btc_amount,eur_amount,note
    2024-03-10,0.01000000,550.00,Bisq P2P Kauf
    2024-07-22,0.00500000,280.00,Robosats

- date: YYYY-MM-DD (wird als 12:00 UTC interpretiert)
- btc_amount: BTC gekauft (positiv)
- eur_amount: EUR bezahlt (Gesamtbetrag inkl. Gebühren)
- note: Freitext (z.B. Quelle, Trade-ID)

Hinweis: Der Report weist manuell eingegebene Käufe als solche aus.
Das Finanzamt hat keinen Anspruch auf den vollständigen Wallet-Fingerprint —
korrekte Angabe der Anschaffungskosten ist ausreichend.
"""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType


def parse(filepath: Path) -> list[Transaction]:
    transactions = []
    with open(filepath, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            row = {k.strip(): v.strip() for k, v in row.items()}
            tx = _parse_row(row, i)
            if tx is not None:
                transactions.append(tx)
    return transactions


def _parse_row(row: dict, line: int) -> Transaction | None:
    date_str = row.get("date", "").strip()
    btc_str = row.get("btc_amount", "").strip()
    eur_str = row.get("eur_amount", "").strip()

    if not date_str or not btc_str or not eur_str:
        return None

    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").replace(
            hour=12, tzinfo=timezone.utc
        )
        btc_amount = Decimal(btc_str)
        eur_amount = Decimal(eur_str)
    except Exception as e:
        raise ValueError(f"manual_buys.csv Zeile {line}: ungültiger Wert — {e}") from e

    note = row.get("note", "").strip() or "Manueller Kauf"
    eur_price_per_btc = eur_amount / btc_amount if btc_amount else Decimal("0")

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
    )
