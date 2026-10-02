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

from ..models import Transaction, TxType, de_date
from . import FileRef, warn, warn_fmt


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
            warn_fmt(
                "{file}: {typ} vom {zeit} mit Status '{status}' nicht verarbeitet.",
                internal=False, file=FileRef(filename),
                typ=row.get('Transaction Type', '').strip(), zeit=row.get('Time (UTC)', '?'), status=status,
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
        # Netzwerkgebühr in BTC: in Amount BTC ENTHALTEN (echter Export, Abgleich
        # mit dem BitBox-Eingang derselben TX-ID: Amount = Eingang + Fee BTC).
        # Getrennt buchen wie bei der BitBox: btc_amount = übertragener Betrag,
        # fee_btc = Veräußerung des Gebührenanteils (H8). Bis 10/2026 fiel die
        # Gebühr stillschweigend weg.
        fee_btc = abs(_decimal(row.get("Fee BTC", "")))
        if fee_btc > btc_amount:
            warn_fmt("{file}: Auszahlung am {tag} mit Gebühr {fee} BTC über dem Betrag {menge} BTC — "
                     "Gebühr nicht verarbeitet.", internal=False, year=de_date(date).year,
                     file=FileRef(filename), tag=de_date(date), fee=fee_btc, menge=btc_amount)
            fee_btc = Decimal("0")
        btc_amount -= fee_btc

        return Transaction(
            date=date,
            type=TxType.TRANSFER_OUT,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            fee_btc=fee_btc,
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
        warn_fmt("{file}: unbekannter Transaktionstyp '{typ}' am {tag} nicht verarbeitet.",
                 internal=False, year=de_date(date).year, file=FileRef(filename),
                 typ=tx_type_raw, tag=de_date(date))
    return None


def _decimal(value: str) -> Decimal:
    val = value.strip().replace(",", ".")
    return Decimal(val) if val else Decimal("0")
