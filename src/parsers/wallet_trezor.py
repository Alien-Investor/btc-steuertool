"""Trezor Suite: Konto → Transaktionen → Export → CSV (Format aus dem Suite-Quellcode, nicht bestätigt).

Kopfzeile (exportTransactionsUtils.ts), ein Konto je Datei:
    Timestamp,Date,Time,Type,Transaction ID,Fee,Fee unit,Address,Label,Amount,Amount unit,Fiat (EUR),Other
Trennzeichen Komma ab Suite 25.9.1, davor Semikolon (gleiche Spalten).

EINE ZEILE JE OUTPUT, nicht je Transaktion: Beträge derselben Transaktion werden summiert, die
Gebühr steht nur in der ersten Zeile und wird einmal gezählt. Amount ohne Vorzeichen, in BTC,
OHNE Gebühr; die Richtung steht in Type:
    RECV  → TRANSFER_IN (Gebühr in der Datei leer — die des Absenders steht nicht drin)
    SENT  → TRANSFER_OUT, btc_amount = Summe der Outputs, fee_btc = Gebühr (GIFT_OUT bei Schenkungswort)
    SELF  → nur die Gebühr (wie BitBox sent_to_yourself)
Zeit: nur Timestamp (Unix-Sekunden, UTC) — Date/Time sind nach Sprache und Zeitzone des Rechners
formatiert. Unbestätigte Transaktionen exportiert die Suite nicht, CoinJoin/Payjoin (Typ JOINT)
ebenfalls nicht, und ein aktiver Suchfilter kürzt den Export. Ab 26.5.2 steht vor Labels, die mit
= + - @ beginnen, ein „'“ (Formelschutz) — wird entfernt.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, de_date
from . import read_rows, parse_amount, warn_fmt, FileRef, LINE_KEY, wallet_files
from .wallet_export import Stats, delta_tx, emit_stats, warn_unconfirmed_format

LABEL = "Trezor Suite"
# Die Suite schlägt „<Konto>_JJJJMMTTTHHMMSS.csv“ vor — der Exportzeitpunkt gehört nicht zum
# Wallet-Namen, sonst wären zwei Exporte desselben Kontos zwei Wallets (doppelter Bestand)
_EXPORT_STAMP = re.compile(r"_\d{8}T\d{6}$")
REQUIRED = ("Timestamp", "Type", "Transaction ID", "Fee", "Fee unit", "Label", "Amount", "Amount unit")


def matches(header: list[str]) -> bool:
    return header[:5] == ["Timestamp", "Date", "Time", "Type", "Transaction ID"] and "Amount unit" in header


def _delimiter(filepath: Path) -> str:
    first = filepath.read_bytes().split(b"\n", 1)[0]
    return ";" if first.count(b";") > first.count(b",") else ","


def parse(filepath: Path, *, no_kyc: bool) -> list[Transaction]:
    filename = filepath.name
    source = f"trezor:{_EXPORT_STAMP.sub('', filepath.stem) or filepath.stem}"
    rows, header = read_rows(filepath, label=LABEL, required=REQUIRED, delimiter=_delimiter(filepath))

    stats = Stats()
    groups: dict[str, dict] = {}     # txid → {type, date, amount, fee, labels, line}
    own_addr: set[str] = set()       # Empfangsadressen dieses Kontos (RECV/SELF)
    sent_addr: list[tuple[str, int]] = []
    order: list[str] = []
    unknown: dict[tuple[str, int | None], int] = {}
    for row in rows:
        line = row[LINE_KEY]
        if not row["Timestamp"]:
            stats.add("unconfirmed", None)
            continue
        try:
            date = datetime.fromtimestamp(int(row["Timestamp"]), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            raise ValueError(f"{LABEL} {filename} Zeile {line}, Spalte 'Timestamp': '{row['Timestamp']}' ist keine Unix-Zeit.") from None
        typ = row["Type"].upper()
        unit = row["Amount unit"].upper()
        if unit in ("SAT", "SATS", "SATOSHI", "MBTC", "UBTC", "BITS"):
            # Die Suite schreibt immer BTC (Netzwerk-Konfiguration) — eine Bitcoin-Untereinheit hieße
            # geändertes Exportformat; überspringen wäre ein stiller Bestandsverlust (Audit v1.4, B3)
            raise ValueError(f"{LABEL} {filename} Zeile {line}: Einheit '{row['Amount unit']}' statt BTC — "
                             f"Exportformat geändert? Bitte melden.")
        if unit and unit != "BTC":
            stats.add("other_coin", None)
            continue
        if typ not in ("RECV", "SENT", "SELF", "FAILED"):
            key = (typ, de_date(date).year)
            unknown[key] = unknown.get(key, 0) + 1
            continue
        txid = row["Transaction ID"]
        if not txid:
            raise ValueError(f"{LABEL} {filename} Zeile {line}: Transaction ID fehlt — ohne sie lassen sich die "
                             f"Zeilen einer Transaktion nicht zusammenfassen.")
        g = groups.get(txid)
        if g is None:
            g = groups[txid] = {"type": typ, "date": date, "amount": Decimal("0"), "fee": None, "labels": [], "line": line}
            order.append(txid)
        elif g["type"] != typ:
            raise ValueError(f"{LABEL} {filename} Zeile {line}: Transaktion {txid[:16]}… hat Zeilen vom Typ {g['type']} und {typ}.")
        amount = parse_amount(row["Amount"], label=LABEL, filename=filename, line=line, field="Amount")
        if amount < 0:
            # Amount ist vorzeichenlos (Richtung steht in Type) — ein Vorzeichen drehte die Richtung still um
            raise ValueError(f"{LABEL} {filename} Zeile {line}: negativer Betrag '{row['Amount']}' — Exportformat geändert?")
        g["amount"] += amount
        if row["Fee"]:
            if row["Fee unit"].upper() not in ("BTC", ""):
                raise ValueError(f"{LABEL} {filename} Zeile {line}: Gebühr in unbekannter Einheit '{row['Fee unit']}'.")
            if g["fee"] is not None:
                raise ValueError(f"{LABEL} {filename} Zeile {line}: zweite Gebühr für Transaktion {txid[:16]}… — Datei umsortiert oder beschädigt?")
            g["fee"] = parse_amount(row["Fee"], label=LABEL, filename=filename, line=line, field="Fee")
            if g["fee"] < 0:
                raise ValueError(f"{LABEL} {filename} Zeile {line}: negative Gebühr '{row['Fee']}'.")
        addr = row.get("Address", "")
        if addr and typ in ("RECV", "SELF"):
            own_addr.add(addr)
        elif addr and typ == "SENT":
            sent_addr.append((addr, de_date(date).year))
        label = row["Label"]
        if label[:1] == "'" and label[1:2] in ("=", "+", "-", "@"):
            label = label[1:]
        if label and label not in g["labels"]:
            g["labels"].append(label)

    wallet_files.setdefault(source, []).append((filename, ""))
    txs: list[Transaction] = []
    for txid in order:
        g = groups[txid]
        fee = g["fee"] or Decimal("0")
        if g["type"] == "RECV":
            delta = g["amount"]
            fee_arg = None
        elif g["type"] == "SENT":
            delta = -(g["amount"] + fee)
            fee_arg = g["fee"]
        else:       # SELF, FAILED: nur die Gebühr verlässt das Konto
            if g["type"] == "FAILED":
                stats.add("failed", de_date(g["date"]).year)
            if fee <= 0:
                continue
            delta, fee_arg = -fee, fee
        tx = delta_tx(date=g["date"], delta=delta, fee=fee_arg, label=" | ".join(g["labels"]), tx_id=txid,
                      source=source, no_kyc=no_kyc, where=f"{LABEL} {filename} Zeile {g['line']}", stats=stats)
        if tx is not None:
            txs.append(tx)

    for (typ, year), n in sorted(unknown.items(), key=lambda kv: (kv[0][1] or 0, kv[0][0])):
        warn_fmt("{file}: {n} Zeile(n) mit unbekanntem Typ '{typ}' nicht verarbeitet.",
                 internal=no_kyc, year=year, file=FileRef(filename, "ein Trezor-Suite-Export"), n=n, typ=typ)
    # Ein SENT-Output an eine Adresse, die im selben Konto auch empfängt, ist ein eigener Output:
    # er wurde mitgezählt, obwohl er das Konto nie verlassen hat (Audit v1.4, Format noch unklar)
    own_out: dict[int, int] = {}
    for addr, year in sent_addr:
        if addr in own_addr:
            own_out[year] = own_out.get(year, 0) + 1
    for year, n in sorted(own_out.items()):
        warn_fmt("{file}: {n} gesendete(r) Output(s) im Jahr {jahr} an eine eigene Empfangsadresse dieses Kontos — "
                 "als Abgang mitgezählt; bitte prüfen, ob der Betrag das Konto wirklich verlassen hat.",
                 internal=no_kyc, year=year, jahr=year, file=FileRef(filename, "ein Trezor-Suite-Export"), n=n)
    emit_stats(stats, label=LABEL, filename=filename, no_kyc=no_kyc)
    warn_unconfirmed_format(
        filename, "Trezor Suite", txs, no_kyc=no_kyc,
        extra=" CoinJoin-/Payjoin-Transaktionen (Typ JOINT) fehlen im Suite-Export, ein aktiver Suchfilter kürzt ihn.")
    return sorted(txs, key=lambda t: t.date)
