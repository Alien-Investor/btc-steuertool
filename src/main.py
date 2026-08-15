#!/usr/bin/env python3
"""BTC Steuertool — CLI-Einstieg."""
from __future__ import annotations
import argparse
import fnmatch
import re
import sys
from pathlib import Path

# Projekt-Root ist das Verzeichnis über src/
ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(ROOT))

from src.parsers import bitbox, broker_21bitcoin, broker_bison, broker_swissquote, broker_strike, broker_pocket, manual_sales, manual_buys, bisq
import src.parsers as parsers
from src.fifo_engine import FifoEngine
from src.tax_report import TaxReport
from src.formal_report import generate_tax_free_proof
from src.models import TxType, de_date
import src.fx_rates as fx_rates


# Dateien, die an Steuerberater und Finanzamt gehen dürfen. Die Einstufung gehört
# hierher, wo die Reports auch benannt werden — nicht in eine Präfix-Liste im HTML
# der GUI (H5). Sonst reist ein später hinzugefügtes internes Artefakt so lange
# ungekennzeichnet mit, bis jemand daran denkt, ein anderes Repo anzufassen.
OFFICIAL_REPORT_PREFIXES = ("steuerreport_", "steuernachweis_", "kaeufe_", "verkaeufe_")


def is_internal_report(name: str) -> bool:
    """Fail closed: was nicht ausdrücklich als offiziell benannt ist, gilt als intern."""
    return not name.startswith(OFFICIAL_REPORT_PREFIXES)


def _find(directory: Path, pattern: str) -> list[Path]:
    """Case-insensitive Datei-Suche (SA2-07).

    `Path.glob` ist auf Linux case-sensitiv: `bisq*.csv` findet `Bisq_2024.csv`
    nicht, `Pocket*.csv` nicht `pocket_2025.csv`, und keiner der Globs findet
    eine Datei mit Endung `.CSV` (Windows-Export, Android-Downloads). Betroffen
    war jeder Broker-Glob — die Datei fiel aus dem FiFo-Pool, und beim
    noKYC-Broker Bisq wäre sie zusätzlich in den offiziellen Report gerutscht.

    Sortierung bewusst nach `p.name` (nicht kleingeschrieben), damit die
    Reihenfolge — und damit die Dedup-Präzedenz in `_dedup_files` — dieselbe
    bleibt wie beim vorherigen `sorted(directory.glob(...))`.
    """
    if not directory.exists():
        return []
    rx = re.compile(fnmatch.translate(pattern), re.IGNORECASE)
    return sorted(
        (p for p in directory.iterdir() if p.is_file() and rx.match(p.name)),
        key=lambda p: p.name,
    )


def _find_dir(parent: Path, name: str) -> Path | None:
    """Unterverzeichnis case-insensitiv suchen (SA2-04).

    `bitbox/NoKYC/` wurde sonst gar nicht gefunden: die noKYC-Wallets fielen
    komplett aus dem Lauf, ohne ein Wort. Und läge derselbe Ordner unter einem
    Namen, den `bitbox.py` nicht als noKYC erkennt, gingen die Bewegungen in
    die Finanzamt-Dokumente — der Fehler zeigt also Richtung Offenlegung.
    """
    if not parent.exists():
        return None
    for p in sorted(parent.iterdir(), key=lambda p: p.name):
        if p.is_dir() and p.name.lower() == name.lower():
            return p
    return None


def _dedup_files(per_file: list[tuple[str, list]], label: str, internal: bool = False) -> list:
    """Erkennt identische Transaktionen über mehrere Export-Dateien desselben
    Brokers (überlappende Exporte, z.B. Jahres- + Gesamtexport) und zählt sie
    nur einmal. Innerhalb EINER Datei wird nicht dedupliziert — dort sind
    identische Zeilen echte, getrennte Trades."""
    seen: set = set()
    result = []
    for fname, txs in per_file:
        dropped = 0
        file_keys = []
        for tx in txs:
            key = (tx.tx_id, tx.date, tx.type, str(tx.btc_amount), str(tx.eur_amount))
            if key in seen:
                dropped += 1
            else:
                result.append(tx)
            file_keys.append(key)
        seen.update(file_keys)
        if dropped:
            # Der Dateiname ist hier ein privates Label (Wallet-Name!) und wird im
            # Finanzamt-Kanal redigiert — die Warnung selbst bleibt aber sichtbar,
            # sie ist eine methodisch relevante Angabe (SA2-06).
            parsers.warn_fmt(
                "{label}: {n} Transaktion(en) aus {file} übersprungen — "
                "identisch mit einer bereits geladenen Datei (überlappende Exporte?). "
                "Bitte pro Broker nur einen lückenlosen Export verwenden.",
                internal=internal, label=label, n=dropped,
                file=parsers.FileRef(fname, "einer weiteren Datei desselben Brokers"),
            )
    return result


