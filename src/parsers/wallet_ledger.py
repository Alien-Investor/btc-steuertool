"""Ledger Wallet (bis Desktop 2.131 „Ledger Live“): Einstellungen → Konten → Historie der
Kontobewegungen → Speichern (Format aus dem Quellcode, nicht bestätigt).

Kopfzeile (libs/ledger-live-common/src/csvExport.ts):
    Operation Date,Status,Currency Ticker,Operation Type,Operation Amount,Operation Fees,Operation Hash,
    Account Name,Account xpub,Countervalue Ticker,Countervalue at Operation Date,Countervalue at CSV Export
Ältere Fassungen ohne Status (vor 03/2024), ohne Countervalue-Spalten oder mit „Account id“ statt
„Account xpub“ — Spalten werden deshalb über den Namen gelesen. CRLF, kein Quoting (Kommas in
Namen löscht Ledger), Datum ISO 8601 UTC („…Z“).

ALLE ausgewählten Konten und Coins in EINER Datei: nur Currency Ticker BTC zählt, jedes Konto ist
eine eigene Wallet (Quelle „ledger:<Kontoname>“; gleiche Namen bei verschiedenen xpubs werden
durchnummeriert — der xpub selbst geht in kein Dokument). Beträge ohne Vorzeichen, Richtung in
Operation Type:
    OUT  Betrag = gesendet + Gebühr (Gebühr ENTHALTEN), Operation Fees = Gebühr
    IN   Betrag = empfangen; Operation Fees = Gebühr des ABSENDERS → ignoriert
An sich selbst im selben Konto: OUT und IN mit demselben Hash. Deshalb je (Konto, Hash) netto
gerechnet: Netto = Σ IN − Σ OUT, dann wie Sparrow/Electrum (wallet_export.delta_tx) — übrig bleibt
bei Selbstüberweisungen genau die Gebühr. Status „Failed“ → übersprungen.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ..models import Transaction, de_date
from . import read_rows, parse_amount, parse_iso_datetime, warn_fmt, FileRef, LINE_KEY, _sanitize, wallet_files
from .wallet_export import Stats, delta_tx, emit_stats, warn_unconfirmed_format

LABEL = "Ledger Wallet"
REQUIRED = ("Operation Date", "Currency Ticker", "Operation Type", "Operation Amount", "Operation Fees",
            "Operation Hash", "Account Name")


def _account_key(row: dict, key_col: str | None) -> str:
    """xpub des Kontos. Alte Exporte haben „Account id“ (z. B. libcore:1:bitcoin:xpub…:native_segwit) —
    daraus den xpub ziehen, damit alter und neuer Export desselben Kontos denselben Schlüssel haben."""
    raw = row.get(key_col, "") if key_col else ""
    if key_col == "Account id":
        for part in raw.split(":"):
            if part[:4].lower() in ("xpub", "ypub", "zpub", "tpub", "vpub", "upub"):
                return part
    return raw


def matches(header: list[str]) -> bool:
    return header[:1] == ["Operation Date"] and "Operation Hash" in header and "Account Name" in header


def parse(filepath: Path, *, no_kyc: bool) -> list[Transaction]:
    filename = filepath.name
    rows, header = read_rows(filepath, label=LABEL, required=REQUIRED)
    key_col = "Account xpub" if "Account xpub" in header else ("Account id" if "Account id" in header else None)

    stats = Stats()
    # Vorlauf: Konto-Schlüssel je Name, Nummerierung nach dem SCHLÜSSEL sortiert statt nach der
    # Zeilenfolge — sonst wechselte „Bitcoin 1 (2)“ bei jedem Neuexport das Konto (Audit v1.4)
    by_name: dict[str, set[str]] = {}
    for row in rows:
        if row["Currency Ticker"].upper() == "BTC":
            n = _sanitize(row["Account Name"]).strip() or "Bitcoin"
            by_name.setdefault(n, set()).add(_account_key(row, key_col) or n)
    names: dict[str, str] = {}          # Konto-Schlüssel (xpub) → Wallet-Name
    for n, keys in by_name.items():
        for i, k in enumerate(sorted(keys), 1):
            names[k] = n if i == 1 else f"{n} ({i})"
    groups: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []
    unknown: dict[tuple[str, int | None], int] = {}
    failed = 0
    for row in rows:
        line = row[LINE_KEY]
        if row["Currency Ticker"].upper() != "BTC":
            stats.add("other_coin", None)
            continue
        status = row.get("Status", "").lower()
        if status == "failed":
            failed += 1
            continue
        if status not in ("", "confirmed", "succeeded"):
            stats.add("unconfirmed", None)     # z. B. „Pending“: erst nach Bestätigung buchen
            continue
        date = parse_iso_datetime(row["Operation Date"], label=LABEL, filename=filename, line=line, field="Operation Date")
        typ = row["Operation Type"].upper()
        if typ not in ("IN", "OUT"):
            key = (typ, de_date(date).year)
            unknown[key] = unknown.get(key, 0) + 1
            continue
        name = _sanitize(row["Account Name"]).strip() or "Bitcoin"
        wallet = names[_account_key(row, key_col) or name]
        if not row["Operation Hash"]:
            raise ValueError(f"{LABEL} {filename} Zeile {line}: Operation Hash fehlt — ohne ihn lassen sich "
                             f"Selbstüberweisungen und Überträge nicht erkennen.")
        gkey = (wallet, row["Operation Hash"])
        g = groups.get(gkey)
        if g is None:
            g = groups[gkey] = {"date": date, "net": Decimal("0"), "fee": None, "line": line}
            order.append(gkey)
        amount = parse_amount(row["Operation Amount"], label=LABEL, filename=filename, line=line, field="Operation Amount")
        if amount < 0:
            # Beträge sind vorzeichenlos (Richtung in Operation Type) — ein Vorzeichen drehte sie still um
            raise ValueError(f"{LABEL} {filename} Zeile {line}: negativer Betrag '{row['Operation Amount']}' — Exportformat geändert?")
        if typ == "IN":
            g["net"] += amount
        else:
            g["net"] -= amount
            g["fee"] = parse_amount(row["Operation Fees"], label=LABEL, filename=filename, line=line, field="Operation Fees")
            if g["fee"] < 0:
                raise ValueError(f"{LABEL} {filename} Zeile {line}: negative Gebühr '{row['Operation Fees']}'.")
        g["date"] = min(g["date"], date)

    for key, wallet in names.items():
        wallet_files.setdefault(f"ledger:{wallet}", []).append((filename, key))
    txs: list[Transaction] = []
    for wallet, txid in order:
        g = groups[(wallet, txid)]
        tx = delta_tx(date=g["date"], delta=g["net"], fee=g["fee"], label="", tx_id=txid.lower(),
                      source=f"ledger:{wallet}", no_kyc=no_kyc, where=f"{LABEL} {filename} Zeile {g['line']}", stats=stats)
        if tx is not None:
            txs.append(tx)

    for (typ, year), n in sorted(unknown.items(), key=lambda kv: (kv[0][1] or 0, kv[0][0])):
        warn_fmt("{file}: {n} BTC-Zeile(n) mit unbekanntem Typ '{typ}' nicht verarbeitet.",
                 internal=no_kyc, year=year, file=FileRef(filename, "ein Ledger-Export"), n=n, typ=typ)
    if failed:
        warn_fmt("{file}: {n} fehlgeschlagene Operation(en) übersprungen.", internal=True,
                 file=FileRef(filename, "ein Ledger-Export"), n=failed)
    emit_stats(stats, label=LABEL, filename=filename, no_kyc=no_kyc)
    accounts = len({w for w, _ in order})
    warn_unconfirmed_format(
        filename, "Ledger Wallet/Ledger Live", txs, no_kyc=no_kyc,
        extra=f" {accounts} Bitcoin-Konto/-Konten, jedes als eigene Wallet.")
    return sorted(txs, key=lambda t: t.date)
