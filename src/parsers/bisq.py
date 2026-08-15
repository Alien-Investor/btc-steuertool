"""Parser für Bisq CSV-Exporte (deutschsprachig).

Format:
    Handels-ID,Datum/Zeit,Markt,Preis,Abweichung,Betrag in BTC,Betrag,Währung,
    Transaktionsgebühr,Handelsgebühr BTC,Handelsgebühr BSQ,Käufer-Kaution,
    Verkäufer-Kaution,Angebotstyp,Status

Relevante Zeilen:
    Angebotstyp="BTC kaufen" + Status="Abgeschlossen" → BUY, no_kyc=True

Gebühren:
    Transaktionsgebühr (BTC On-Chain-Fee) + Handelsgebühr BTC werden in EUR
    umgerechnet (Preis * Gebühr_BTC) und gehen als Anschaffungsnebenkosten in
    den Einstand ein (BMF 06.03.2025 Rn. 59). Zusätzlich reicht der Parser die
    Gebühr als fee_btc durch: die Sats sind aus dem Bestand abgeflossen, die
    Engine bucht dafür einen Gebühren-Abgang aus dem noKYC-Pool (H8).
    Handelsgebühr BSQ wird ignoriert.
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
    skipped: dict[tuple[str, int | None], int] = {}
    with open(filepath, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows_seen += 1
            tx = _parse_row(row, filepath.name, skipped)
            if tx is not None:
                transactions.append(tx)
    for (reason, year), count in sorted(skipped.items(), key=lambda kv: (kv[0][1] or 0, kv[0][0])):
        # Jahr mitfuehren, sonst taucht eine abgebrochene Zeile aus 2021 im
        # 2024er-Report auf und erzeugt dort einen internen Report (SA2-09)
        warn(f"{filepath.name}: {count} Zeile(n) {reason}", internal=True, year=year)
    if rows_seen and not transactions and not skipped:
        warn(
            f"{filepath.name}: keine Bisq-Transaktion erkannt ({rows_seen} Zeilen) — "
            f"englischsprachiger Export? Der Parser erwartet den deutschsprachigen Export.",
            internal=True,
        )
    return transactions


def _row_year(row: dict) -> int | None:
    """Steuerjahr einer Bisq-Zeile, tolerant — nur fuer die Jahres-Zuordnung
    von Warnungen. Bisq stempelt lokale Zeit, die als Europe/Berlin gilt."""
    raw = row.get("Datum/Zeit", "").strip()
    try:
        return datetime.strptime(raw, "%d.%m.%Y %H:%M:%S").year
    except (ValueError, TypeError):
        return None


def _parse_row(row: dict, filename: str, skipped: dict) -> Transaction | None:
    status = row.get("Status", "").strip()
    if status != "Abgeschlossen":
        # Nicht abgeschlossene Trades sind steuerlich irrelevant — aber mitzählen,
        # sonst greift der Sammel-Fallback bei teilweisem Verlust nicht.
        key = (f"mit Status '{status}' übersprungen", _row_year(row))
        skipped[key] = skipped.get(key, 0) + 1
        return None
    offer_type = row.get("Angebotstyp", "").strip()
    if offer_type != "BTC kaufen":
        # Nicht stillschweigend verwerfen — ein Verkauf wäre steuerlich relevant!
        if offer_type == "BTC verkaufen":
            warn(
                f"{filename}: Bisq-Verkauf am {row.get('Datum/Zeit', '?')} wird vom Parser "
                f"noch nicht unterstützt — bitte als manual_sales.csv (no_kyc=ja) erfassen, "
                f"sonst ist die noKYC-Übersicht unvollständig.",
                internal=True, year=_row_year(row),
            )
        else:
            key = (f"mit Angebotstyp '{offer_type}' nicht verarbeitet", _row_year(row))
            skipped[key] = skipped.get(key, 0) + 1
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
            internal=True, year=date.year,
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
        fee_btc=fee_btc,
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