def load_all_transactions(data_dir: Path):
    parsers.reset_warnings()
    transactions = []

    # BitBox-Wallets (KYC) — _find statt glob: .CSV ist über die GUI erreichbar
    # (TYPES.bitbox reicht den Original-Dateinamen durch), fiel aber aus dem Lauf
    bitbox_dir = data_dir / "bitbox"
    nokyc_dir = _find_dir(bitbox_dir, "nokyc")
    loaded_bitbox: set[Path] = set()
    if bitbox_dir.exists():
        per_file = []
        for csv_file in _find(bitbox_dir, "*.csv"):
            txs = bitbox.parse(csv_file)
            per_file.append((csv_file.name, txs))
            loaded_bitbox.add(csv_file)
            print(f"  BitBox {csv_file.stem}: {len(txs)} Transaktionen")
        transactions.extend(_dedup_files(per_file, "BitBox"))

    # BitBox-Wallets (noKYC — bitbox/nokyc/*.csv, Ordnername case-insensitiv)
    if nokyc_dir is not None:
        per_file = []
        for csv_file in _find(nokyc_dir, "*.csv"):
            txs = bitbox.parse(csv_file)
            per_file.append((csv_file.name, txs))
            loaded_bitbox.add(csv_file)
            print(f"  BitBox noKYC {csv_file.stem}: {len(txs)} Transaktionen")
        nokyc_txs = _dedup_files(per_file, "BitBox noKYC", internal=True)
        if nokyc_txs:
            transactions.extend(nokyc_txs)
            print(f"  → {len(nokyc_txs)} noKYC-Wallet-Transaktionen (intern, nicht für Finanzamt)")

    broker_dir = data_dir / "Broker"

    # Broker: 21bitcoin (Dateiname kann variieren, z.B. 21bitcoin-gesamt.csv oder 21bitcoin_name_gesamt.csv)
    btc21_files = _find(broker_dir, "21bitcoin*.csv")
    if btc21_files:
        btc21_txs = _dedup_files([(bf.name, broker_21bitcoin.parse(bf)) for bf in btc21_files], "21bitcoin")
        transactions.extend(btc21_txs)
        print(f"  21bitcoin: {len(btc21_txs)} Transaktionen")

    # Broker: Bison — Liste statt fester Pfad, damit auch bison-csv-gesamt.csv
    # oder Bison-CSV-Gesamt.CSV greift (und zwei Schreibweisen nebeneinander
    # nicht stillschweigend auf eine reduziert werden)
    bison_files = _find(broker_dir, "Bison-CSV-Gesamt.csv")
    if bison_files:
        bison_txs = _dedup_files([(bf.name, broker_bison.parse(bf)) for bf in bison_files], "Bison")
        transactions.extend(bison_txs)
        print(f"  Bison: {len(bison_txs)} Transaktionen")

    # Broker: Swissquote
    sq_files = _find(broker_dir, "Swissquote_CSV-Gesamt.csv")
    if sq_files:
        sq_txs = _dedup_files([(sf.name, broker_swissquote.parse(sf)) for sf in sq_files], "Swissquote")
        transactions.extend(sq_txs)
        print(f"  Swissquote: {len(sq_txs)} Transaktionen")

    # Broker: Strike (mehrere CSV-Dateien möglich)
    strike_files = _find(broker_dir, "strike_*.csv")
    if strike_files:
        strike_txs = _dedup_files([(sf.name, broker_strike.parse(sf)) for sf in strike_files], "Strike")
        transactions.extend(strike_txs)
        print(f"  Strike: {len(strike_txs)} Transaktionen ({len(strike_files)} Dateien)")

    # Broker: Pocket (mehrere CSV-Dateien möglich, z.B. Pocket_-_2025.csv)
    pocket_files = _find(broker_dir, "Pocket*.csv")
    if pocket_files:
        pocket_txs = _dedup_files([(pf.name, broker_pocket.parse(pf)) for pf in pocket_files], "Pocket")
        transactions.extend(pocket_txs)
        print(f"  Pocket: {len(pocket_txs)} Transaktionen ({len(pocket_files)} Dateien)")

    # Broker: Bisq (noKYC P2P, mehrere CSV-Dateien möglich)
    bisq_files = _find(broker_dir, "bisq*.csv")
    if bisq_files:
        bisq_txs = _dedup_files([(bf.name, bisq.parse(bf)) for bf in bisq_files], "Bisq", internal=True)
        transactions.extend(bisq_txs)
        print(f"  Bisq (noKYC): {len(bisq_txs)} Transaktionen ({len(bisq_files)} Dateien)")

    # Manuelle Käufe (noKYC: Robosats, P2P, Bargeld etc.)
    # BEWUSST vor den Verkäufen geladen: beide Parser stempeln 12:00 UTC, also
    # entscheidet bei gleichem Kalendertag sonst die Ladereihenfolge, und ein
    # gleichtägiger Verkauf liefe vor seinem Kauf.
    manual_buys_file = data_dir / "manual_buys.csv"
    if manual_buys_file.exists():
        txs = manual_buys.parse(manual_buys_file)
        transactions.extend(txs)
        print(f"  Manuell (Käufe):   {len(txs)} Transaktionen")

    # Manuelle Verkäufe (private Peer-to-Peer Transaktionen)
    manual_file = data_dir / "manual_sales.csv"
    if manual_file.exists():
        txs = manual_sales.parse(manual_file)
        transactions.extend(txs)
        print(f"  Manuell (Verkäufe): {len(txs)} Transaktionen")

    # Nicht zugeordnete CSVs im Broker-Ordner melden — CLI-Pendant zum GUI-Prinzip
    # "nicht erkannte Dateien sperren die Berechnung" (z.B. falsch benannte
    # Bison-/Swissquote-Datei oder ein Broker ohne Parser)
    consumed = {
        p.name
        for p in btc21_files + bison_files + sq_files + strike_files + pocket_files + bisq_files
    }
    # Pendant für bitbox/: bisher gab es hier gar keinen Auffang-Warner, also
    # verschwand eine ganze Wallet lautlos (WALLET1.CSV, wallet1.txt, ein
    # Unterordner bitbox/2024/). Rekursiv, damit auch Verschachteltes auffällt.
    # Der Nachweis behauptet sonst eine zu kleine Wallet-Anzahl, und die
    # GUI-Dateitabelle zeigt die Datei als akzeptiert an.
    if bitbox_dir.exists():
        for p in sorted(bitbox_dir.rglob("*"), key=lambda p: str(p)):
            if not p.is_file() or p in loaded_bitbox:
                continue
            rel = p.relative_to(bitbox_dir)
            # Versteckte Dateien und Ordner (.DS_Store, .git/, .claude/) sind nie
            # Wallet-Exporte. Ohne diese Ausnahme steht in JEDEM Steuerreport eine
            # Warnung über ein Werkzeug-Artefakt — und eine Warnung, die man
            # gewohnheitsmäßig überliest, schützt niemanden mehr.
            if any(part.startswith(".") for part in rel.parts):
                continue
            # Dateiname unterhalb von nokyc/ nennt ein noKYC-Wallet → nur intern
            in_nokyc = nokyc_dir is not None and nokyc_dir in p.parents
            parsers.warn_fmt(
                "{file}: NICHT geladen — keine BitBox-CSV am erwarteten Ort. "
                "Erwartet werden CSV-Dateien direkt in bitbox/ bzw. bitbox/nokyc/. "
                "Bitte prüfen, ob hier ein Wallet-Export fehlt.",
                internal=in_nokyc,
                file=parsers.FileRef(f"bitbox/{rel}", "Eine Datei im Ordner bitbox/"),
            )

    for p in _find(broker_dir, "*.csv"):
        if p.name not in consumed:
            # Der Dateiname kann eine noKYC-Plattform benennen (robosats-export.csv)
            # → im Finanzamt-Kanal redigiert. Die Liste der erwarteten Namen ist
            # unser eigener Textbaustein und bleibt vollständig stehen.
            parsers.warn_fmt(
                "{file}: keinem Parser zugeordnet — NICHT geladen. "
                "Erwartete Namen: 21bitcoin*.csv, Bison-CSV-Gesamt.csv, "
                "Swissquote_CSV-Gesamt.csv, strike_*.csv, Pocket*.csv, bisq*.csv.",
                file=parsers.FileRef(f"Broker/{p.name}", "Eine Datei im Ordner Broker/"), internal=False,
            )

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
        # Jahres-Zuordnung nach deutschem Kalenderdatum (Europe/Berlin), nicht UTC
        years = sorted(set(
            de_date(t.date).year for t in transactions
            if t.type in (TxType.BUY, TxType.SELL)
        ))
        for year in years:
            _generate_report(transactions, engine, year, args.csv, args.nachweis, reports_dir)
    else:
        _generate_report(transactions, engine, args.year, args.csv, args.nachweis, reports_dir)


