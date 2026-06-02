"""Parser für Bisq CSV-Exporte (deutschsprachig).

Format:
    Handels-ID,Datum/Zeit,Markt,Preis,Abweichung,Betrag in BTC,Betrag,Währung,
    Transaktionsgebühr,Handelsgebühr BTC,Handelsgebühr BSQ,Käufer-Kaution,
    Verkäufer-Kaution,Angebotstyp,Status

Relevante Zeilen:
    Angebotstyp="BTC kaufen" + Status="Abgeschlossen" → BUY, no_kyc=True

Gebühren:
    Transaktionsgebühr (BTC On-Chain-Fee) + Handelsgebühr BTC werden in EUR
    umgerechnet (Preis * Gebühr_BTC). Handelsgebühr BSQ wird ignoriert.
    Sicherheitskautionen (Kaution) sind keine Gebühren — werden zurückgegeben.

Timestamps:
    Bisq exportiert lokale Systemzeit ohne Timezone-Angabe.
    Wird als UTC behandelt (±1-2h Abweichung irrelevant für Tagesberechnung).
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
        for row in reader:
            tx = _parse_row(row)
            if tx is not None:
                transactions.append(tx)
    return transactions


def _parse_row(row: dict) -> Transaction | None:
    if row.get("Status", "").strip() != "Abgeschlossen":
        return None
    if row.get("Angebotstyp", "").strip() != "BTC kaufen":
        return None

    trade_id = row.get("Handels-ID", "").strip()
    date_str = row.get("Datum/Zeit", "").strip()
    date = datetime.strptime(date_str, "%d.%m.%Y %H:%M:%S").replace(tzinfo=timezone.utc)

    btc_amount = _decimal(row.get("Betrag in BTC", "0"))
    eur_amount = _decimal(row.get("Betrag", "0"))
    eur_price_per_btc = _decimal(row.get("Preis", "0"))

    # Gebühren in BTC → EUR umrechnen (Kautionen sind keine Gebühren)
    fee_btc = _decimal(row.get("Transaktionsgebühr", "0")) + _decimal(row.get("Handelsgebühr BTC", "0"))
    fee_eur = _round(fee_btc * eur_price_per_btc) if eur_price_per_btc else Decimal("0")

    return Transaction(
        date=date,
        type=TxType.BUY,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=fee_eur,
        source="bisq",
        tx_id=trade_id,
        note="Bisq P2P Kauf",
        no_kyc=True,
    )


def _decimal(value: str) -> Decimal:
    val = value.strip().replace(",", ".")
    return Decimal(val) if val else Decimal("0")


def _round(val: Decimal) -> Decimal:
    from decimal import ROUND_HALF_UP
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
