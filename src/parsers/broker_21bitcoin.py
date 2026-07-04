"""Parser für 21bitcoin CSV-Exporte."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType
from . import warn


def parse(filepath: Path) -> list[Transaction]:
    transactions = []
    with open(filepath, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tx = _parse_row(row, filepath.name)
            if tx is not None:
                transactions.append(tx)
    return transactions


def _parse_row(row: dict, filename: str) -> Transaction | None:
    tx_type_raw = row["transaction_type"].strip().lower()

    # Datum: "DD.MM.YYYY HH:MM:SS" — 21bitcoin gibt keine Timezone an,
    # laut Support handelt es sich um UTC
    date_str = row["transaction_date"].strip()
    date = datetime.strptime(date_str, "%d.%m.%Y %H:%M:%S").replace(tzinfo=timezone.utc)

    note = row.get("note", "").strip()
    row_id = row.get("id", "").strip()

    if tx_type_raw == "trade":
        # BTC-Kauf: buy_asset=BTC, sell_asset=EUR
        buy_asset = row.get("buy_asset", "").strip().upper()
        sell_asset = row.get("sell_asset", "").strip().upper()
        if buy_asset != "BTC" or sell_asset != "EUR":
            # Nicht stillschweigend verwerfen — ein BTC-Verkauf wäre steuerlich relevant!
            if sell_asset == "BTC":
                warn(
                    f"{filename}: BTC-Verkauf am {date.date()} wird vom 21bitcoin-Parser "
                    f"noch nicht unterstützt — bitte als manual_sales.csv erfassen, "
                    f"sonst ist der Report unvollständig."
                )
            else:
                warn(f"{filename}: Trade-Zeile mit {sell_asset}→{buy_asset} nicht verarbeitet.")
            return None

        btc_amount = Decimal(row["buy_amount"].strip())
        eur_amount = Decimal(row["sell_amount"].strip())
        fee_eur = Decimal(row["fee_amount"].strip()) if row.get("fee_amount", "").strip() else Decimal("0")
        eur_price_per_btc = eur_amount / btc_amount if btc_amount else Decimal("0")

        return Transaction(
            date=date,
            type=TxType.BUY,
            btc_amount=btc_amount,
            eur_amount=eur_amount,
            eur_price_per_btc=eur_price_per_btc,
            fee_eur=fee_eur,
            source="21bitcoin",
            tx_id=f"21btc-{row_id}",
            note=note,
        )

    elif tx_type_raw == "withdrawal":
        # BTC-Auszahlung an eigene Wallet
        sell_asset = row.get("sell_asset", "").strip().upper()
        if sell_asset != "BTC":
            return None

        btc_amount = Decimal(row["sell_amount"].strip())
        fee_btc = Decimal(row["fee_amount"].strip()) if row.get("fee_amount", "").strip() else Decimal("0")

        return Transaction(
            date=date,
            type=TxType.TRANSFER_OUT,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            source="21bitcoin",
            tx_id=f"21btc-{row_id}",
            note=note,
        )

    # deposit (EUR-Einzahlung) ist bekannt irrelevant — alles Unbekannte melden
    if tx_type_raw != "deposit":
        warn(f"{filename}: unbekannter Transaktionstyp '{tx_type_raw}' am {date.date()} nicht verarbeitet.")
    return None