def _lots_at_year_end(transactions, engine, year):
    """Bestand zum 31.12. des Berichtsjahres (SA2-14).

    Vorher zeigte der Report die Bestände nur, wenn `year == date.today().year` —
    derselbe 2024er-Report sah 2024 anders aus als 2026, und für ein
    abgeschlossenes Jahr fehlte die Bestandsliste ganz. Ein Steuerdokument muss
    aus den Daten allein reproduzierbar sein.

    Ein bloßes Filtern der Rest-Lots nach Kaufdatum reicht NICHT: ein Lot, das
    2025 verkauft wurde, war zum 31.12.2024 noch vorhanden, taucht aber in
    `engine.remaining_lots()` gar nicht mehr auf. Deshalb ein eigener FiFo-Lauf
    über die Transaktionen bis zum Stichtag. Dessen Warnungen werden verworfen —
    sie sind eine Teilmenge des Hauptlaufs und würden sonst doppelt erscheinen.
    """
    if not year:
        return engine.remaining_lots()
    scoped = FifoEngine()
    scoped.process([t for t in transactions if de_date(t.date).year <= year])
    return scoped.remaining_lots()


def _generate_report(transactions, engine, year, save_csv, nachweis, reports_dir):
    # Parser-Warnungen (still verworfene Zeilen wären falsche Reports!) + Engine-Warnungen
    all_warnings = list(parsers.parser_warnings) + list(engine.warnings)

    # Jahresfilter: die Warnungsliste ist global, die Reports sind pro Jahr.
    # Ohne den Filter markierte eine abgebrochene Bisq-Zeile aus 2021 den
    # 2024er-Nachweis als "möglicherweise unvollständig" und erzeugte einen
    # internen Report für ein Jahr ganz ohne noKYC-Vorgänge (SA2-09).
    # year=None heißt "betrifft alle Jahre" (Datei-Ebene, z.B. nicht geladen).
    if year:
        all_warnings = [w for w in all_warnings
                        if getattr(w, "year", None) in (None, year)]

    # Vertraulichkeit: Warnungen zu noKYC-Vorgängen dürfen NICHT in die
    # Dokumente für Steuerberater/Finanzamt. Sie nennen Dateinamen, Daten,
    # Mengen und teils das Wort "noKYC" selbst.
    # Fail closed (H4): eine Warnung ohne Klassifizierung — etwa ein blanker str,
    # den ein künftiger Erzeuger anhängt — gilt als INTERN. `getattr(w, "internal",
    # False)` hätte sie stillschweigend ins Finanzamt-Dokument gelassen; der
    # Standardwert entschied damit in die gefährliche Richtung.
    def _is_internal(w) -> bool:
        return getattr(w, "internal", True)

    internal_warnings = [w for w in all_warnings if _is_internal(w)]
    official_warnings = [w for w in all_warnings if not _is_internal(w)]
    # KEIN Zähl-Hinweis mehr im offiziellen Kanal: jeder Erzeuger einer internen
    # Warnung setzt noKYC-Daten voraus, die Zeile war also ein Ein-Weg-Indikator.
    # Schwerer wog, dass sie unter "WICHTIGE HINWEISE — BITTE VOR VERWENDUNG
    # PRÜFEN" stand und den Nachweis selbst als ungeklärt markierte — auf die
    # naheliegende Rückfrage "welche Hinweise?" gibt es keine vorzeigbare Antwort.
    # Der Nutzer sieht diese Warnungen ohnehin im GUI-Log und im internen Report.

    lots_at_cutoff = _lots_at_year_end(transactions, engine, year)

    report = TaxReport(
        all_transactions=transactions,
        sell_results=engine.sell_results,
        remaining_lots=lots_at_cutoff,
        warnings=official_warnings,
        internal_warnings=internal_warnings,
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
    nokyc_text = report.nokyc_report()
    if nokyc_text:
        nokyc_path = reports_dir / f"nokyc_intern_{year_label}.txt"
        nokyc_path.write_text(nokyc_text, encoding="utf-8")
        print(f"  noKYC intern:       {nokyc_path}  ← NUR INTERN, nicht für Finanzamt")

    if nachweis and year:
        nachweis_path = reports_dir / f"steuernachweis_{year}.txt"
        generate_tax_free_proof(
            all_transactions=transactions,
            sell_results=engine.sell_results,
            remaining_lots=lots_at_cutoff,
            year=year,
            output_path=nachweis_path,
            warnings=official_warnings,
        )
        print(f"  Nachweis gespeichert: {nachweis_path}")


if __name__ == "__main__":
    main()
