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

from src.parsers import bitbox, broker_21bitcoin, broker_bison, broker_swissquote, broker_strike, broker_pocket, manual_sales, manual_buys, bisq, transfer_zuordnung, sammelimport, wallet_export
import src.parsers as parsers
from src.fifo_engine import FifoEngine
from src.tax_report import TaxReport
from src.formal_report import generate_tax_free_proof
import src.wallet_report as wallet_report
from src.models import TxType, de_date, ANY_WALLET, own_wallet, wallet_name, wallet_label
import src.fx_rates as fx_rates


# Dateien, die an Steuerberater und Finanzamt gehen dürfen. Die Einstufung gehört
# hierher, wo die Reports auch benannt werden — nicht in eine Präfix-Liste im HTML
# der GUI (H5). Sonst reist ein später hinzugefügtes internes Artefakt so lange
# ungekennzeichnet mit, bis jemand daran denkt, ein anderes Repo anzufassen.
OFFICIAL_REPORT_PREFIXES = ("steuerreport_", "steuernachweis_", "kaeufe_", "verkaeufe_")


def is_internal_report(name: str) -> bool:
    """Fail closed: was nicht ausdrücklich als offiziell benannt ist, gilt als intern."""
    return not name.startswith(OFFICIAL_REPORT_PREFIXES)


def report_years(transactions, official: bool = False) -> list[int]:
    """Steuerjahre, für die ein Report erzeugt wird (deutsches Kalenderdatum).

    Ein Jahr zählt, sobald darin ein Kauf, ein Verkauf, eine unentgeltliche
    Übertragung oder eine in BTC entrichtete Gebühr liegt — die Gebühr ist eine
    (kleine) Veräußerung, ein Jahr nur mit Wallet-Transfers ist es nicht mehr
    zwingend ohne steuerbaren Vorgang. Die GUI ruft dieselbe Funktion auf und
    leitet die Jahresliste nicht selbst her (Prinzip aus H5).

    `official=True`: nur Jahre mit KYC-Vorgängen — nur sie bekommen Steuerreport, Nachweis und
    CSV. Ein Jahr allein mit noKYC-Vorgängen erzeugte sonst ein leeres offizielles Dokument, das
    schon durch seine Existenz noKYC-Aktivität verriet (Audit v1.4, R2-B6; mit den Wallet-Parsern
    trägt jeder Abgang eine Gebühr, der Fall wurde häufig). Solche Jahre bekommen nur die internen Dateien.
    """
    return sorted(set(
        de_date(t.date).year for t in transactions
        if (t.type in (TxType.BUY, TxType.SELL, TxType.GIFT_OUT) or t.fee_btc > 0)
        and not (official and t.no_kyc)
    ))


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


def _dedup_files(per_file: list[tuple[str, list]], label: str, internal: bool = False, by_source: bool = False) -> list:
    # Klasse immer im Schlüssel (Audit v1.4, R2): ein noKYC-Duplikat verdrängte sonst einen
    # KYC-Kauf aus dem offiziellen Report (Sammelimport mit KYC- und noKYC-Datei)
    """Erkennt identische Transaktionen über mehrere Export-Dateien desselben
    Brokers (überlappende Exporte, z.B. Jahres- + Gesamtexport) und zählt sie
    nur einmal. Innerhalb EINER Datei wird nicht dedupliziert — dort sind
    identische Zeilen echte, getrennte Trades."""
    seen: set = set()
    result = []
    for fname, txs in per_file:
        dropped = 0
        dropped_nokyc = False
        file_keys = []
        for tx in txs:
            # Mengen numerisch vergleichen: 0.01 und 0.01000000 sind dieselbe Transaktion
            key = (tx.tx_id, tx.date, tx.type, str(tx.btc_amount.normalize()), str(tx.eur_amount.normalize()), tx.no_kyc)
            if by_source:
                # Wallet-Exporte (Audit v1.4): eine Batch-TX mit gleichen Beträgen an zwei eigene
                # Wallets ist kein überlappender Export — nur innerhalb derselben Wallet abgleichen
                key += (tx.source,)
            if key in seen:
                dropped += 1
                dropped_nokyc = dropped_nokyc or tx.no_kyc
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
                internal=internal or dropped_nokyc, label=label, n=dropped,
                file=parsers.FileRef(fname, "einer weiteren Datei desselben Brokers"),
            )
    return result


