"""Parser für Strike CSV-Exporte.

Format (Pflichtspalten hart geprüft, Audit 03.10.2026):
    Transaction ID,Time (UTC),Status,Transaction Type,Amount EUR,Fee EUR,
    Amount BTC,Fee BTC,Description,Exchange Rate,Transaction Hash

Transaktionstypen:
    Purchase  — BTC-Kauf, Amount EUR ist negativ (Betrag den man zahlt)
    Send      — BTC-Auszahlung an eigene Wallet (TRANSFER_OUT)
    Receive   — BTC-Eingang ohne EUR-Gegenwert (z.B. Trinkgeld), TRANSFER_IN
    Deposit   — EUR-Einzahlung, irrelevant
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, de_date
from . import FileRef, warn_fmt, read_rows, amount, LINE_KEY

LABEL = "Strike"
REQUIRED = ("Transaction ID", "Time (UTC)", "Status", "Transaction Type", "Amount EUR", "Fee EUR",
            "Amount BTC", "Fee BTC", "Exchange Rate", "Transaction Hash")


def parse(filepath: Path) -> list[Transaction]:
    transactions = []
    rows, _ = read_rows(filepath, label=LABEL, required=REQUIRED)
    for row in rows:
        tx = _parse_row(row, filepath.name)
        if tx is not None:
            transactions.append(tx)
    return transactions


def _parse_date(date_str: str, filename: str, line) -> datetime:
    # Datum: "Jun 24 2025 21:59:51" UTC — englische Monatskürzel, unabhängig von
    # der Systemsprache (strptime %b hängt an der C-Locale, die Python nicht setzt)
    try:
        return datetime.strptime(date_str, "%b %d %Y %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError(
            f"{LABEL} {filename} Zeile {line}: Zeit '{date_str}' nicht lesbar (erwartet z.B. 'Jun 24 2025 21:59:51')."
        ) from None


def _parse_row(row: dict, filename: str) -> Transaction | None:
    line = row[LINE_KEY]
    date_str = row.get("Time (UTC)", "")
    status = row.get("Status", "")
    tx_type_raw = row.get("Transaction Type", "")
    if status != "Completed":
        # Nur abgeschlossene Vorgänge zählen — aber nicht stillschweigend
        # verwerfen: Purchase/Send/Receive sind steuerlich relevant.
        if tx_type_raw in ("Purchase", "Send", "Receive"):
            year, tag = None, "?"
            try:
                tag = de_date(_parse_date(date_str, filename, line))
                year = tag.year
            except ValueError:
                pass
            # Datum als deutsches Kalenderdatum, nicht die Rohzelle (Audit v1.4, R3-B7)
            warn_fmt(
                "{file}: {typ} vom {zeit} mit Status '{status}' nicht verarbeitet.",
                internal=False, file=FileRef(filename), year=year,
                typ=tx_type_raw, zeit=tag, status=status,
            )
        return None

    date = _parse_date(date_str, filename, line)

    tx_id = row.get("Transaction ID", "")
    tx_hash = row.get("Transaction Hash", "")
    description = row.get("Description", "")

    def num(field: str) -> Decimal:
        return amount(row, field, label=LABEL, filename=filename)

    if tx_type_raw == "Purchase":
        # Amount EUR ist negativ (gezahlter Betrag) → abs nehmen
        eur_amount = abs(num("Amount EUR"))
        fee_eur = num("Fee EUR")
        btc_amount = num("Amount BTC")
        rate = num("Exchange Rate")
        eur_price_per_btc = rate if rate else (
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
        btc_amount = abs(num("Amount BTC"))
        # Netzwerkgebühr in BTC: in Amount BTC ENTHALTEN (echter Export, Abgleich
        # mit dem BitBox-Eingang derselben TX-ID: Amount = Eingang + Fee BTC).
        # Getrennt buchen wie bei der BitBox: btc_amount = übertragener Betrag,
        # fee_btc = Veräußerung des Gebührenanteils (H8). Bis 10/2026 fiel die
        # Gebühr stillschweigend weg.
        fee_btc = abs(num("Fee BTC"))
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
        btc_amount = num("Amount BTC")

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
