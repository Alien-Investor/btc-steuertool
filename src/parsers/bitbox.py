"""Parser für BitBox Hardware Wallet CSV-Exporte.

Typen:
    received          → TRANSFER_IN  (Bestand bleibt, keine Gebühr unsererseits)
    sent              → TRANSFER_OUT (Bestand bleibt — eigene Wallet), Gebühr in
                        fee_btc: die Miner-Fee verlässt den Bestand und ist eine
                        Veräußerung des Gebührenanteils (H8, BMF 06.03.2025 Rn. 33/54/60)
    sent + Notiz mit  → GIFT_OUT: unentgeltliche Übertragung an Dritte — kein
    Schenkungs-Wort     Veräußerungsgeschäft, aber Bestandsabgang (§ 23 Abs. 1 S. 3 EStG
                        für den Empfänger). Erkannt am WORT in der Wallet-Notiz, siehe
                        _GIFT_WORDS. Jede so eingestufte Zeile steht im Report unter
                        einer eigenen Überschrift — die Einstufung ist nachprüfbar.
    sent_to_yourself  → nur die Gebühr (fee_btc), Menge 0: wallet-intern bewegt sich
                        kein Bestand, aber die Miner-Fee ist trotzdem weg.

`Amount` bei sent ist der Betrag, der beim Empfänger ankommt — OHNE Gebühr
(15.08.2026 gegen zwei echte Transaktionen im Block-Explorer geprüft:
Wallet-Abgang = Amount + Fee).
"""
from __future__ import annotations
import csv
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, sat_to_btc
from . import warn, warn_fmt, FileRef

# Ganze Wörter, Groß-/Kleinschreibung egal. Bewusst KEINE Teilwort-Treffer
# („Vergiftung", „Geschenkgutschein-Kauf" wären falsch positiv) und keine
# Adress-/Zahlenmuster — nur die Notiz, die der Nutzer selbst geschrieben hat.
_GIFT_WORDS = re.compile(
    r"\b(spende|spenden|gespendet|schenkung|geschenk|geschenkt|verschenkt|donation|donated|gift)\b",
    re.IGNORECASE,
)


def is_gift_note(note: str) -> bool:
    """True, wenn die Wallet-Notiz eine Schenkung/Spende benennt."""
    return bool(note) and _GIFT_WORDS.search(note) is not None


def parse(filepath: Path) -> list[Transaction]:
    """Parst eine BitBox-CSV-Datei und gibt eine Liste von Transactions zurück.

    Liegt die Datei in einem 'nokyc'-Unterordner (bitbox/nokyc/), werden alle
    Transaktionen mit no_kyc=True markiert und erscheinen nicht im Finanzamt-Report.
    """
    wallet_name = filepath.stem  # z.B. "wallet1"
    source = f"bitbox:{wallet_name}"
    # Case-insensitiv: ein Ordner 'NoKYC' oder 'NOKYC' wurde sonst als KYC
    # behandelt — der Fehler geht Richtung Offenlegung (SA2-04).
    no_kyc = filepath.parent.name.lower() == "nokyc"
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
    note = row.get("Note", "").strip()
    self_transfer = False
    if tx_type_raw == "sent":
        tx_type = TxType.GIFT_OUT if is_gift_note(note) else TxType.TRANSFER_OUT
    elif tx_type_raw == "received":
        tx_type = TxType.TRANSFER_IN
    elif tx_type_raw == "sent_to_yourself":
        # Interner Transfer innerhalb derselben Wallet (z.B. UTXO-Management):
        # kein Zu-/Abfluss des Bestands — aber die Miner-Fee ist trotzdem bezahlt
        # und verlässt den Bestand. Deshalb als TRANSFER_OUT mit Menge 0 und nur
        # der Gebühr; ohne Gebühr bleibt die Zeile bekannt irrelevant.
        tx_type = TxType.TRANSFER_OUT
        self_transfer = True
    else:
        # internal bei noKYC-Wallets: der Dateiname allein verrät sonst dem
        # Finanzamt die Existenz einer noKYC-Wallet. Bei KYC-Wallets bleibt die
        # Warnung offiziell, der Wallet-Name wird aber redigiert — er ist ein
        # privates Label und gehört nicht in den Nachweis.
        warn_fmt(
            "{file}: unbekannter Typ '{typ}' nicht verarbeitet.",
            internal=no_kyc, file=FileRef(filename), typ=tx_type_raw,
        )
        return None

    # Datum parsen (ISO 8601 mit Timezone-Offset)
    date = datetime.fromisoformat(row["Time"].strip()).astimezone(timezone.utc)

    # Betrag von Satoshi in BTC (abs: Vorzeichen steckt schon im Typ sent/received)
    btc_amount = abs(sat_to_btc(row["Amount"].strip()))

    # Gebühr — Unit heißt je nach BitBox-Version "satoshi" oder "sat". Bei
    # received ist eine eingetragene Fee die des Absenders, nicht unsere: 0.
    fee_raw = row.get("Fee", "").strip()
    fee_unit = row.get("Fee Unit", "").strip().lower()
    fee_btc = Decimal("0")
    if tx_type != TxType.TRANSFER_IN and fee_raw and fee_raw != "0":
        if fee_unit in ("satoshi", "sat"):
            fee_btc = sat_to_btc(fee_raw)
        elif fee_unit == "btc":
            fee_btc = Decimal(fee_raw)
        else:
            # Nicht stillschweigend 0: eine Gebühr in unbekannter Einheit ist ein
            # unbebuchter Bestandsabgang.
            warn_fmt(
                "{file}: Gebühr '{fee}' mit unbekannter Einheit '{unit}' am {tag} "
                "nicht verarbeitet — Bestandsabgang fehlt.",
                internal=no_kyc, file=FileRef(filename), fee=fee_raw, unit=fee_unit,
                tag=date.date(), year=date.year,
            )

    if self_transfer:
        if fee_btc <= 0:
            return None
        btc_amount = Decimal("0")
        note = f"wallet-intern (kein Bestandsabgang, nur Gebühr){' | ' + note if note else ''}"

    tx_id = row.get("Transaction ID", "").strip()
    address = row.get("Address", "").strip()

    # BitBox-Transfers haben keinen EUR-Wert
    return Transaction(
        date=date,
        type=tx_type,
        btc_amount=btc_amount,
        eur_amount=Decimal("0"),
        eur_price_per_btc=Decimal("0"),
        fee_eur=Decimal("0"),   # Gebühr ist in BTC (fee_btc), die Engine bewertet sie zum Tageskurs
        fee_btc=fee_btc,
        source=source,
        tx_id=tx_id,
        note=f"{note} | Adresse: {address}" if address else note,
        no_kyc=no_kyc,
    )