def _bitbox_extras(txs) -> str:
    """Log-Zusatz: was der Parser aus Notiz und Typ abgeleitet hat — die
    Schenkungs-Einstufung hängt an einem Wort in der Wallet-Notiz und soll dem
    Nutzer sofort ins Auge fallen, nicht erst im Report."""
    gifts = sum(1 for t in txs if t.type == TxType.GIFT_OUT)
    fee_only = sum(1 for t in txs if t.type == TxType.TRANSFER_OUT and t.btc_amount == 0 and t.fee_btc > 0)
    parts = []
    if gifts:
        parts.append(f"{gifts} als Schenkung/Spende eingestuft (Wort in der Notiz)")
    if fee_only:
        parts.append(f"{fee_only} wallet-intern, nur Gebühr")
    return f" ({', '.join(parts)})" if parts else ""


def _resolve_manual_wallets(transactions) -> None:
    """Spalte wallet in manual_buys/manual_sales: der geschriebene Name (BitBox-
    Dateiname ohne .csv oder Broker) wird einer eingelesenen Wallet zugeordnet.
    Harter Fehler bei unbekanntem Namen oder falscher Klasse: ein Tippfehler
    ließe das Lot sonst in einer Phantom-Wallet liegen, ein KYC-Kauf in einer
    noKYC-Wallet bräche die Trennung der Bestände."""
    own = [t for t in transactions if t.source != "manual"]
    known = {t.wallet for t in own}
    cls: dict[str, set[bool]] = {}
    for t in own:
        cls.setdefault(t.wallet, set()).add(t.no_kyc)
    for t in transactions:
        if t.source != "manual" or t.wallet in ("manual", ANY_WALLET):
            continue
        datei = "manual_buys.csv" if t.type == TxType.BUY else "manual_sales.csv"
        wallet = transfer_zuordnung.resolve_wallet(t.wallet, known)
        if wallet is None:
            # Nur Wallets derselben Klasse aufzählen: die Meldung kann in einer
            # Bug-Mail landen, und ein KYC-Vorgang soll keine noKYC-Wallet nennen
            same = sorted(wallet_name(w) for w in known if cls.get(w) == {t.no_kyc})
            raise ValueError(
                f"{datei}: Wallet '{t.wallet}' ({de_date(t.date)}, {t.btc_amount} BTC) gehört zu "
                f"keiner eingelesenen Datei. Erlaubt: Dateiname des Wallet-Exports (BitBox, Sparrow …) ohne .csv "
                f"oder ein Broker" + (f" — passend: {', '.join(same)}." if same else ".")
            )
        if cls.get(wallet) and t.no_kyc not in cls[wallet]:
            raise ValueError(
                f"{datei}: Vorgang vom {de_date(t.date)} ({t.btc_amount} BTC) ist "
                f"{'noKYC' if t.no_kyc else 'KYC'}, die Wallet '{t.wallet}' aber nicht — "
                f"KYC- und noKYC-Bestände bleiben strikt getrennt. Bitte Spalte "
                f"{'kyc' if t.type == TxType.BUY else 'no_kyc'} oder wallet prüfen."
            )
        t.wallet = wallet


def _nonempty_lines(path: Path) -> int:
    try:
        return sum(1 for line in path.read_bytes().splitlines() if line.strip())
    except OSError:
        return 0


def _parse_file(label: str, module, path: Path, *, internal: bool = False) -> list:
    """Ruft `module.parse(path)` auf und sorgt für zwei Dinge (Parser-Audit 03.10.2026, B5/A2):

    1. Jeder Abbruch nennt Datei und Ursache in Klartext. Ein `KeyError: 'Type'`
       oder `InvalidOperation` ohne Dateibezug half niemandem — und erreichte die
       GUI als roher Traceback. Der Dateiname ist hier richtig: der Fehler bricht
       den Lauf ab, bevor ein Dokument entsteht, und der Bug-Report der GUI
       übernimmt Fehlermeldungen nicht.
    2. Eine Datei mit Zeilen, aber ohne eine einzige Transaktion und ohne eigene
       Warnung wird gemeldet — das war der stille Totalverlust (Pocket mit BOM,
       umbenannte Spalte). Die Kopfzeilenprüfung fängt die meisten Fälle vorher;
       dies ist das Netz darunter.
    """
    before = len(parsers.parser_warnings)
    try:
        txs = module.parse(path)
    except ValueError as e:
        msg = str(e)
        raise ValueError(msg if path.name in msg else f"{label} {path.name}: {msg}") from None
    except (KeyError, AttributeError, TypeError, IndexError, ArithmeticError, UnicodeDecodeError) as e:
        raise ValueError(
            f"{label} {path.name}: Datei konnte nicht gelesen werden ({type(e).__name__}: {e}). "
            f"Hat der Anbieter das Exportformat geändert oder ist die Datei beschädigt?"
        ) from e
    if not txs and len(parsers.parser_warnings) == before:
        n = _nonempty_lines(path) - 1
        if n > 0:
            parsers.warn_fmt(
                "{label}: {file} enthält {n} Datenzeile(n), aber keine davon ergab eine Transaktion — "
                "bitte prüfen, ob das die richtige Datei ist (Exportformat, Zeitraum).",
                internal=internal, label=label, n=n,
                file=parsers.FileRef(path.name, "eine der eingelesenen Dateien"),
            )
    return txs


