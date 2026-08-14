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
    Wird als Europe/Berlin behandelt — maßgeblich für Steuerjahr und Haltefrist
    ist das deutsche Kalenderdatum.
"""
from __future__ import annotations
import csv
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, TZ_DE
from . import warn


def parse(filepath: Path) -> list[Transaction]:
    transactions = []
    rows_seen = 0
    skipped: dict[str, int] = {}
    with open(filepath, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows_seen += 1
            tx = _parse_row(row, filepath.name, skipped)
            if tx is not None:
                transactions.append(tx)
    for reason, count in skipped.items():
        warn(f"{filepath.name}: {count} Zeile(n) {reason}", internal=True)
    if rows_seen and not transactions and not skipped:
        warn(
            f"{filepath.name}: keine Bisq-Transaktion erkannt ({rows_seen} Zeilen) — "
            f"englischsprachiger Export? Der Parser erwartet den deutschsprachigen Export.",
            internal=True,
        )
    return transactions


def _parse_row(row: dict, filename: str, skipped: dict[str, int]) -> Transaction | None:
    status = row.get("Status", "").strip()
    if status != "Abgeschlossen":
        # Nicht abgeschlossene Trades sind steuerlich irrelevant — aber mitzählen,
        # sonst greift der Sammel-Fallback bei teilweisem Verlust nicht.
        skipped[f"mit Status '{status}' übersprungen"] = (
            skipped.get(f"mit Status '{status}' übersprungen", 0) + 1
        )
        return None
    offer_type = row.get("Angebotstyp", "").strip()
    if offer_type != "BTC kaufen":
        # Nicht stillschweigend verwerfen — ein Verkauf wäre steuerlich relevant!
        if offer_type == "BTC verkaufen":
            warn(
                f"{filename}: Bisq-Verkauf am {row.get('Datum/Zeit', '?')} wird vom Parser "
                f"noch nicht unterstützt — bitte als manual_sales.csv (no_kyc=ja) erfassen, "
                f"sonst ist die noKYC-Übersicht unvollständig.",
                internal=True,
            )
        else:
            reason = f"mit Angebotstyp '{offer_type}' nicht verarbeitet"
            skipped[reason] = skipped.get(reason, 0) + 1
        return None

    trade_id = row.get("Handels-ID", "").strip()
    date_str = row.get("Datum/Zeit", "").strip()
    # Bisq exportiert lokale Systemzeit ohne Timezone — als Europe/Berlin stempeln,
    # damit das Kalenderdatum für Steuerjahr/Haltefrist stimmt.
    date = datetime.strptime(date_str, "%d.%m.%Y %H:%M:%S").replace(tzinfo=TZ_DE)

    currency = row.get("Währung", "").strip().upper()
    if currency and currency != "EUR":
        warn(
            f"{filename}: Bisq-Trade {trade_id} in {currency} statt EUR — nicht verarbeitet. "
            f"Bitte als manual_buys.csv mit EUR-Umrechnung zum Kaufdatum erfassen.",
            internal=True,
        )
        return None

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
