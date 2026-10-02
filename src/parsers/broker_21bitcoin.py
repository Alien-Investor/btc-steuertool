"""Parser für 21bitcoin CSV-Exporte.

Kopfzeile (Pflichtspalten hart geprüft, Audit 03.10.2026):
    id,exchange_name,depot_name,transaction_date,buy_asset,buy_amount,sell_asset,
    sell_amount,fee_asset,fee_amount,transaction_type,note,linked_transaction
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, de_date
from . import warn_fmt, FileRef, read_rows, amount, LINE_KEY

LABEL = "21bitcoin"
REQUIRED = ("id", "transaction_date", "transaction_type", "buy_asset", "buy_amount",
            "sell_asset", "sell_amount", "fee_asset", "fee_amount")


def parse(filepath: Path) -> list[Transaction]:
    transactions = []
    rows, _ = read_rows(filepath, label=LABEL, required=REQUIRED)
    for row in rows:
        tx = _parse_row(row, filepath.name)
        if tx is not None:
            transactions.append(tx)
    return transactions


def _parse_row(row: dict, filename: str) -> Transaction | None:
    tx_type_raw = row["transaction_type"].lower()
    line = row[LINE_KEY]

    # Datum: "DD.MM.YYYY HH:MM:SS" — 21bitcoin gibt keine Timezone an,
    # laut Support handelt es sich um UTC
    date_str = row["transaction_date"]
    try:
        date = datetime.strptime(date_str, "%d.%m.%Y %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError(
            f"{LABEL} {filename} Zeile {line}: Datum '{date_str}' nicht lesbar (erwartet TT.MM.JJJJ HH:MM:SS)."
        ) from None

    note = row.get("note", "")
    row_id = row.get("id", "")

    def num(field: str) -> Decimal:
        return amount(row, field, label=LABEL, filename=filename)

    if tx_type_raw == "trade":
        # BTC-Kauf: buy_asset=BTC, sell_asset=EUR
        buy_asset = row.get("buy_asset", "").upper()
        sell_asset = row.get("sell_asset", "").upper()
        if buy_asset != "BTC" or sell_asset != "EUR":
            # Nicht stillschweigend verwerfen — ein BTC-Verkauf wäre steuerlich relevant!
            if sell_asset == "BTC":
                # manual_sales.csv ist unser eigener Textbaustein und bleibt stehen —
                # redigiert wird nur der eingesetzte Dateiname (SA2-06)
                warn_fmt(
                    "{file}: BTC-Verkauf am {tag} wird vom 21bitcoin-Parser "
                    "noch nicht unterstützt — bitte als manual_sales.csv erfassen, "
                    "sonst ist der Report unvollständig.",
                    file=FileRef(filename), tag=de_date(date), year=de_date(date).year, internal=False,
                )
            else:
                warn_fmt(
                    "{file}: Trade-Zeile mit {a}→{b} nicht verarbeitet.",
                    file=FileRef(filename), a=sell_asset, b=buy_asset, year=de_date(date).year, internal=False,
                )
            return None

        btc_amount = num("buy_amount")
        eur_amount = num("sell_amount")
        fee_eur = num("fee_amount")
        eur_price_per_btc = eur_amount / btc_amount if btc_amount else Decimal("0")

        return Transaction(
            date=date,
            type=TxType.BUY,
            btc_amount=btc_amount,
            eur_amount=eur_amount,
            eur_price_per_btc=eur_price_per_btc,
            fee_eur=fee_eur,
            source="21bitcoin",
            tx_id=f"21btc-{row_id}",
            note=note,
        )

    elif tx_type_raw == "withdrawal":
        # BTC-Auszahlung an eigene Wallet
        sell_asset = row.get("sell_asset", "").upper()
        if sell_asset != "BTC":
            # EUR/CHF-Auszahlungen sind bekannt irrelevant und bleiben stumm.
            # Alles andere melden: benennt 21bitcoin die Spalte je um, liefert
            # row.get() "" und JEDE Auszahlung verschwaende sonst lautlos,
            # waehrend die trade-Zweige weiter warnen (SA2-11).
            if sell_asset not in ("EUR", "CHF"):
                warn_fmt(
                    "{file}: Auszahlung am {tag} mit sell_asset='{asset}' nicht "
                    "verarbeitet — erwartet wird BTC.",
                    file=FileRef(filename), tag=de_date(date), asset=sell_asset,
                    year=de_date(date).year, internal=False,
                )
            return None

        btc_amount = num("sell_amount")
        # Auszahlungsgebühr in BTC: geht an den Broker als Entgelt für die
        # Auszahlung — Tausch gegen Dienstleistung, also Veräußerung des
        # Gebührenanteils (H8). Die Engine bewertet fee_btc zum Tageskurs.
        fee_btc = num("fee_amount")
        fee_asset = row.get("fee_asset", "").upper()
        if fee_btc > 0 and fee_asset != "BTC":
            warn_fmt(
                "{file}: Auszahlungsgebühr {fee} {asset} am {tag} nicht verarbeitet — "
                "erwartet wird eine Gebühr in BTC.",
                file=FileRef(filename), fee=fee_btc, asset=fee_asset or "?",
                tag=de_date(date), year=de_date(date).year, internal=False,
            )
            fee_btc = Decimal("0")

        return Transaction(
            date=date,
            type=TxType.TRANSFER_OUT,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            fee_btc=fee_btc,
            source="21bitcoin",
            tx_id=f"21btc-{row_id}",
            note=note,
        )

    # deposit: die Kommentar-Annahme "ist immer EUR" wurde nie geprueft — eine
    # BTC-Einzahlung verschwand damit, waehrend die passende Auszahlung gebucht
    # wurde (SA2-11). EUR/CHF bleiben bekannt irrelevant und stumm.
    if tx_type_raw == "deposit":
        buy_asset = row.get("buy_asset", "").upper()
        if buy_asset not in ("EUR", "CHF"):
            warn_fmt(
                "{file}: Einzahlung am {tag} mit buy_asset='{asset}' nicht "
                "verarbeitet — erwartet wird EUR.",
                file=FileRef(filename), tag=de_date(date), asset=buy_asset,
                year=de_date(date).year, internal=False,
            )
        return None

    warn_fmt(
        "{file}: unbekannter Transaktionstyp '{typ}' am {tag} nicht verarbeitet.",
        file=FileRef(filename), typ=tx_type_raw, tag=de_date(date), year=de_date(date).year, internal=False,
    )
    return None
