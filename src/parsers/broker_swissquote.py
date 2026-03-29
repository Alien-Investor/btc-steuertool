"""Parser für Swissquote CSV-Exporte."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from collections import defaultdict

from ..models import Transaction, TxType
from ..fx_rates import eur_rate_for_date


def parse(filepath: Path) -> list[Transaction]:
    # Encoding: Windows-1252 (Swissquote exportiert mit diesem Encoding)
    rows = []
    with open(filepath, encoding="windows-1252", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items() if k is not None})

    # Kauf-Zeilen mit gleicher Auftragsnummer zusammenfassen
    orders: dict[str, list[dict]] = defaultdict(list)
    other_rows: list[dict] = []

    for row in rows:
        tx_type = row.get("Transaktionen", "").strip()
        order_id = row.get("Auftrag #", "").strip()
        symbol = row.get("Symbol", "").strip().upper()

        if symbol != "BTC":
            continue  # nur BTC relevant

        if tx_type == "Kauf" and order_id:
            orders[order_id].append(row)
        elif tx_type in ("Crypto Withdrawal", "Crypto Deposit"):
            other_rows.append(row)

    transactions = []

    # Käufe (ggf. mehrere Teilausführungen pro Order zusammenfassen)
    for order_id, order_rows in orders.items():
        tx = _merge_buy_rows(order_id, order_rows)
        if tx is not None:
            transactions.append(tx)

    # Withdrawals & Deposits
    for row in other_rows:
        tx = _parse_transfer(row)
        if tx is not None:
            transactions.append(tx)

    return transactions


def _parse_date(date_str: str) -> datetime:
    # Format: "DD-MM-YYYY HH:MM:SS"
    return datetime.strptime(date_str.strip(), "%d-%m-%Y %H:%M:%S").replace(tzinfo=timezone.utc)


def _merge_buy_rows(order_id: str, rows: list[dict]) -> Transaction | None:
    """Fasst mehrere Teilausführungen einer Order zu einer Transaktion zusammen."""
    if not rows:
        return None

    # Datum der ersten Teilausführung
    date = _parse_date(rows[0]["Datum"])
    currency = rows[0].get("Währung", "EUR").strip().upper()

    total_btc = Decimal("0")
    total_cost = Decimal("0")  # Betrag in Originalwährung (ohne Gebühren)
    total_fee = Decimal("0")   # in Originalwährung

    for row in rows:
        btc = Decimal(row["Anzahl"].strip())
        price = Decimal(row["Stückpreis"].strip())
        fee = Decimal(row["Kosten"].strip())
        total_btc += btc
        total_cost += btc * price
        total_fee += fee

    # EUR-Umrechnung falls nötig
    if currency == "EUR":
        total_cost_eur = total_cost
        total_fee_eur = total_fee
    else:
        rate = eur_rate_for_date(date.date(), currency)
        total_cost_eur = total_cost * rate
        total_fee_eur = total_fee * rate

    eur_price_per_btc = total_cost_eur / total_btc if total_btc else Decimal("0")

    return Transaction(
        date=date,
        type=TxType.BUY,
        btc_amount=total_btc,
        eur_amount=total_cost_eur,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=total_fee_eur,
        source="swissquote",
        tx_id=f"swissquote-{order_id}",
        note=f"Swissquote Kauf (Order {order_id}){f' [Original: {currency}]' if currency != 'EUR' else ''}",
    )


def _parse_transfer(row: dict) -> Transaction | None:
    tx_type = row.get("Transaktionen", "").strip()
    date = _parse_date(row["Datum"])
    btc_amount = Decimal(row["Anzahl"].strip())
    order_id = row.get("Auftrag #", "").strip()

    if tx_type == "Crypto Withdrawal":
        return Transaction(
            date=date,
            type=TxType.TRANSFER_OUT,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            source="swissquote",
            tx_id=f"swissquote-{order_id}",
            note="Swissquote BTC-Auszahlung an eigene Wallet",
        )
    elif tx_type == "Crypto Deposit":
        return Transaction(
            date=date,
            type=TxType.TRANSFER_IN,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            source="swissquote",
            tx_id=f"swissquote-{order_id}",
            note="Swissquote BTC-Eingang von eigener Wallet",
        )
    return None
