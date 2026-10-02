"""Parser für Pocket Bitcoin CSV-Exporte.

Pocket-Transaktionen bestehen aus Dreier-Gruppen (deposit/exchange/withdrawal).
Wir identifizieren den zentralen 'exchange'-Eintrag und lesen BTC-Menge
sowie EUR-Betrag aus den benachbarten Zeilen mit gleichem Zeitstempel.

Relevante exchange-Typen:
  - cost.currency=BTC → BTC-Verkauf (BTC → EUR)
  - cost.currency=EUR → BTC-Kauf (EUR → BTC)

Kopfzeile (Pflichtspalten hart geprüft, Audit 03.10.2026):
    type,date,value.currency,value.amount,cost.currency,cost.amount,fee.currency,fee.amount,price.amount
"""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, de_date
from ..fx_rates import eur_rate_for_date
from . import FileRef, warn, warn_fmt, read_rows, amount, parse_iso_datetime, LINE_KEY

LABEL = "Pocket"
REQUIRED = ("type", "date", "value.currency", "value.amount", "cost.currency", "cost.amount",
            "fee.currency", "fee.amount", "price.amount")
FIAT = ("EUR", "CHF", "USD")


def _to_eur(amount_: Decimal, price: Decimal, currency: str, date, filename: str, line) -> tuple[Decimal, Decimal]:
    """Rechnet Betrag + Stückpreis in EUR um (Pocket bucht CH-Käufe oft in CHF).

    Keine EUR-Vorgabe bei leerer Währung (A3): ein CHF-Betrag würde sonst still
    als EUR gebucht.
    """
    currency = (currency or "").upper()
    if not currency:
        raise ValueError(f"{LABEL} {filename} Zeile {line}: Währung der exchange-Zeile ist leer.")
    if currency == "EUR":
        return amount_, price
    rate = eur_rate_for_date(date.date(), currency)
    return amount_ * rate, price * rate


def parse(filepath: Path) -> list[Transaction]:
    rows, _ = read_rows(filepath, label=LABEL, required=REQUIRED)
    filename = filepath.name

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
        date = _parse_date(row["date"], filename, row[LINE_KEY])
        if len(candidates) > 1:
            warn(
                f"{filename}: mehrere deposit-Zeilen zur exchange-Zeile "
                f"{exchange_ts} — Zuordnung nicht eindeutig, Trade NICHT verarbeitet.", internal=False,
                year=de_date(date).year,
            )
            continue
        deposit = candidates[0] if candidates else None

        cost_currency = row.get("cost.currency", "").upper()
        if cost_currency == "BTC":
            tx = _parse_sell(row, deposit, date, filename)
        elif cost_currency in FIAT:
            tx = _parse_buy(row, deposit, date, filename)
        else:
            # Nicht stillschweigend verwerfen — jede exchange-Zeile ist ein Trade
            warn_fmt("{file}: exchange-Zeile am {datum} mit cost.currency '{cur}' nicht verarbeitet.",
                     internal=False, file=FileRef(filename), datum=row.get('date', '?'), cur=cost_currency,
                     year=de_date(date).year)
            continue

        if tx:
            transactions.append(tx)

    return transactions


def _num(row: dict, field: str, filename: str) -> Decimal:
    return amount(row, field, label=LABEL, filename=filename)


def _parse_sell(exchange: dict, deposit: dict | None, date: datetime, filename: str) -> Transaction | None:
    """BTC → EUR: Nutzer schickt BTC an Pocket, bekommt EUR ausgezahlt."""
    line = exchange[LINE_KEY]

    # BTC-Menge: was aus der Wallet gesendet wurde (deposit bei Pocket)
    if deposit and deposit.get("value.currency", "").upper() == "BTC":
        btc_amount = _num(deposit, "value.amount", filename)
    else:
        # Fallback: BTC aus exchange + Gebühr in BTC zurückrechnen
        btc_net = _num(exchange, "cost.amount", filename)
        fee_eur = _num(exchange, "fee.amount", filename)
        price = _num(exchange, "price.amount", filename)
        fee_btc = fee_eur / price if price else Decimal("0")
        btc_amount = btc_net + fee_btc

    # Fiat netto erhalten (Gebühr wurde in BTC abgezogen, nicht in Fiat)
    recv_currency = exchange.get("value.currency", "").upper()
    recv = _num(exchange, "value.amount", filename)
    price = _num(exchange, "price.amount", filename)
    eur_amount, eur_price_per_btc = _to_eur(recv, price, recv_currency, date, filename, line)
    note = "Pocket Verkauf" + (f" [Original: {recv_currency}]" if recv_currency not in ("EUR", "") else "")

    return Transaction(
        date=date,
        type=TxType.SELL,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=Decimal("0"),  # Gebühr in BTC abgezogen, bereits in eur_amount reflektiert
        source="pocket",
        direct=True,  # Pocket hält keinen Bestand: Lieferung an / Verkauf aus eigener Wallet
        # Betrag im Schlüssel: zwei Trades in derselben Sekunde bleiben unterscheidbar
        tx_id=f"pocket-{exchange['date']}-{exchange.get('value.amount', '')}",
        note=note,
    )


def _parse_buy(exchange: dict, deposit: dict | None, date: datetime, filename: str) -> Transaction | None:
    """EUR → BTC: Nutzer zahlt EUR, bekommt BTC in die Wallet."""
    line = exchange[LINE_KEY]

    # BTC-Menge: was Pocket für den Nutzer gekauft hat
    btc_amount = _num(exchange, "value.amount", filename)

    # Gesamtbetrag bezahlt (Originalwährung): bevorzugt deposit-Zeile, sonst cost + fee
    cost_currency = exchange.get("cost.currency", "").upper()
    if deposit and _num(deposit, "value.amount", filename) > 0:
        paid = _num(deposit, "value.amount", filename)
        paid_currency = (deposit.get("value.currency", "") or cost_currency).upper()
    else:
        paid = _num(exchange, "cost.amount", filename) + _num(exchange, "fee.amount", filename)
        paid_currency = cost_currency

    price = _num(exchange, "price.amount", filename)
    eur_amount, eur_price_per_btc = _to_eur(paid, price, paid_currency, date, filename, line)
    note = "Pocket Kauf" + (f" [Original: {paid_currency}]" if paid_currency not in ("EUR", "") else "")

    return Transaction(
        date=date,
        type=TxType.BUY,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=Decimal("0"),  # Gebühr in eur_amount enthalten
        source="pocket",
        direct=True,  # Pocket hält keinen Bestand: Lieferung an / Verkauf aus eigener Wallet
        # Betrag im Schlüssel: zwei Trades in derselben Sekunde bleiben unterscheidbar
        tx_id=f"pocket-{exchange['date']}-{exchange.get('value.amount', '')}",
        note=note,
    )


def _parse_date(date_str: str, filename: str, line) -> datetime:
    # Format: "2025-08-14T19:10:57.000Z" — ISO 8601 mit Zeitzone. Bisher wurde mit
    # [:19] jeder Offset abgeschnitten und UTC angenommen (C4); jetzt zählt der
    # Offset, und ohne Offset ist es ein Fehler.
    return parse_iso_datetime(date_str, label=LABEL, filename=filename, line=line, field="date")
