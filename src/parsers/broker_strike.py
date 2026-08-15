"""Parser für Strike CSV-Exporte.

Format:
    Transaction ID,Time (UTC),Status,Transaction Type,Amount EUR,Fee EUR,
    Amount BTC,Fee BTC,Description,Exchange Rate,Transaction Hash

Transaktionstypen:
    Purchase  — BTC-Kauf, Amount EUR ist negativ (Betrag den man zahlt)
    Send      — BTC-Auszahlung an eigene Wallet (TRANSFER_OUT)
    Receive   — BTC-Eingang ohne EUR-Gegenwert (z.B. Trinkgeld), TRANSFER_IN
    Deposit   — EUR-Einzahlung, irrelevant
"""
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
    status = row.get("Status", "").strip()
    if status != "Completed":
        # Nur abgeschlossene Vorgänge zählen — aber nicht stillschweigend
        # verwerfen: Purchase/Send/Receive sind steuerlich relevant.
        if row.get("Transaction Type", "").strip() in ("Purchase", "Send", "Receive"):
            warn(
                f"{filename}: {row.get('Transaction Type', '').strip()} vom "
                f"{row.get('Time (UTC)', '?')} mit Status '{status}' nicht verarbeitet.", internal=False
            )
        return None

    tx_type_raw = row.get("Transaction Type", "").strip()

    # Datum: "Jun 24 2025 21:59:51" UTC
    date_str = row.get("Time (UTC)", "").strip()
    date = datetime.strptime(date_str, "%b %d %Y %H:%M:%S").replace(tzinfo=timezone.utc)

    tx_id = row.get("Transaction ID", "").strip()
    tx_hash = row.get("Transaction Hash", "").strip()
    description = row.get("Description", "").strip()

    if tx_type_raw == "Purchase":
        # Amount EUR ist negativ (gezahlter Betrag) → abs nehmen
        eur_raw = row.get("Amount EUR", "").strip()
        fee_raw = row.get("Fee EUR", "").strip()
        btc_raw = row.get("Amount BTC", "").strip()
        rate_raw = row.get("Exchange Rate", "").strip()

        eur_amount = abs(_decimal(eur_raw))
        fee_eur = _decimal(fee_raw)
        btc_amount = _decimal(btc_raw)
        eur_price_per_btc = _decimal(rate_raw) if rate_raw else (
            eur_amount / btc_amount if btc_amount else Decimal("0")
        )

        return Transaction(
            date=date,
            type=TxType.BUY,
            btc_amount=btc_amount,
            eur_amount=eur_amount,
            eur_price_per_btc=eur_price_per_btc,
            fee_eur=fee_eur,
            source="strike",
            tx_id=tx_id,
            note=description or "Strike Kauf",
        )

    elif tx_type_raw == "Send":
        # Amount BTC ist negativ → abs nehmen
        btc_raw = row.get("Amount BTC", "").strip()
        btc_amount = abs(_decimal(btc_raw))

        return Transaction(
            date=date,
            type=TxType.TRANSFER_OUT,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            source="strike",
            tx_id=tx_hash or tx_id,
            note=description or "Strike Auszahlung",
        )

    elif tx_type_raw == "Receive":
        # BTC empfangen ohne EUR-Gegenwert (Trinkgeld/Spende/Testzahlung)
        btc_raw = row.get("Amount BTC", "").strip()
        btc_amount = _decimal(btc_raw)

        return Transaction(
            date=date,
            type=TxType.TRANSFER_IN,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            source="strike",
            tx_id=tx_hash or tx_id,
            note=description or "Strike Eingang (kein Kauf)",
        )

    # Deposit/Withdrawal (EUR-Bewegungen) sind bekannt irrelevant — alles
    # Unbekannte melden (z.B. ein künftiger Verkaufstyp wäre steuerlich relevant!)
    if tx_type_raw not in ("Deposit", "Withdrawal"):
        warn(f"{filename}: unbekannter Transaktionstyp '{tx_type_raw}' am {date.date()} nicht verarbeitet.", internal=False)
    return None


def _decimal(value: str) -> Decimal:
    val = value.strip().replace(",", ".")
    return Decimal(val) if val else Decimal("0")
