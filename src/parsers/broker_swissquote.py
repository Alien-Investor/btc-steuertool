"""Parser für Swissquote CSV-Exporte.

Kopfzeile (Semikolon, Windows-1252 — eine als UTF-8 gespeicherte Kopie wird ebenfalls
gelesen; Pflichtspalten hart geprüft, Audit 03.10.2026):
    Datum;Auftrag #;Transaktionen;Symbol;Name;ISIN;Anzahl;Stückpreis;Kosten;
    Aufgelaufene Zinsen;Nettobetrag;Saldo;Währung
"""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from collections import defaultdict

from ..models import Transaction, TxType, TZ_DE
from ..fx_rates import eur_rate_for_date
from . import FileRef, warn, warn_fmt, read_rows, amount, LINE_KEY

LABEL = "Swissquote"
REQUIRED = ("Datum", "Auftrag #", "Transaktionen", "Symbol", "Anzahl", "Stückpreis", "Kosten", "Währung")


def parse(filepath: Path) -> list[Transaction]:
    # Encoding: Swissquote exportiert Windows-1252. UTF-8 zuerst probieren: eine in
    # einem Editor neu gespeicherte Datei scheiterte sonst mit KeyError 'Stückpreis'
    # (B2) — cp1252 dekodiert jedes Byte, nur eben zu „StÃ¼ckpreis".
    rows, _ = read_rows(filepath, label=LABEL, required=REQUIRED, delimiter=";",
                        encodings=("utf-8-sig", "windows-1252"))

    # Kauf-Zeilen mit gleicher Auftragsnummer zusammenfassen
    orders: dict[str, list[dict]] = defaultdict(list)
    other_rows: list[dict] = []

    for row in rows:
        tx_type = row.get("Transaktionen", "")
        order_id = row.get("Auftrag #", "")
        symbol = row.get("Symbol", "").upper()

        if symbol != "BTC":
            continue  # nur BTC relevant

        if tx_type == "Kauf":
            if order_id:
                orders[order_id].append(row)
            else:
                warn_fmt("{file}: Kauf-Zeile vom {datum} ohne Auftragsnummer nicht verarbeitet.",
                         internal=False, file=FileRef(filepath.name), datum=row.get('Datum', '?'),
                         year=_year(row, filepath.name))
        elif tx_type in ("Crypto Withdrawal", "Crypto Deposit"):
            other_rows.append(row)
        elif tx_type == "Verkauf":
            # Nicht stillschweigend verwerfen — Verkauf ist steuerlich relevant!
            warn(
                f"{filepath.name}: BTC-Verkauf vom {row.get('Datum', '?')} wird vom "
                f"Swissquote-Parser noch nicht unterstützt — bitte als manual_sales.csv "
                f"erfassen, sonst ist der Report unvollständig.", internal=False,
                year=_year(row, filepath.name),
            )
        else:
            warn_fmt("{file}: unbekannter Transaktionstyp '{typ}' vom {datum} nicht verarbeitet.",
                     internal=False, file=FileRef(filepath.name), typ=tx_type, datum=row.get('Datum', '?'),
                     year=_year(row, filepath.name))

    transactions = []

    # Käufe (ggf. mehrere Teilausführungen pro Order zusammenfassen)
    for order_id, order_rows in orders.items():
        tx = _merge_buy_rows(order_id, order_rows, filepath.name)
        if tx is not None:
            transactions.append(tx)

    # Withdrawals & Deposits
    for row in other_rows:
        tx = _parse_transfer(row, filepath.name)
        if tx is not None:
            transactions.append(tx)

    return transactions


def _parse_date(date_str: str, filename: str, line) -> datetime:
    # Format: "DD-MM-YYYY HH:MM:SS" — Swissquote exportiert Schweizer Lokalzeit
    # ohne Timezone-Angabe. CH und DE teilen die Zeitzone (CET/CEST), darum als
    # Europe/Berlin stempeln — so stimmt das Kalenderdatum für Steuerjahr/Haltefrist
    # auch bei Abend-Transaktionen (als UTC gestempelt wäre es um 1-2h verschoben).
    try:
        return datetime.strptime(date_str.strip(), "%d-%m-%Y %H:%M:%S").replace(tzinfo=TZ_DE)
    except ValueError:
        raise ValueError(
            f"{LABEL} {filename} Zeile {line}: Datum '{date_str}' nicht lesbar (erwartet TT-MM-JJJJ HH:MM:SS)."
        ) from None


def _year(row: dict, filename: str) -> int | None:
    try:
        return _parse_date(row.get("Datum", ""), filename, row.get(LINE_KEY, "?")).year
    except ValueError:
        return None


def _currency(row: dict, filename: str) -> str:
    # Keine EUR-Vorgabe mehr (A3): eine leere Währungsspalte buchte einen
    # USD-Kauf still als EUR — Betrag ohne Umrechnung, keine Warnung.
    currency = row.get("Währung", "").upper()
    if not currency:
        raise ValueError(f"{LABEL} {filename} Zeile {row.get(LINE_KEY, '?')}: Spalte 'Währung' ist leer.")
    return currency


def _merge_buy_rows(order_id: str, rows: list[dict], filename: str = "Swissquote") -> Transaction | None:
    """Fasst mehrere Teilausführungen einer Order zu einer Transaktion zusammen."""
    if not rows:
        return None

    # Datum der ersten Teilausführung.
    # Teilausführungen einer Order liegen dicht beieinander. Spannen die Zeilen
    # mehr als einen Tag, ist die Auftragsnummer mehrfach vergeben (oder die
    # Datei manipuliert) — dann würde das Lot ein falsches Anschaffungsdatum
    # erben und die Haltefrist kippen. Lieber melden als still zusammenfassen.
    dates = [_parse_date(r["Datum"], filename, r[LINE_KEY]) for r in rows]
    if (max(dates) - min(dates)).days > 1:
        warn(
            f"{filename}: Order {order_id} enthält Zeilen von {min(dates).date()} "
            f"bis {max(dates).date()} — nicht zusammengefasst, bitte prüfen.", internal=False,
            year=min(dates).year,
        )
        return None
    date = min(dates)
    currency = _currency(rows[0], filename)

    total_btc = Decimal("0")
    total_cost = Decimal("0")  # Betrag in Originalwährung (ohne Gebühren)
    total_fee = Decimal("0")   # in Originalwährung

    for row in rows:
        btc = amount(row, "Anzahl", label=LABEL, filename=filename)
        price = amount(row, "Stückpreis", label=LABEL, filename=filename)
        fee = amount(row, "Kosten", label=LABEL, filename=filename)
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


def _parse_transfer(row: dict, filename: str) -> Transaction | None:
    tx_type = row.get("Transaktionen", "")
    date = _parse_date(row["Datum"], filename, row[LINE_KEY])
    btc_amount = amount(row, "Anzahl", label=LABEL, filename=filename)
    order_id = row.get("Auftrag #", "")

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
