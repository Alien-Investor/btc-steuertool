"""Sparrow Wallet: Transactions → „Export CSV“ (Format aus dem Sparrow-Quellcode, nicht bestätigt).

Kopfzeilen (WalletTransactions.java, Versionen über die Git-Historie zugeordnet):
    ab 2.5.5      Date (UTC),Label,Value (BTC|sats),Balance (…),Fee (…)[,Value (EUR)],Txid
    1.8.6–2.5.4   Date (UTC),Label,Value,Balance,Fee[,Value (EUR)],Txid
    1.8.1–1.8.5   Date,Label,Value,Balance,Fee[,Value (EUR)],Txid   ← Ortszeit ohne Zeitzone
    1.7.2–1.8.0   ohne Fiat-Spalte
    1.5.1–1.7.1   Date,Label,Value,Balance,Txid  (ohne Gebühr, Zeit ohne Sekunden)
    älter         ohne Txid — nicht unterstützt (keine Zuordnung über die TX-ID möglich)

Value = Netto-Änderung der Wallet mit Vorzeichen, bei Ausgängen INKLUSIVE Gebühr; Fee = Gebühr
der Transaktion, leer wenn ein Input fremd ist (Eingang von extern, CoinJoin/Payjoin). Einheit
BTC (immer 8 Nachkommastellen) oder sats (Ganzzahl) — Nutzereinstellung, bei „Auto“ BTC, sobald
die Wallet je einen Output ≥ 1 BTC hatte. Ohne Einheit in der Kopfzeile (vor 2.5.5) entscheidet
die Schreibweise: Nachkommastellen → BTC, nur Ganzzahlen → sats. Dezimalkomma (Einstellung
„Comma“) steht in Anführungszeichen und wird von parse_amount gelesen. Unbestätigt: „Unconfirmed“
statt Datum. Mit Fiat-Spalte hängt Sparrow eine Kommentarzeile „# Historical …“ an.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, sat_to_btc
from . import read_rows, parse_amount, LINE_KEY
from .wallet_export import Stats, delta_tx, emit_stats, local_time, warn_unconfirmed_format

LABEL = "Sparrow"
_VALUE = re.compile(r"^Value(?: \((BTC|sats)\))?$")


def matches(header: list[str]) -> bool:
    return (len(header) >= 5 and header[0] in ("Date (UTC)", "Date") and header[1] == "Label"
            and _VALUE.match(header[2]) is not None and header[3].startswith("Balance")
            and (len(header) == 5 or header[4].startswith("Fee")) and header[-1] == "Txid")


def parse(filepath: Path, *, no_kyc: bool) -> list[Transaction]:
    filename = filepath.name
    source = f"sparrow:{filepath.stem}"
    rows, header = read_rows(filepath, label=LABEL, comment="#")
    if not matches(header):
        raise ValueError(f"{LABEL} {filename}: Kopfzeile ist kein Sparrow-Export. Gelesen: {', '.join(header[:8])}")
    date_col, value_col = header[0], header[2]
    fee_col = header[4] if len(header) > 5 else None     # vor 1.7.2 ohne Gebührenspalte
    utc = date_col == "Date (UTC)"
    unit = _VALUE.match(value_col).group(1)
    guessed = unit is None
    if guessed:
        # Vor 2.5.5 ohne Einheit: BTC schreibt Sparrow seit 1.7.2 immer mit 8 Nachkommastellen
        frac = any(("." in r[value_col] or "," in r[value_col]) for r in rows if r[value_col])
        unit = "BTC" if frac else "sats"
    if fee_col not in (None, "Fee", f"Fee ({unit})"):
        raise ValueError(f"{LABEL} {filename}: Spalte '{fee_col}' passt nicht zur Einheit '{unit}' der Spalte '{value_col}'.")

    stats = Stats()
    txs: list[Transaction] = []
    for row in rows:
        line = row[LINE_KEY]
        raw_date = row[date_col]
        if raw_date.lower() == "unconfirmed":
            stats.add("unconfirmed", None)
            continue
        if utc:
            try:
                date = datetime.strptime(raw_date, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                raise ValueError(f"{LABEL} {filename} Zeile {line}, Spalte '{date_col}': '{raw_date}' — erwartet JJJJ-MM-TT HH:MM:SS.") from None
        else:
            fmt = "%Y-%m-%d %H:%M:%S" if raw_date.count(":") == 2 else "%Y-%m-%d %H:%M"
            date = local_time(raw_date, fmt, label=LABEL, filename=filename, line=line, field=date_col)
        delta = _btc(row, value_col, unit, filename)
        fee = _btc(row, fee_col, unit, filename) if fee_col and row[fee_col] else None
        tx = delta_tx(date=date, delta=delta, fee=fee, label=row["Label"], tx_id=row["Txid"], source=source,
                      no_kyc=no_kyc, where=f"{LABEL} {filename} Zeile {line}", stats=stats)
        if tx is not None:
            txs.append(tx)

    emit_stats(stats, label=LABEL, filename=filename, no_kyc=no_kyc)
    extra = ""
    if guessed:
        extra += f" Einheit aus der Schreibweise abgeleitet: {unit} (vor 2.5.5)."
    if not utc:
        extra += " Zeiten ohne Zeitzone als deutsche Ortszeit gelesen (vor 1.8.6)."
    if fee_col is None:
        extra += " Ohne Gebührenspalte (vor 1.7.2)."
    warn_unconfirmed_format(filename, "Sparrow Wallet", txs, no_kyc=no_kyc, extra=extra)
    return txs


def _btc(row: dict, field: str, unit: str, filename: str) -> Decimal:
    value = parse_amount(row[field], label=LABEL, filename=filename, line=row[LINE_KEY], field=field)
    if unit == "sats":
        if value != value.to_integral_value():
            raise ValueError(f"{LABEL} {filename} Zeile {row[LINE_KEY]}, Spalte '{field}': '{row[field]}' ist keine ganze Zahl Satoshi.")
        return sat_to_btc(value)
    return value