def _warn_double_loaded_wallets(sammel_txs: list, all_txs: list) -> None:
    """Dieselbe On-Chain-TX-ID in gleicher Richtung aus dem Sammelimport UND einem
    anderen Export (BitBox, Broker) → dieselbe Wallet ist doppelt geladen, der Bestand
    würde doppelt gezählt. Nur melden — welche Datei weg soll, entscheidet der Nutzer."""
    # Nur innerhalb derselben Klasse vergleichen (Audit v1.4, B3): eine KYC-Warnung, die auf
    # eine noKYC-Quelle zeigt, verriete deren Existenz im offiziellen Dokument
    others: dict[tuple[str, TxType, bool], str] = {}
    sammel_sources = {s.source for s in sammel_txs}     # einmal bilden (Audit v1.4: war quadratisch)
    for t in all_txs:
        if t.tx_id and t.source not in sammel_sources:
            others.setdefault((t.tx_id.lower(), t.type, t.no_kyc), t.source)
    seen: set[tuple[str, str]] = set()
    for t in sammel_txs:
        key = (t.tx_id.lower(), t.type, t.no_kyc)
        if t.tx_id and key in others and (t.source, others[key]) not in seen:
            seen.add((t.source, others[key]))
            parsers.warn_fmt(
                "Sammelimport: Konto '{a}' enthält dieselbe Transaktions-ID in gleicher Richtung wie {b} — "
                "ist diese Wallet doppelt geladen (Sammelimport UND eigener Export)? Dann eine der "
                "Quellen entfernen, sonst zählt der Bestand doppelt.",
                internal=t.no_kyc, a=t.source,
                b=parsers.FileRef(others[key], "eine andere eingelesene Quelle") if own_wallet(others[key]) else others[key],
            )


def _resolve_dst(transactions) -> None:
    """Doppelte Stunde der Winterzeit-Umstellung: eine Ortszeit (Electrum, alte Sparrow-Exporte)
    zwischen 02:00 und 03:00 gibt es zweimal. Trägt dieselbe TX-ID in einer anderen Quelle genau
    die andere Lesart, gilt diese — sonst lief ein Abgang vor dem Eingang seiner Lots (Audit v1.4)."""
    if not parsers.dst_candidates:
        return
    by_txid: dict[str, set] = {}
    for t in transactions:
        if t.tx_id:
            by_txid.setdefault(t.tx_id.lower(), set()).add((t.source, t.date))
    alts = {id(tx): alt for tx, alt in parsers.dst_candidates}
    for tx, alt in parsers.dst_candidates:
        if tx.tx_id and any(src != tx.source and d == alt for src, d in by_txid.get(tx.tx_id.lower(), ())):
            tx.date = alt
            del alts[id(tx)]
    # Danach die Reihenfolge der Datei: Electrum und Sparrow schreiben aufsteigend nach Zeit
    # (Electrum wallet.py „sort by timestamp“, Sparrow nach Blockhöhe). Eine mehrdeutige Zeile, die
    # jetzt vor ihrer Vorgängerin läge, nimmt die andere Lesart.
    prev: dict[str, object] = {}
    for t in transactions:
        if not t.source.startswith(("electrum:", "sparrow:")):
            continue
        p = prev.get(t.source)
        if p is not None and t.date < p and id(t) in alts and alts[id(t)] >= p:
            t.date = alts.pop(id(t))
        prev[t.source] = t.date if p is None else max(p, t.date)


