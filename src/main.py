#!/usr/bin/env python3
"""BTC Steuertool — CLI-Einstieg."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

# Projekt-Root ist das Verzeichnis über src/
ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(ROOT))

from src.parsers import bitbox, broker_21bitcoin, broker_bison, broker_swissquote, broker_strike, broker_pocket, manual_sales, manual_buys, bisq
from src.fifo_engine import FifoEngine
from src.tax_report import TaxReport
from src.formal_report import generate_tax_free_proof
from src.models import TxType
import src.fx_rates as fx_rates


def load_all_transactions(data_dir: Path):
    transactions = []

    # BitBox-Wallets (KYC)
    bitbox_dir = data_dir / "bitbox"
    if bitbox_dir.exists():
        for csv_file in sorted(bitbox_dir.glob("*.csv")):
            txs = bitbox.parse(csv_file)
            transactions.extend(txs)
            print(f"  BitBox {csv_file.stem}: {len(txs)} Transaktionen")

    # BitBox-Wallets (noKYC — bitbox/nokyc/*.csv)
    nokyc_dir = data_dir / "bitbox" / "nokyc"
    if nokyc_dir.exists():
        nokyc_txs = []
        for csv_file in sorted(nokyc_dir.glob("*.csv")):
            txs = bitbox.parse(csv_file)
            nokyc_txs.extend(txs)
            print(f"  BitBox noKYC {csv_file.stem}: {len(txs)} Transaktionen")
        if nokyc_txs:
            transactions.extend(nokyc_txs)
            print(f"  → {len(nokyc_txs)} noKYC-Wallet-Transaktionen (intern, nicht für Finanzamt)")

    # Broker: 21bitcoin (Dateiname kann variieren, z.B. 21bitcoin-gesamt.csv oder 21bitcoin_name_gesamt.csv)
    btc21_files = sorted((data_dir / "Broker").glob("21bitcoin*.csv"))
    if btc21_files:
        btc21_txs = []
        for bf in btc21_files:
            txs = broker_21bitcoin.parse(bf)
            btc21_txs.extend(txs)
        transactions.extend(btc21_txs)
        print(f"  21bitcoin: {len(btc21_txs)} Transaktionen")

    # Broker: Bison
    bison_file = data_dir / "Broker" / "Bison-CSV-Gesamt.csv"
    if bison_file.exists():
        txs = broker_bison.parse(bison_file)
        transactions.extend(txs)
        print(f"  Bison: {len(txs)} Transaktionen")

    # Broker: Swissquote
    sq_file = data_dir / "Broker" / "Swissquote_CSV-Gesamt.csv"
    if sq_file.exists():
        txs = broker_swissquote.parse(sq_file)
        transactions.extend(txs)
        print(f"  Swissquote: {len(txs)} Transaktionen")

    # Broker: Strike (mehrere CSV-Dateien möglich)
    strike_files = sorted((data_dir / "Broker").glob("strike_*.csv"))
    if strike_files:
        strike_txs = []
        for sf in strike_files:
            txs = broker_strike.parse(sf)
            strike_txs.extend(txs)
        transactions.extend(strike_txs)
        print(f"  Strike: {len(strike_txs)} Transaktionen ({len(strike_files)} Dateien)")

    # Broker: Pocket (mehrere CSV-Dateien möglich, z.B. Pocket_-_2025.csv)
    pocket_files = sorted((data_dir / "Broker").glob("Pocket*.csv"))
    if pocket_files:
        pocket_txs = []
        for pf in pocket_files:
            txs = broker_pocket.parse(pf)
            pocket_txs.extend(txs)
        transactions.extend(pocket_txs)
        print(f"  Pocket: {len(pocket_txs)} Transaktionen ({len(pocket_files)} Dateien)")

    # Broker: Bisq (noKYC P2P, mehrere CSV-Dateien möglich)
    bisq_files = sorted((data_dir / "Broker").glob("bisq*.csv"))
    if bisq_files:
        bisq_txs = []
        for bf in bisq_files:
            txs = bisq.parse(bf)
            bisq_txs.extend(txs)
        transactions.extend(bisq_txs)
        print(f"  Bisq (noKYC): {len(bisq_txs)} Transaktionen ({len(bisq_files)} Dateien)")

    # Manuelle Verkäufe (private Peer-to-Peer Transaktionen)
    manual_file = data_dir / "manual_sales.csv"
    if manual_file.exists():
        txs = manual_sales.parse(manual_file)
        transactions.extend(txs)
        print(f"  Manuell (Verkäufe): {len(txs)} Transaktionen")

    # Manuelle Käufe (noKYC: Robosats, P2P, Bargeld etc.)
    manual_buys_file = data_dir / "manual_buys.csv"
    if manual_buys_file.exists():
        txs = manual_buys.parse(manual_buys_file)
        transactions.extend(txs)
        print(f"  Manuell (Käufe):   {len(txs)} Transaktionen")

    return sorted(transactions, key=lambda t: t.date)


def main():
    parser = argparse.ArgumentParser(
        description="Bitcoin Steuerreport (Deutschland, FiFo, § 23 EStG)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--year", type=int, metavar="JAHR", help="Report für ein Steuerjahr (z.B. --year 2024)")
    group.add_argument("--all", action="store_true", help="Reports für alle Jahre mit Transaktionen")
    parser.add_argument("--csv", action="store_true", help="Zusätzlich CSV-Dateien nach reports/ exportieren")
    parser.add_argument("--nachweis", action="store_true", help="Formalen Steuernachweis für Steuerberater/Finanzamt erzeugen")
    parser.add_argument("--data-dir", type=Path, metavar="PFAD", default=None,
                        help="Datenverzeichnis mit bitbox/ und Broker/ (Standard: Projekt-Root)")
    args = parser.parse_args()

    data_dir = args.data_dir.resolve() if args.data_dir else ROOT
    fx_rates.init(data_dir)

    print("Lade Transaktionen...")
    transactions = load_all_transactions(data_dir)
    print(f"  → {len(transactions)} Transaktionen gesamt\n")

    # FiFo-Engine läuft immer über ALLE Transaktionen (kumulativer Pool)
    engine = FifoEngine()
    engine.process(transactions)

    reports_dir = data_dir / "reports"

    if args.all:
        years = sorted(set(
            t.date.year for t in transactions
            if t.type in (TxType.BUY, TxType.SELL)
        ))
        for year in years:
            _generate_report(transactions, engine, year, args.csv, args.nachweis, reports_dir)
    else:
        _generate_report(transactions, engine, args.year, args.csv, args.nachweis, reports_dir)


def _generate_report(transactions, engine, year, save_csv, nachweis, reports_dir):
    report = TaxReport(
        all_transactions=transactions,
        sell_results=engine.sell_results,
        remaining_lots=engine.remaining_lots(),
        warnings=engine.warnings,
        year=year,
    )

    text = report.print_report()
    print(text)

    year_label = str(year) if year else "gesamt"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Text-Report speichern
    txt_path = reports_dir / f"steuerreport_{year_label}.txt"
    txt_path.write_text(text, encoding="utf-8")
    print(f"\n  Report gespeichert: {txt_path}")

    if save_csv:
        saved = report.save_csv(reports_dir)
        for p in saved:
            print(f"  CSV gespeichert:    {p}")

    # noKYC-Intern-Report (getrennte Datei, NICHT für Finanzamt)
    nokyc_text = report.nokYC_report()
    if nokyc_text:
        nokyc_path = reports_dir / f"nokyc_intern_{year_label}.txt"
        nokyc_path.write_text(nokyc_text, encoding="utf-8")
        print(f"  noKYC intern:       {nokyc_path}  ← NUR INTERN, nicht für Finanzamt")

    if nachweis and year:
        nachweis_path = reports_dir / f"steuernachweis_{year}.txt"
        generate_tax_free_proof(
            all_transactions=transactions,
            sell_results=engine.sell_results,
            remaining_lots=engine.remaining_lots(),
            year=year,
            output_path=nachweis_path,
        )
        print(f"  Nachweis gespeichert: {nachweis_path}")


if __name__ == "__main__":
    main()
