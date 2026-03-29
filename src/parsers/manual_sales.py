"""Parser für manuelle Verkäufe (manual_sales.csv).

Für private BTC-Verkäufe (z.B. Peer-to-Peer) die in keiner Broker-CSV auftauchen.

Format (UTF-8, Komma-getrennt):
    date,btc_amount,eur_amount,note
    2024-06-15,0.00500000,325.00,P2P Verkauf

- date: YYYY-MM-DD (wird als 12:00 UTC interpretiert)
- btc_amount: BTC verkauft (positiv)
- eur_amount: EUR erhalten (netto, ohne zusätzliche Gebühren)
- note: Freitext
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
        raise ValueError(f"manual_sales.csv Zeile {line}: ungültiger Wert — {e}") from e

    note = row.get("note", "").strip() or "Manueller Verkauf"
    eur_price_per_btc = eur_amount / btc_amount if btc_amount else Decimal("0")

    return Transaction(
        date=date,
        type=TxType.SELL,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=Decimal("0"),
        source="manual",
        tx_id=f"manual-{date_str}-{btc_str}",
        note=note,
    )