def _number_ledger_accounts(txs) -> None:
    """Ledger-Konten über ALLE Dateien gemeinsam benennen (Audit v1.4, R2-F2/F3, N4).

    Gleichnamige Konten mit verschiedenem xpub („Bitcoin 1“ auf zwei Geräten) werden nach xpub
    sortiert durchnummeriert: „Bitcoin 1“, „Bitcoin 1 (2)“ — gleich in jeder Datei, egal welche
    Konten ein Export enthält. Derselbe xpub unter zwei Namen = Konto umbenannt und der alte Export
    liegt noch dabei → Abbruch, der Bestand zählte sonst doppelt."""
    keyed = [(t, parsers.ledger_keys[id(t)]) for t in txs if id(t) in parsers.ledger_keys]
    if not keyed:
        return
    names_of: dict[str, set[str]] = {}
    keys_of: dict[str, set[str]] = {}
    for _, (name, key) in keyed:
        names_of.setdefault(key, set()).add(name)
        keys_of.setdefault(name, set()).add(key)
    renamed = sorted(n for k, ns in names_of.items() if len(ns) > 1 for n in ns)
    if renamed:
        raise ValueError(
            f"Ledger: dasselbe Konto (xpub) steht unter mehreren Namen in den Exporten: {', '.join(renamed)}. "
            f"Vermutlich umbenannt — bitte nur den aktuellen Export verwenden, sonst zählt der Bestand doppelt. "
            f"Berechnung abgebrochen."
        )
    taken = set(keys_of)
    final: dict[str, str] = {}
    for name in sorted(keys_of):
        for i, key in enumerate(sorted(keys_of[name]), 1):
            label, n = name, i
            while i > 1 and (label == name or label in taken):
                label = f"{name} ({n})"
                n += 1
            taken.add(label)
            final[key] = label
    for t, (_, key) in keyed:
        t.source = t.wallet = f"ledger:{final[key]}"


def _check_same_wallet_twice(txs) -> None:
    """Dieselbe Wallet unter zwei Dateinamen (Jahres- und Gesamtexport, dieselbe Seed in Sparrow
    UND Electrum, eine Datei zweimal im ZIP): der Dedup arbeitet je Wallet, also zählte der Bestand
    doppelt (Audit v1.4, R2-F3/M1).

    - Gleicher Abgang (TX-ID, Betrag, Gebühr) in zwei Wallets derselben Klasse → Abbruch: eine
      Ausgabe gehört genau einer Wallet.
    - Nur gleiche Eingänge, und die kleinere Wallet steckt vollständig in der anderen → Hinweis:
      eine reine Empfangs-Wallet, zweimal exportiert, sieht genauso aus wie wiederholte Batch-
      Auszahlungen mit gleichen Beträgen an zwei eigene Wallets (Zufallstest fuzz3)."""
    keys_of: dict[str, set] = {}
    out_of: dict[tuple, set[str]] = {}
    nokyc: dict[str, bool] = {}
    for t in txs:
        if not t.tx_id or t.type not in (TxType.TRANSFER_IN, TxType.TRANSFER_OUT, TxType.GIFT_OUT):
            continue
        key = (t.no_kyc, t.tx_id.lower(), t.type, t.btc_amount.normalize(), t.fee_btc.normalize())
        keys_of.setdefault(t.source, set()).add(key)
        nokyc[t.source] = t.no_kyc
        if t.type != TxType.TRANSFER_IN:
            out_of.setdefault(key, set()).add(t.source)
    for key, sources in sorted(out_of.items(), key=lambda kv: str(kv[0])):
        if len(sources) > 1:
            a, b = sorted(sources)[:2]
            raise ValueError(
                f"Die Wallet-Exporte '{wallet_label(a)}' und '{wallet_label(b)}' enthalten denselben Abgang — "
                f"vermutlich dieselbe Wallet doppelt geladen (Jahres- und Gesamtexport, umbenannte Datei, dieselbe "
                f"Wallet aus zwei Programmen oder eine Datei zweimal). Bitte nur einen lückenlosen Export je Wallet "
                f"verwenden, sonst zählt der Bestand doppelt. Berechnung abgebrochen."
            )
    sources = sorted(keys_of)
    for i, a in enumerate(sources):
        for b in sources[i + 1:]:
            small, big = sorted((keys_of[a], keys_of[b]), key=len)
            if len(small) >= 2 and small <= big:
                parsers.warn_fmt(
                    "{a} und {b} enthalten dieselben Eingänge ({n}) — dieselbe Wallet doppelt geladen (Jahres- und "
                    "Gesamtexport, umbenannte Datei)? Dann eine Datei entfernen, sonst zählt der Bestand doppelt. "
                    "Bei Sammelauszahlungen mit gleichen Beträgen an zwei eigene Wallets ist der Hinweis gegenstandslos.",
                    internal=nokyc[a], n=len(small), a=wallet_label(a), b=wallet_label(b),
                )


