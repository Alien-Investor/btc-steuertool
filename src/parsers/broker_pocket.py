"""Parser für Pocket Bitcoin CSV-Exporte.

Pocket-Transaktionen bestehen aus Dreier-Gruppen (deposit/exchange/withdrawal).
Wir identifizieren den zentralen 'exchange'-Eintrag und lesen BTC-Menge
sowie EUR-Betrag aus den benachbarten Zeilen mit gleichem Zeitstempel.

Relevante exchange-Typen:
  - cost.currency=BTC → BTC-Verkauf (BTC → EUR)
  - cost.currency=EUR → BTC-Kauf (EUR → BTC)
"""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType


def parse(filepath: Path) -> list[Transaction]:
    rows = []
    with open(filepath, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k.strip(): v.strip() for k, v in row.items()})

    transactions = []
    for i, row in enumerate(rows):
        if row.get("type") != "exchange":
            continue

        # Deposit-Zeile mit gleichem Zeitstempel (Minute) suchen
        exchange_ts = row["date"][:16]
        deposit = None
        for j in [i + 1, i - 1, i + 2, i - 2]:
            if 0 <= j < len(rows) and rows[j].get("type") == "deposit":
                if rows[j]["date"][:16] == exchange_ts:
                    deposit = rows[j]
                    break

        cost_currency = row.get("cost.currency", "").upper()
        if cost_currency == "BTC":
            tx = _parse_sell(row, deposit)
        elif cost_currency == "EUR":
            tx = _parse_buy(row, deposit)
        else:
            continue

        if tx:
            transactions.append(tx)

    return transactions


def _parse_sell(exchange: dict, deposit: dict | None) -> Transaction | None:
    """BTC → EUR: Nutzer schickt BTC an Pocket, bekommt EUR ausgezahlt."""
    date = _parse_date(exchange["date"])

    # BTC-Menge: was aus der Wallet gesendet wurde (deposit bei Pocket)
    if deposit and deposit.get("value.currency", "").upper() == "BTC":
        btc_amount = _d(deposit["value.amount"])
    else:
        # Fallback: BTC aus exchange + Gebühr in BTC zurückrechnen
        btc_net = _d(exchange["cost.amount"])
        fee_eur = _d(exchange.get("fee.amount", "0"))
        price = _d(exchange.get("price.amount", "0"))
        fee_btc = fee_eur / price if price else Decimal("0")
        btc_amount = btc_net + fee_btc

    # EUR netto erhalten (Gebühr wurde in BTC abgezogen, nicht in EUR)
    eur_amount = _d(exchange["value.amount"])
    eur_price_per_btc = _d(exchange.get("price.amount", "0"))

    return Transaction(
        date=date,
        type=TxType.SELL,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=Decimal("0"),  # Gebühr in BTC abgezogen, bereits in eur_amount reflektiert
        source="pocket",
        tx_id=f"pocket-{exchange['date']}",
        note="Pocket Verkauf",
    )


def _parse_buy(exchange: dict, deposit: dict | None) -> Transaction | None:
    """EUR → BTC: Nutzer zahlt EUR, bekommt BTC in die Wallet."""
    date = _parse_date(exchange["date"])

    # BTC-Menge: was Pocket für den Nutzer gekauft hat
    btc_amount = _d(exchange["value.amount"])

    # EUR bezahlt gesamt (aus deposit-Zeile oder cost + fee)
    if deposit and deposit.get("value.currency", "").upper() == "EUR":
        eur_amount = _d(deposit["value.amount"])
    else:
        eur_amount = _d(exchange["cost.amount"]) + _d(exchange.get("fee.amount", "0"))

    eur_price_per_btc = _d(exchange.get("price.amount", "0"))

    return Transaction(
        date=date,
        type=TxType.BUY,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=Decimal("0"),  # Gebühr in eur_amount enthalten
        source="pocket",
        tx_id=f"pocket-{exchange['date']}",
        note="Pocket Kauf",
    )


def _parse_date(date_str: str) -> datetime:
    # Format: "2025-08-14T19:10:57.000Z" — Millisekunden abschneiden, UTC
    return datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _d(value: str) -> Decimal:
    val = value.strip().replace(",", ".")
    return Decimal(val) if val else Decimal("0")
