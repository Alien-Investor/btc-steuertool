"""Parser für Bison Broker CSV-Exporte."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType


def parse(filepath: Path) -> list[Transaction]:
    transactions = []
    with open(filepath, encoding="utf-8", newline="") as f:
        # Semikolon als Trennzeichen, Leerzeichen nach Semikolon werden getrimmt
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            # Alle Keys und Values trimmen (Bison hat Leerzeichen nach dem Semikolon)
            row = {k.strip(): v.strip() for k, v in row.items() if k is not None}
            tx = _parse_row(row)
            if tx is not None:
                transactions.append(tx)
    return transactions


def _parse_row(row: dict) -> Transaction | None:
    tx_type_raw = row.get("Transaction type", "").strip()
    asset = row.get("Asset", "").strip().upper()
    currency = row.get("Currency", "").strip().upper()

    # Datum: "YYYY-MM-DD HH:MM:SS" UTC
    date_str = row.get("Date (UTC - Coordinated Universal Time)", "").strip()
    if not date_str:
        return None
    date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

    tx_id = row.get("Transaction ID", "").strip()

    if tx_type_raw == "Buy" and asset == "BTC":
        eur_amount = _decimal(row.get("Eur (amount)", "0"))
        btc_amount = _decimal(row.get("Asset (amount)", "0"))
        market_price = _decimal(row.get("Asset (market price)", "0"))
        # Bison hat keine explizite Gebühr — im Spread enthalten, fee_eur = 0
        return Transaction(
            date=date,
            type=TxType.BUY,
            btc_amount=btc_amount,
            eur_amount=eur_amount,
            eur_price_per_btc=market_price if market_price else (eur_amount / btc_amount if btc_amount else Decimal("0")),
            fee_eur=Decimal("0"),
            source="bison",
            tx_id=tx_id,
            note=f"Bison Kauf",
        )

    elif tx_type_raw == "Sell" and asset == "BTC":
        eur_amount = _decimal(row.get("Eur (amount)", "0"))
        btc_amount = _decimal(row.get("Asset (amount)", "0"))
        market_price = _decimal(row.get("Asset (market price)", "0"))
        return Transaction(
            date=date,
            type=TxType.SELL,
            btc_amount=btc_amount,
            eur_amount=eur_amount,
            eur_price_per_btc=market_price if market_price else (eur_amount / btc_amount if btc_amount else Decimal("0")),
            fee_eur=Decimal("0"),
            source="bison",
            tx_id=tx_id,
            note=f"Bison Verkauf",
        )

    elif tx_type_raw == "Deposit" and asset == "BTC" and currency == "":
        # BTC-Eingang von eigener Wallet (für Verkauf eingesendet)
        btc_amount = _decimal(row.get("Asset (amount)", "0"))
        return Transaction(
            date=date,
            type=TxType.TRANSFER_IN,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            source="bison",
            tx_id=tx_id,
            note="BTC-Eingang von eigener Wallet",
        )

    # Deposit EUR, Withdraw EUR, ETH-Transaktionen → ignorieren
    return None


def _decimal(value: str) -> Decimal:
    val = value.strip().replace(",", ".")
    return Decimal(val) if val else Decimal("0")