def _check_wallet_identity(transactions) -> None:
    """Trezor hat keinen xpub in der Datei: zwei Dateien mit gleichem Namen (nach Abstreifen des
    Exportzeitpunkts) sind zwei Exporte desselben Kontos oder zwei Geräte → Hinweis (Audit v1.4)."""
    for source, entries in sorted(parsers.wallet_files.items()):
        files = sorted({f for f, _ in entries})
        if source.startswith("trezor:") and len(files) > 1:
            parsers.warn_fmt(
                "Trezor: {n} Dateien ergeben dieselbe Wallet{wallet} (Name ohne Exportzeitpunkt). Gehören sie zu "
                "verschiedenen Konten oder Geräten, die Dateien unterschiedlich benennen — sonst rechnet das Tool "
                "sie als einen Bestand.",
                internal=any(nk for _, nk in entries), n=len(files),
                wallet=parsers.FileRef(f" „{wallet_name(source)}“", ""),
            )


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
            txs = _parse_file("BitBox", bitbox, csv_file)
            per_file.append((csv_file.name, txs))
            loaded_bitbox.add(csv_file)
            print(f"  BitBox {csv_file.stem}: {len(txs)} Transaktionen{_bitbox_extras(txs)}")
        transactions.extend(_dedup_files(per_file, "BitBox"))

    # BitBox-Wallets (noKYC — bitbox/nokyc/*.csv, Ordnername case-insensitiv)
    if nokyc_dir is not None:
        per_file = []
        for csv_file in _find(nokyc_dir, "*.csv"):
            txs = _parse_file("BitBox", bitbox, csv_file, internal=True)
            per_file.append((csv_file.name, txs))
            loaded_bitbox.add(csv_file)
            print(f"  BitBox noKYC {csv_file.stem}: {len(txs)} Transaktionen{_bitbox_extras(txs)}")
        nokyc_txs = _dedup_files(per_file, "BitBox noKYC", internal=True)
        if nokyc_txs:
            transactions.extend(nokyc_txs)
            print(f"  → {len(nokyc_txs)} noKYC-Wallet-Transaktionen (intern, nicht für Finanzamt)")

    # Weitere Wallet-Software (v1.4): Sparrow, Electrum, Trezor Suite, Ledger Live —
    # wallets/*.csv (KYC) und wallets/nokyc/*.csv, Programm wird an der Kopfzeile erkannt
    wallets_dir = data_dir / "wallets"
    wallets_nokyc = _find_dir(wallets_dir, "nokyc")
    loaded_wallets: set[Path] = set()
    parsed: list[tuple[bool, list]] = []
    for folder, internal in ((wallets_dir, False), (wallets_nokyc, True)):
        if folder is None or not folder.is_dir():
            continue
        per_file = []
        for csv_file in _find(folder, "*.csv"):
            if csv_file.name.startswith("."):
                continue    # ._cold.csv (macOS), versteckte Dateien: nie ein Export (wie bei bitbox/)
            txs = _parse_file("Wallet-Export", wallet_export, csv_file, internal=internal)
            per_file.append((csv_file.name, txs))
            loaded_wallets.add(csv_file)
            kinds = sorted({t.source.split(":", 1)[0] for t in txs})
            print(f"  Wallet {'noKYC ' if internal else ''}{csv_file.stem} ({', '.join(kinds) or '–'}): "
                  f"{len(txs)} Transaktionen{_bitbox_extras(txs)}")
        parsed.append((internal, per_file))
    # Ledger-Namen erst nach allen Dateien vergeben (über beide Ordner), dann je Wallet abgleichen
    _number_ledger_accounts([t for _, per_file in parsed for _, txs in per_file for t in txs])
    wallet_txs: list = []
    for internal, per_file in parsed:
        wallet_txs.extend(_dedup_files(per_file, "Wallet-Export noKYC" if internal else "Wallet-Export",
                                       internal=internal, by_source=True))
    _check_same_wallet_twice(wallet_txs)
    transactions.extend(wallet_txs)

    broker_dir = data_dir / "Broker"

    # Broker: 21bitcoin (Dateiname kann variieren, z.B. 21bitcoin-gesamt.csv oder 21bitcoin_name_gesamt.csv)
    btc21_files = _find(broker_dir, "21bitcoin*.csv")
    if btc21_files:
        btc21_txs = _dedup_files([(bf.name, _parse_file("21bitcoin", broker_21bitcoin, bf)) for bf in btc21_files], "21bitcoin")
        transactions.extend(btc21_txs)
        print(f"  21bitcoin: {len(btc21_txs)} Transaktionen")

    # Broker: Bison — Liste statt fester Pfad, damit auch bison-csv-gesamt.csv
    # oder Bison-CSV-Gesamt.CSV greift (und zwei Schreibweisen nebeneinander
    # nicht stillschweigend auf eine reduziert werden)
    bison_files = _find(broker_dir, "Bison-CSV-Gesamt.csv")
    if bison_files:
        bison_txs = _dedup_files([(bf.name, _parse_file("Bison", broker_bison, bf)) for bf in bison_files], "Bison")
        transactions.extend(bison_txs)
        print(f"  Bison: {len(bison_txs)} Transaktionen")

    # Broker: Swissquote
    sq_files = _find(broker_dir, "Swissquote_CSV-Gesamt.csv")
    if sq_files:
        sq_txs = _dedup_files([(sf.name, _parse_file("Swissquote", broker_swissquote, sf)) for sf in sq_files], "Swissquote")
        transactions.extend(sq_txs)
        print(f"  Swissquote: {len(sq_txs)} Transaktionen")

    # Broker: Strike (mehrere CSV-Dateien möglich)
    strike_files = _find(broker_dir, "strike_*.csv")
    if strike_files:
        strike_txs = _dedup_files([(sf.name, _parse_file("Strike", broker_strike, sf)) for sf in strike_files], "Strike")
        transactions.extend(strike_txs)
        print(f"  Strike: {len(strike_txs)} Transaktionen ({len(strike_files)} Dateien)")

    # Broker: Pocket (mehrere CSV-Dateien möglich, z.B. Pocket_-_2025.csv)
    pocket_files = _find(broker_dir, "Pocket*.csv")
    if pocket_files:
        pocket_txs = _dedup_files([(pf.name, _parse_file("Pocket", broker_pocket, pf)) for pf in pocket_files], "Pocket")
        transactions.extend(pocket_txs)
        print(f"  Pocket: {len(pocket_txs)} Transaktionen ({len(pocket_files)} Dateien)")

    # Broker: Bisq (noKYC P2P, mehrere CSV-Dateien möglich)
    bisq_files = _find(broker_dir, "bisq*.csv")
    if bisq_files:
        bisq_txs = _dedup_files([(bf.name, _parse_file("Bisq", bisq, bf, internal=True)) for bf in bisq_files], "Bisq", internal=True)
        transactions.extend(bisq_txs)
        print(f"  Bisq (noKYC): {len(bisq_txs)} Transaktionen ({len(bisq_files)} Dateien)")

    # Sammelimport: CoinTracking-/Blockpit-Exporte (viele Börsen in einer Datei).
    # Erkennung am Inhalt; Dateiname nur für die Zuordnung (und „nokyc" im Namen →
    # alles intern). Format noch nicht an echten Exporten bestätigt — der Parser
    # warnt sichtbar je Datei.
    sammel_files = [p for pat in ("cointracking*.csv", "blockpit*.csv", "sammelimport*.csv")
                    for p in _find(broker_dir, pat)]
    if sammel_files:
        sammel_txs = _dedup_files(
            [(sf.name, _parse_file("Sammelimport", sammelimport, sf, internal="nokyc" in sf.name.lower()))
             for sf in sammel_files], "Sammelimport")
        transactions.extend(sammel_txs)
        print(f"  Sammelimport (CoinTracking/Blockpit): {len(sammel_txs)} Transaktionen ({len(sammel_files)} Dateien)")
        _warn_double_loaded_wallets(sammel_txs, transactions)

    # Manuelle Käufe (noKYC: Robosats, P2P, Bargeld etc.)
    # BEWUSST vor den Verkäufen geladen: beide Parser stempeln 12:00 UTC, also
    # entscheidet bei gleichem Kalendertag sonst die Ladereihenfolge, und ein
    # gleichtägiger Verkauf liefe vor seinem Kauf.
    # _find statt fester Pfad (A6): Manual_Sales.csv wurde auf Linux still ignoriert.
    root_consumed: set[str] = set()
    for manual_buys_file in _find(data_dir, "manual_buys.csv"):
        txs = _parse_file("manual_buys.csv", manual_buys, manual_buys_file, internal=True)
        transactions.extend(txs)
        root_consumed.add(manual_buys_file.name)
        print(f"  Manuell (Käufe):   {len(txs)} Transaktionen")

    # Manuelle Verkäufe (private Peer-to-Peer Transaktionen)
    for manual_file in _find(data_dir, "manual_sales.csv"):
        txs = _parse_file("manual_sales.csv", manual_sales, manual_file)
        transactions.extend(txs)
        root_consumed.add(manual_file.name)
        print(f"  Manuell (Verkäufe): {len(txs)} Transaktionen")

    # Eigene Wallet mit gleichem Namen in KYC UND noKYC (Audit v1.4, B1): die Übertrags-
    # Zuordnung hielte sie für dieselbe Wallet, ein Übertrag noKYC → KYC würde nicht als
    # Kreuzfall erkannt und stünde mit Datum und Betrag im Nachweis. Harter Abbruch.
    # Gilt für alle Quellen außer „manual“ (manual_buys trägt beide Klassen): auch Sammelimport-
    # Konten gleichen Namens in KYC- und noKYC-Datei galten sonst als eine Wallet (Audit v1.4, R2-B3)
    _classes: dict[str, set[bool]] = {}
    for t in transactions:
        if t.source != "manual":
            _classes.setdefault(t.source, set()).add(t.no_kyc)
    _both = sorted(w for w, c in _classes.items() if len(c) == 2)
    if not _both:
        _check_wallet_identity(transactions)    # erst nach der Klassenprüfung (deren Meldung ist die genauere)
    if _both:
        raise ValueError(
            f"Wallet-Name kommt im KYC- und im noKYC-Bestand vor: {', '.join(wallet_name(w) for w in _both)}. "
            f"Bitte eine der beiden Dateien umbenennen (bei Ledger das Konto in Ledger Wallet, beim Sammelimport "
            f"das Konto) — "
            f"sonst lassen sich die Bestände nicht sicher trennen. Berechnung abgebrochen."
        )

    # Spalte wallet in manual_*.csv gegen die eingelesenen Wallets auflösen
    _resolve_manual_wallets(transactions)

    # Manuelle Übertrags-Zuordnung (walletbezogenes FiFo, BMF Rn. 90)
    for zuordnung in _find(data_dir, transfer_zuordnung.FILENAME):
        rows = transfer_zuordnung.parse(zuordnung)
        parsers.manual_links.extend(rows)
        root_consumed.add(zuordnung.name)
        print(f"  Übertrags-Zuordnung: {len(rows)} Zeilen")

    # Auffang-Warner fürs Wurzelverzeichnis (A6): eine CSV mit anderem Namen
    # (manual-sales.csv, verkaeufe.csv) verschwand bisher ohne ein Wort.
    for p in _find(data_dir, "*.csv"):
        if p.name not in root_consumed:
            parsers.warn_fmt(
                "{file}: keinem Parser zugeordnet — NICHT geladen. Im Hauptordner werden nur "
                "manual_buys.csv, manual_sales.csv und transfer_zuordnung.csv gelesen; Broker-Exporte "
                "gehören nach Broker/, BitBox-Exporte nach bitbox/.",
                file=parsers.FileRef(p.name, "Eine Datei im Hauptordner"), internal=False,
            )

    # Nicht zugeordnete CSVs im Broker-Ordner melden — CLI-Pendant zum GUI-Prinzip
    # "nicht erkannte Dateien sperren die Berechnung" (z.B. falsch benannte
    # Bison-/Swissquote-Datei oder ein Broker ohne Parser)
    consumed = {
        p.name
        for p in btc21_files + bison_files + sq_files + strike_files + pocket_files + bisq_files + sammel_files
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

    if wallets_dir.exists():
        for p in sorted(wallets_dir.rglob("*"), key=lambda p: str(p)):
            if not p.is_file() or p in loaded_wallets:
                continue
            rel = p.relative_to(wallets_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue
            parsers.warn_fmt(
                "{file}: NICHT geladen — keine Wallet-CSV am erwarteten Ort. "
                "Erwartet werden CSV-Dateien direkt in wallets/ bzw. wallets/nokyc/. "
                "Bitte prüfen, ob hier ein Wallet-Export fehlt.",
                internal=wallets_nokyc is not None and wallets_nokyc in p.parents,
                file=parsers.FileRef(f"wallets/{rel}", "Eine Datei im Ordner wallets/"),
            )

    for p in _find(broker_dir, "*.csv"):
        if p.name not in consumed:
            # Der Dateiname kann eine noKYC-Plattform benennen (robosats-export.csv)
            # → im Finanzamt-Kanal redigiert. Die Liste der erwarteten Namen ist
            # unser eigener Textbaustein und bleibt vollständig stehen.
            parsers.warn_fmt(
                "{file}: keinem Parser zugeordnet — NICHT geladen. "
                "Erwartete Namen: 21bitcoin*.csv, Bison-CSV-Gesamt.csv, "
                "Swissquote_CSV-Gesamt.csv, strike_*.csv, Pocket*.csv, bisq*.csv, "
                "cointracking*.csv, blockpit*.csv (Sammelimport).",
                file=parsers.FileRef(f"Broker/{p.name}", "Eine Datei im Ordner Broker/"), internal=False,
            )

    _resolve_dst(transactions)      # nach allen Quellen: die Gegenseite kann ein Broker sein
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

    engine = run_engine(transactions)

    reports_dir = data_dir / "reports"

    if args.all:
        years = report_years(transactions)
        if not years:
            # Kein Report → die Warnungen stünden nirgends (Audit v1.4, Robustheit B7)
            print("Keine steuerlich relevanten Vorgänge — kein Report erzeugt.")
            for w in parsers.parser_warnings:
                print(f"  ⚠ {w.full}")
        official_years = set(report_years(transactions, official=True))
        for year in years:
            _generate_report(transactions, engine, year, args.csv, args.nachweis, reports_dir,
                             official=year in official_years)
    else:
        _generate_report(transactions, engine, args.year, args.csv, args.nachweis, reports_dir)


def run_engine(transactions, mode: str = "wallet", manual_links=None) -> FifoEngine:
    """Ein FiFo-Lauf über ALLE Transaktionen (kumulativ) — einzige Stelle, an der
    CLI und GUI (web/index.html) die Engine starten. Walletbezogen nach BMF
    06.03.2025 Rn. 62; mode="global" nur für den Vergleich im internen Report."""
    if manual_links is None:
        # von load_all_transactions gesammelt (transfer_zuordnung.csv)
        manual_links = list(parsers.manual_links)
    engine = FifoEngine(mode=mode)
    engine.process(transactions, manual_links)
    if mode == "wallet":
        # Vergleichslauf nach der früheren gemeinsamen Rechnung — nur für die
        # interne Datei wallet_abgleich_intern_JJJJ.txt, nie für ein Finanzamt-Dokument
        engine.comparison = FifoEngine(mode="global")
        engine.comparison.process(transactions)
    return engine


def _lots_at_year_end(transactions, engine, year):
    """Bestand zum 31.12. des Berichtsjahres (SA2-14).

    Ein Steuerdokument muss aus den Daten allein reproduzierbar sein — also der
    Bestand zum Stichtag, nicht der von heute. Die Engine hält ihn im Hauptlauf
    an jeder Jahresgrenze fest; ein zweiter Lauf über die Daten bis zum Stichtag
    zerrisse Überträge über Silvester.
    """
    if not year:
        return engine.remaining_lots()
    return engine.lots_at_year_end(year)


def _generate_report(transactions, engine, year, save_csv, nachweis, reports_dir, official: bool = True):
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
    labels = wallet_report.official_labels(transactions)
    moves = wallet_report.move_rows(engine, year)

    report = TaxReport(
        all_transactions=transactions,
        sell_results=engine.sell_results,
        remaining_lots=lots_at_cutoff,
        warnings=official_warnings,
        internal_warnings=internal_warnings,
        year=year,
        fee_results=engine.fee_results,
        gift_results=engine.gift_results,
        wallet_labels=labels,
        moves=moves,
    )

    text = report.print_report()
    if official:
        print(text)

    year_label = str(year) if year else "gesamt"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Text-Report speichern — nur in Jahren mit KYC-Vorgängen (report_years(official=True))
    if official:
        txt_path = reports_dir / f"steuerreport_{year_label}.txt"
        txt_path.write_text(text, encoding="utf-8")
        print(f"\n  Report gespeichert: {txt_path}")

    if save_csv and official:
        saved = report.save_csv(reports_dir)
        for p in saved:
            print(f"  CSV gespeichert:    {p}")

    # noKYC-Intern-Report (getrennte Datei, NICHT für Finanzamt)
    nokyc_text = report.nokyc_report()
    if nokyc_text:
        nokyc_path = reports_dir / f"nokyc_intern_{year_label}.txt"
        nokyc_path.write_text(nokyc_text, encoding="utf-8")
        print(f"  noKYC intern:       {nokyc_path}  ← NUR INTERN, nicht für Finanzamt")

    # Wallet-Abgleich (echte Wallet-Namen, Vergleich zur gemeinsamen Rechnung)
    comparison = getattr(engine, "comparison", None)
    if year and comparison is not None:
        abgleich_path = reports_dir / f"wallet_abgleich_intern_{year}.txt"
        abgleich_path.write_text(
            wallet_report.internal_report(engine, comparison, transactions, year), encoding="utf-8")
        print(f"  Wallet-Abgleich:    {abgleich_path}  ← NUR INTERN, nicht für Finanzamt")

    if nachweis and year and official:
        nachweis_path = reports_dir / f"steuernachweis_{year}.txt"
        generate_tax_free_proof(
            all_transactions=transactions,
            sell_results=engine.sell_results,
            remaining_lots=lots_at_cutoff,
            year=year,
            output_path=nachweis_path,
            warnings=official_warnings,
            fee_results=engine.fee_results,
            gift_results=engine.gift_results,
            wallet_labels=labels,
            moves=moves,
        )
        print(f"  Nachweis gespeichert: {nachweis_path}")


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        # Gewollte Abbrüche (Format, KYC/noKYC-Sperre …) als Meldung, nicht als Traceback (Audit v1.4, R2-N3)
        print(f"\nFEHLER: {e}", file=sys.stderr)
        sys.exit(2)
