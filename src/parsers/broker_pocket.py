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
from ..fx_rates import eur_rate_for_date
from . import warn

FIAT = ("EUR", "CHF", "USD")


def _to_eur(amount: Decimal, price: Decimal, currency: str, date) -> tuple[Decimal, Decimal]:
    """Rechnet Betrag + Stückpreis in EUR um (Pocket bucht CH-Käufe oft in CHF)."""
    currency = (currency or "EUR").upper()
    if currency == "EUR":
        return amount, price
    rate = eur_rate_for_date(date.date(), currency)
    return amount * rate, price * rate


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

        # Deposit-Zeile mit gleichem Zeitstempel (Minute) suchen.
        # i-1 ZUERST: Pocket exportiert deposit / exchange / withdrawal, die
        # echte deposit-Zeile steht also davor. Passen mehrere Zeilen, ist die
        # Zuordnung nicht eindeutig — dann lieber melden als raten, sonst
        # bestimmt eine eingeschmuggelte Zeile Preis oder Menge des Trades.
        exchange_ts = row["date"][:16]
        candidates = [
            rows[j] for j in (i - 1, i + 1, i - 2, i + 2)
            if 0 <= j < len(rows)
            and rows[j].get("type") == "deposit"
            and rows[j]["date"][:16] == exchange_ts
        ]
        if len(candidates) > 1:
            warn(
                f"{filepath.name}: mehrere deposit-Zeilen zur exchange-Zeile "
                f"{exchange_ts} — Zuordnung nicht eindeutig, Trade NICHT verarbeitet."
            )
            continue
        deposit = candidates[0] if candidates else None

        cost_currency = row.get("cost.currency", "").upper()
        if cost_currency == "BTC":
            tx = _parse_sell(row, deposit)
        elif cost_currency in FIAT:
            tx = _parse_buy(row, deposit)
        else:
            # Nicht stillschweigend verwerfen — jede exchange-Zeile ist ein Trade
            warn(f"{filepath.name}: exchange-Zeile am {row.get('date', '?')} mit cost.currency '{cost_currency}' nicht verarbeitet.")
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

    # Fiat netto erhalten (Gebühr wurde in BTC abgezogen, nicht in Fiat)
    recv_currency = exchange.get("value.currency", "").upper()
    recv = _d(exchange["value.amount"])
    price = _d(exchange.get("price.amount", "0"))
    eur_amount, eur_price_per_btc = _to_eur(recv, price, recv_currency, date)
    note = "Pocket Verkauf" + (f" [Original: {recv_currency}]" if recv_currency not in ("EUR", "") else "")

    return Transaction(
        date=date,
        type=TxType.SELL,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=Decimal("0"),  # Gebühr in BTC abgezogen, bereits in eur_amount reflektiert
        source="pocket",
        # Betrag im Schlüssel: zwei Trades in derselben Sekunde bleiben unterscheidbar
        tx_id=f"pocket-{exchange['date']}-{exchange.get('value.amount', '')}",
        note=note,
    )


def _parse_buy(exchange: dict, deposit: dict | None) -> Transaction | None:
    """EUR → BTC: Nutzer zahlt EUR, bekommt BTC in die Wallet."""
    date = _parse_date(exchange["date"])

    # BTC-Menge: was Pocket für den Nutzer gekauft hat
    btc_amount = _d(exchange["value.amount"])

    # Gesamtbetrag bezahlt (Originalwährung): bevorzugt deposit-Zeile, sonst cost + fee
    cost_currency = exchange.get("cost.currency", "").upper()
    if deposit and _d(deposit.get("value.amount", "0")) > 0:
        paid = _d(deposit["value.amount"])
        paid_currency = (deposit.get("value.currency", "") or cost_currency).upper()
    else:
        paid = _d(exchange["cost.amount"]) + _d(exchange.get("fee.amount", "0"))
        paid_currency = cost_currency

    price = _d(exchange.get("price.amount", "0"))
    eur_amount, eur_price_per_btc = _to_eur(paid, price, paid_currency, date)
    note = "Pocket Kauf" + (f" [Original: {paid_currency}]" if paid_currency not in ("EUR", "") else "")

    return Transaction(
        date=date,
        type=TxType.BUY,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=Decimal("0"),  # Gebühr in eur_amount enthalten
        source="pocket",
        # Betrag im Schlüssel: zwei Trades in derselben Sekunde bleiben unterscheidbar
        tx_id=f"pocket-{exchange['date']}-{exchange.get('value.amount', '')}",
        note=note,
    )


def _parse_date(date_str: str) -> datetime:
    # Format: "2025-08-14T19:10:57.000Z" — Millisekunden abschneiden, UTC
    return datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def _d(value: str) -> Decimal:
    val = value.strip().replace(",", ".")
    return Decimal(val) if val else Decimal("0")
