"""Parser für BitBox Hardware Wallet CSV-Exporte."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, sat_to_btc
from . import warn


def parse(filepath: Path) -> list[Transaction]:
    """Parst eine BitBox-CSV-Datei und gibt eine Liste von Transactions zurück.

    Liegt die Datei in einem 'nokyc'-Unterordner (bitbox/nokyc/), werden alle
    Transaktionen mit no_kyc=True markiert und erscheinen nicht im Finanzamt-Report.
    """
    wallet_name = filepath.stem  # z.B. "wallet1"
    source = f"bitbox:{wallet_name}"
    no_kyc = filepath.parent.name == "nokyc"
    transactions = []

    with open(filepath, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tx = _parse_row(row, source, filepath.name, no_kyc=no_kyc)
            if tx is not None:
                transactions.append(tx)

    return transactions


def _parse_row(row: dict, source: str, filename: str, no_kyc: bool = False) -> Transaction | None:
    tx_type_raw = row["Type"].strip().lower()
    if tx_type_raw == "sent":
        tx_type = TxType.TRANSFER_OUT
    elif tx_type_raw == "received":
        tx_type = TxType.TRANSFER_IN
    elif tx_type_raw == "sent_to_yourself":
        # Interner Transfer innerhalb derselben Wallet (z.B. UTXO-Management):
        # kein Zu-/Abfluss, kein steuerlicher Vorgang — bekannt irrelevant
        return None
    else:
        # internal bei noKYC-Wallets: der Dateiname allein verrät sonst dem
        # Finanzamt die Existenz einer noKYC-Wallet
        warn(f"{filename}: unbekannter Typ '{tx_type_raw}' nicht verarbeitet.", internal=no_kyc)
        return None

    # Datum parsen (ISO 8601 mit Timezone-Offset)
    date = datetime.fromisoformat(row["Time"].strip()).astimezone(timezone.utc)

    # Betrag von Satoshi in BTC (abs: Vorzeichen steckt schon im Typ sent/received)
    btc_amount = abs(sat_to_btc(row["Amount"].strip()))

    # Gebühr (nur bei sent, bei received meist leer) — Unit heißt je nach
    # BitBox-Version "satoshi" oder "sat"
    fee_raw = row.get("Fee", "").strip()
    fee_unit = row.get("Fee Unit", "").strip().lower()
    if fee_raw and fee_unit in ("satoshi", "sat"):
        fee_btc = sat_to_btc(fee_raw)
    else:
        fee_btc = Decimal("0")

    note = row.get("Note", "").strip()
    tx_id = row.get("Transaction ID", "").strip()
    address = row.get("Address", "").strip()

    # BitBox-Transfers haben keinen EUR-Wert
    return Transaction(
        date=date,
        type=tx_type,
        btc_amount=btc_amount,
        eur_amount=Decimal("0"),
        eur_price_per_btc=Decimal("0"),
        fee_eur=Decimal("0"),  # On-Chain-Fee in BTC, nicht EUR — hier nicht umgerechnet
        source=source,
        tx_id=tx_id,
        note=f"{note} | Adresse: {address}" if address else note,
        no_kyc=no_kyc,
    )
