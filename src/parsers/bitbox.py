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

Kopfzeile (Pflichtspalten hart geprüft, Audit 03.10.2026):
    Time,Type,Amount,Unit,Fee,Fee Unit,Address,Transaction ID,Note
"""
from __future__ import annotations
import re
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, sat_to_btc, de_date
from . import warn_fmt, FileRef, read_rows, amount, parse_iso_datetime, LINE_KEY

LABEL = "BitBox"
REQUIRED = ("Time", "Type", "Amount", "Fee", "Fee Unit", "Transaction ID")

# Ganze Wörter, Groß-/Kleinschreibung egal. Bewusst KEINE Teilwort-Treffer
# („Vergiftung", „Geschenkgutschein-Kauf" wären falsch positiv) und keine
# Adress-/Zahlenmuster — nur die Notiz, die der Nutzer selbst geschrieben hat.
_GIFT_WORDS = re.compile(
    r"\b(spende|spenden|gespendet|schenkung|geschenk|geschenkt|verschenkt|donation|donated|gift)\b",
    re.IGNORECASE,
)
# Bezahlte Vorgänge und Verneinungen, die trotzdem ein Schenkungswort enthalten
# (Audit run-1, Fund 4): „Gift Card", „Geschenk-Gutschein", „kein Geschenk". Ein
# Gutschein-Kauf mit BTC ist eine Veräußerung, kein unentgeltlicher Abgang — als
# GIFT_OUT verbrauchte er Lots und der Nachweis bescheinigte „ohne Gegenleistung".
_NOT_GIFT = re.compile(
    r"gift[\s_-]*cards?|gutschein|voucher|"
    r"\b(kein|keine|keinen|nicht|no|not)\b[\s-]+(\w+[\s-]+)?(geschenk|geschenkt|spende|schenkung|gift|donation)",
    re.IGNORECASE,
)


def is_gift_note(note: str) -> bool:
    """True, wenn die Wallet-Notiz eine Schenkung/Spende benennt (und keinen Gutschein-Kauf oder eine Verneinung)."""
    return bool(note) and _GIFT_WORDS.search(note) is not None and _NOT_GIFT.search(note) is None


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
    # Unbekannte Typen je (Typ, Jahr) zählen statt je Zeile warnen (B6) — und mit
    # Jahr, sonst stünde der Block in jedem Jahresreport.
    unknown: dict[tuple[str, int | None], int] = {}

    rows, _ = read_rows(filepath, label=LABEL, required=REQUIRED)
    for row in rows:
        tx = _parse_row(row, source, filepath.name, no_kyc, unknown)
        if tx is not None:
            transactions.append(tx)

    for (typ, year), n in sorted(unknown.items(), key=lambda kv: (kv[0][1] or 0, kv[0][0])):
        # internal bei noKYC-Wallets: der Dateiname allein verrät sonst dem
        # Finanzamt die Existenz einer noKYC-Wallet. Bei KYC-Wallets bleibt die
        # Warnung offiziell, der Wallet-Name wird aber redigiert — er ist ein
        # privates Label und gehört nicht in den Nachweis.
        warn_fmt(
            "{file}: {n} Zeile(n) mit unbekanntem Typ '{typ}' nicht verarbeitet.",
            internal=no_kyc, year=year, file=FileRef(filepath.name), n=n, typ=typ,
        )
    return transactions


def _parse_row(row: dict, source: str, filename: str, no_kyc: bool, unknown: dict) -> Transaction | None:
    line = row[LINE_KEY]
    # Datum zuerst: ISO 8601 MIT Timezone-Offset (ohne → harter Fehler, A8)
    date = parse_iso_datetime(row["Time"], label=LABEL, filename=filename, line=line, field="Time")

    tx_type_raw = row["Type"].lower()
    note = row.get("Note", "")
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
        key = (tx_type_raw, de_date(date).year)
        unknown[key] = unknown.get(key, 0) + 1
        return None

    # Betrag in Satoshi (abs: Vorzeichen steckt schon im Typ sent/received).
    # Satoshi sind ganzzahlig — ein Bruchteil wäre eine umformatierte Datei (C8).
    sat = amount(row, "Amount", label=LABEL, filename=filename)
    if sat != sat.to_integral_value():
        raise ValueError(f"{LABEL} {filename} Zeile {line}: Betrag '{row['Amount']}' Satoshi ist keine ganze Zahl.")
    btc_amount = abs(sat_to_btc(sat))

    # Gebühr — Unit heißt je nach BitBox-Version "satoshi" oder "sat". Bei
    # received ist eine eingetragene Fee die des Absenders, nicht unsere: 0.
    fee_raw = row.get("Fee", "")
    fee_unit = row.get("Fee Unit", "").lower()
    fee_btc = Decimal("0")
    if tx_type != TxType.TRANSFER_IN and fee_raw and fee_raw != "0":
        fee_val = amount(row, "Fee", label=LABEL, filename=filename)
        if fee_unit in ("satoshi", "sat"):
            if fee_val != fee_val.to_integral_value():
                raise ValueError(f"{LABEL} {filename} Zeile {line}: Gebühr '{fee_raw}' Satoshi ist keine ganze Zahl.")
            fee_btc = sat_to_btc(fee_val)
        elif fee_unit == "btc":
            fee_btc = fee_val
        else:
            # Nicht stillschweigend 0: eine Gebühr in unbekannter Einheit ist ein
            # unbebuchter Bestandsabgang.
            warn_fmt(
                "{file}: Gebühr '{fee}' mit unbekannter Einheit '{unit}' am {tag} "
                "nicht verarbeitet — Bestandsabgang fehlt.",
                internal=no_kyc, file=FileRef(filename), fee=fee_raw, unit=fee_unit,
                tag=de_date(date), year=de_date(date).year,
            )

    if self_transfer:
        if fee_btc <= 0:
            return None
        btc_amount = Decimal("0")
        note = f"wallet-intern (kein Bestandsabgang, nur Gebühr){' | ' + note if note else ''}"

    tx_id = row.get("Transaction ID", "")
    address = row.get("Address", "")

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
