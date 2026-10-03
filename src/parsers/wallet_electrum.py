"""Electrum: History → Export → CSV (Format aus dem Electrum-Quellcode, nicht bestätigt).

Kopfzeilen (wallet.py export_history_to_file, Versionen über die Git-Historie zugeordnet):
    ab 4.8.0    oc_transaction_hash,ln_payment_hash,label,confirmations,amount_chain_bc,
                amount_lightning_bc,fiat_value,network_fee_bc,fiat_fee,timestamp
    4.6–4.7     … network_fee_satoshi …   (Gebühr als Ganzzahl Satoshi)
    3.3–4.5     transaction_hash,label,confirmations,value,fiat_value,fee,fiat_fee,timestamp
    älter       transaction_hash,label,[confirmations,]value,timestamp   (ohne Gebühr)

Beträge in BTC mit Punkt, nachgestellte Nullen abgeschnitten („1.“, „0.“), unabhängig von der
Anzeigeeinheit. amount_chain_bc/value = Netto-Änderung mit Vorzeichen, bei Ausgängen INKLUSIVE
Gebühr. Gebühr „0.“ heißt auch „unbekannt“ (fremde Inputs) — bei Ausgängen deshalb als
unbekannt behandelt. timestamp = Ortszeit des Rechners OHNE Zeitzone → als Europe/Berlin
gelesen (die Zeitzone des Exportrechners steht nicht in der Datei). Leerer timestamp =
unbestätigt (bis 4.7). Lightning-Zeilen (ln_payment_hash, amount_lightning_bc) werden nicht
erfasst, sondern gemeldet; der On-Chain-Teil einer Kanal-Öffnung/-Schließung bleibt gebucht.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ..models import Transaction, sat_to_btc, de_date
from . import read_rows, parse_amount, LINE_KEY
from .wallet_export import Stats, delta_tx, emit_stats, local_time, warn_unconfirmed_format

LABEL = "Electrum"

_NEW = ["oc_transaction_hash", "ln_payment_hash", "label", "confirmations", "amount_chain_bc",
        "amount_lightning_bc", "fiat_value"]
_OLD = ("transaction_hash", "label")


def matches(header: list[str]) -> bool:
    if header[:7] == _NEW and header[-1] == "timestamp" and len(header) == 10 \
            and header[7] in ("network_fee_bc", "network_fee_satoshi"):
        return True
    return tuple(header[:2]) == _OLD and "value" in header and header[-1] == "timestamp"


def parse(filepath: Path, *, no_kyc: bool) -> list[Transaction]:
    filename = filepath.name
    source = f"electrum:{filepath.stem}"
    rows, header = read_rows(filepath, label=LABEL)
    if not matches(header):
        raise ValueError(f"{LABEL} {filename}: Kopfzeile ist kein Electrum-Export. Gelesen: {', '.join(header[:10])}")
    new = header[0] == "oc_transaction_hash"
    if new:
        txid_col, amount_col, fee_col = "oc_transaction_hash", "amount_chain_bc", header[7]
    else:
        txid_col, amount_col, fee_col = "transaction_hash", "value", ("fee" if "fee" in header else None)
    fee_in_sat = fee_col == "network_fee_satoshi"

    stats = Stats()
    txs: list[Transaction] = []
    for row in rows:
        line = row[LINE_KEY]
        if not row["timestamp"]:
            stats.add("unconfirmed", None)
            continue
        date = local_time(row["timestamp"], "%Y-%m-%d %H:%M:%S" if row["timestamp"].count(":") == 2 else "%Y-%m-%d %H:%M",
                          label=LABEL, filename=filename, line=line, field="timestamp")
        if new and _num(row, "amount_lightning_bc", filename) != 0:
            stats.add("lightning", de_date(date).year)
        delta = _num(row, amount_col, filename)
        if delta == 0:
            continue    # reine Lightning-Zeile: kein On-Chain-Bestand bewegt
        fee = None
        if fee_col and row[fee_col]:
            fee = _num(row, fee_col, filename)
            if fee_in_sat:
                if fee != fee.to_integral_value():
                    raise ValueError(f"{LABEL} {filename} Zeile {line}: Gebühr '{row[fee_col]}' Satoshi ist keine ganze Zahl.")
                fee = sat_to_btc(fee)
        tx_id = row[txid_col]
        if set(tx_id) == {"-"}:
            tx_id = ""      # Gruppe ohne eigene Transaktion („----“)
        tx = delta_tx(date=date, delta=delta, fee=fee, label=row["label"], tx_id=tx_id, source=source,
                      no_kyc=no_kyc, where=f"{LABEL} {filename} Zeile {line}", stats=stats)
        if tx is not None:
            txs.append(tx)

    emit_stats(stats, label=LABEL, filename=filename, no_kyc=no_kyc)
    extra = " Zeiten ohne Zeitzone (Electrum schreibt die Ortszeit des Rechners) als deutsche Ortszeit gelesen."
    if fee_col is None:
        extra += " Sehr altes Exportformat ohne Gebührenspalte."
    warn_unconfirmed_format(filename, "Electrum", txs, no_kyc=no_kyc, extra=extra)
    return txs


def _num(row: dict, field: str, filename: str) -> Decimal:
    return parse_amount(row[field], label=LABEL, filename=filename, line=row[LINE_KEY], field=field)
