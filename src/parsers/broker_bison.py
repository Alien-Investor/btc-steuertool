"""Parser für Bison Broker CSV-Exporte.

Kopfzeile (Semikolon, Leerzeichen nach dem Trennzeichen; Pflichtspalten hart geprüft, Audit 03.10.2026):
    Transaction ID; Transaction type; Currency; Asset; Eur (amount); Asset (amount);
    Asset (market price); Fee; Date (UTC - Coordinated Universal Time)
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, de_date
from . import FileRef, warn, warn_fmt, read_rows, amount, LINE_KEY

LABEL = "Bison"
DATE_COL = "Date (UTC - Coordinated Universal Time)"
REQUIRED = ("Transaction ID", "Transaction type", "Currency", "Asset", "Eur (amount)",
            "Asset (amount)", "Asset (market price)", "Fee", DATE_COL)


def parse(filepath: Path) -> list[Transaction]:
    transactions = []
    # Semikolon als Trennzeichen; read_rows trimmt Schlüssel und Werte (Bison
    # hat Leerzeichen nach dem Semikolon)
    rows, _ = read_rows(filepath, label=LABEL, required=REQUIRED, delimiter=";")
    for row in rows:
        tx = _parse_row(row, filepath.name)
        if tx is not None:
            transactions.append(tx)
    return transactions


def _parse_row(row: dict, filename: str) -> Transaction | None:
    tx_type_raw = row.get("Transaction type", "")
    asset = row.get("Asset", "").upper()
    currency = row.get("Currency", "").upper()
    line = row[LINE_KEY]

    # Datum: "YYYY-MM-DD HH:MM:SS" UTC
    date_str = row.get(DATE_COL, "")
    if not date_str:
        # Leerzeilen filtert csv.DictReader schon vorher weg — hier landen nur
        # echte Zeilen ohne Datum. Bei BTC-Bewegungen ist das steuerlich
        # relevant und darf nicht stillschweigend verschwinden.
        if asset == "BTC":
            warn(
                f"{filename}: {tx_type_raw or 'Zeile'} über "
                f"{row.get('Asset (amount)', '?')} BTC ohne Datum — nicht verarbeitet.", internal=False
            )
        return None
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError(
            f"{LABEL} {filename} Zeile {line}: Datum '{date_str}' nicht lesbar (erwartet JJJJ-MM-TT HH:MM:SS)."
        ) from None

    tx_id = row.get("Transaction ID", "")

    def num(field: str) -> Decimal:
        return amount(row, field, label=LABEL, filename=filename)

    if tx_type_raw == "Buy" and asset == "BTC":
        eur_amount = num("Eur (amount)")
        btc_amount = num("Asset (amount)")
        market_price = num("Asset (market price)")
        # Bison hat keine explizite Gebühr — im Spread enthalten, fee_eur = 0
        return Transaction(
            date=date,
            type=TxType.BUY,
            btc_amount=btc_amount,
            eur_amount=eur_amount,
            eur_price_per_btc=market_price if market_price else (eur_amount / btc_amount if btc_amount else Decimal("0")),
            fee_eur=Decimal("0"),
            source="bison",
            tx_id=tx_id,
            note="Bison Kauf",
        )

    elif tx_type_raw == "Sell" and asset == "BTC":
        eur_amount = num("Eur (amount)")
        btc_amount = num("Asset (amount)")
        market_price = num("Asset (market price)")
        return Transaction(
            date=date,
            type=TxType.SELL,
            btc_amount=btc_amount,
            eur_amount=eur_amount,
            eur_price_per_btc=market_price if market_price else (eur_amount / btc_amount if btc_amount else Decimal("0")),
            fee_eur=Decimal("0"),
            source="bison",
            tx_id=tx_id,
            note="Bison Verkauf",
        )

    elif tx_type_raw == "Deposit" and asset == "BTC" and currency == "":
        # BTC-Eingang von eigener Wallet (für Verkauf eingesendet)
        btc_amount = num("Asset (amount)")
        return Transaction(
            date=date,
            type=TxType.TRANSFER_IN,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            source="bison",
            tx_id=tx_id,
            note="BTC-Eingang von eigener Wallet",
        )

    elif tx_type_raw == "Withdraw" and asset == "BTC":
        # BTC-Auszahlung an eigene Wallet (Gegenstück zu Deposit). Bison weist
        # in echten Exporten Fee=0 aus (Netzwerkgebühr trägt Bison). Sollte doch
        # eine Gebühr stehen, ist ihre Einheit aus dem Export nicht ablesbar —
        # melden statt raten (eine Gebühr in BTC wäre ein Bestandsabgang, H8).
        btc_amount = num("Asset (amount)")
        fee_raw = num("Fee")
        if fee_raw > 0:
            warn(
                f"{filename}: BTC-Auszahlung am {de_date(date)} mit Gebühr {fee_raw} — "
                f"Einheit im Export nicht erkennbar, Gebühr NICHT verbucht.",
                internal=False, year=de_date(date).year,
            )
        return Transaction(
            date=date,
            type=TxType.TRANSFER_OUT,
            btc_amount=btc_amount,
            eur_amount=Decimal("0"),
            eur_price_per_btc=Decimal("0"),
            fee_eur=Decimal("0"),
            source="bison",
            tx_id=tx_id,
            note="BTC-Auszahlung an eigene Wallet",
        )

    # EUR-Ein-/Auszahlungen und andere Assets (ETH etc.) sind bekannt irrelevant —
    # unbekannte BTC-Zeilen aber melden (z.B. 'Withdraw' BTC oder neue Typen)
    if asset == "BTC":
        warn_fmt("{file}: Transaktionstyp '{typ}' (BTC) am {tag} nicht verarbeitet.", internal=False,
                 year=de_date(date).year, file=FileRef(filename), typ=tx_type_raw, tag=de_date(date))
    return None
