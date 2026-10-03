"""Diagnose für Bug-Reports (v1.4): darf nichts Privates enthalten.

Leck-Prüfung an echten Läufen: alle Warnungen der Beispieldaten und der Fixtures sowie
typische Abbruchmeldungen laufen durch src/diagnose.build — danach dürfen weder Dateinamen
noch Beträge, Daten, Uhrzeiten, Transaktions-IDs, Adressen, xpubs noch noKYC-Hinweise im Text
stehen.

Aufruf:  python -m unittest discover tests
"""
from __future__ import annotations
import contextlib
import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.parsers as parsers                    # noqa: E402
from src import diagnose                         # noqa: E402
from src.main import load_all_transactions, run_engine    # noqa: E402

FX = ROOT / "tests" / "fixtures"
EX = ROOT / "examples"

# Was nie in einer Diagnose stehen darf
FORBIDDEN = [
    re.compile(r"\d+[.,]\d{2,}"),                 # Beträge (BTC, EUR)
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),          # Datum
    re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b"),
    re.compile(r"\b\d{1,2}:\d{2}\b"),              # Uhrzeit
    re.compile(r"\b[0-9a-f]{16,}\b", re.I),        # TX-ID
    re.compile(r"\b[xyz]pub\w{4,}", re.I),         # xpub
    re.compile(r"\bbc1\w{6,}", re.I),              # Adresse
    re.compile(r"no[\s_-]?kyc", re.I),
    re.compile(r"\bP2P\b"),
]


def assert_clean(tc, text, names):
    for rx in FORBIDDEN:
        tc.assertIsNone(rx.search(text), f"{rx.pattern} in Diagnose:\n{text}")
    for n in names:
        stem = n.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if len(stem) >= 3:
            tc.assertNotIn(stem.lower(), text.lower(), f"Dateiname {stem!r} in Diagnose")


def run_dir(d: Path):
    with contextlib.redirect_stdout(io.StringIO()):
        txs = load_all_transactions(d)
        engine = run_engine(txs)
    return [str(w) for w in list(parsers.parser_warnings) + list(engine.warnings)
            if not getattr(w, "internal", True)]


class Redact(unittest.TestCase):
    def test_rules(self):
        text = ("Trezor Suite cold_2024.csv Zeile 3: negativer Betrag '-0.08' am 2024-06-01T12:00:00+02:00 "
                "(15.03.2024 14:22), TX 3a7c1f0e9b2d4c6a8e0f1a2b3c4d5e6f, xpub6CatWdiZiodmUeTDp8LT5or8nmbK, "
                "bc1qown7a2l0q9mv5c4y3xk8tq0h6r2w5n9e4d7s3f, 10000000 sat, Wallet sparrow:geheim")
        r = diagnose.redact(text, ["cold_2024.csv", "cold_2024"])
        assert_clean(self, r, ["cold_2024.csv", "geheim.csv"])
        self.assertIn("Zeile 3", r)                 # Zeilennummern bleiben (Format-Fragen)
        self.assertIn("2024", r)                    # das Jahr bleibt
        self.assertIn("negativer Betrag", r)

    def test_class_messages_become_neutral(self):
        for msg in ("Der Vorgang aus dem noKYC-Bestand ist in einer KYC-Wallet angekommen",
                    "Bisq-Trade auf Altcoin-Markt", "Manuell (P2P)"):
            self.assertEqual(diagnose.redact(msg), diagnose.PRIVATE_TEXT)

    def test_control_characters_removed(self):
        r = diagnose.redact("a\x1b[31mb‮c\nd")
        self.assertTrue(all(c.isprintable() for c in r))


class AuditRound3(unittest.TestCase):
    """Angriffe der Datenschutz- und Robustheitsprüfer aus Runde 3 (alle vorher durchgelassen)."""

    def test_data_line_as_header_only_structure(self):
        for h in ("Max Mustermann,DE89 3704 0044 0532 0130 00,max@example.org,+49 170 1234567,Hauptstr. 5",
                  "Mar 15 2024,Kauf,0.5 BTC,1 BTC,12 345 EUR,2N1dP3x9yW8uYv7tRqSpOnMlKj6iHgF5eD,lnbc2500u1pvjluez",
                  "15 Mar 2024;Notiz Erbe Oma;1.234,56;mzBc4XEFSdzCDcTxAgf6EZXgsZWpztRhef"):
            text = diagnose.build({"files": [{"label": "x", "lines": 1, "kb": 1, "header": h}], "names": []})
            for bad in ("Mustermann", "DE89", "example", "1234567", "Hauptstr", "Mar", "0.5", "345", "2N1d",
                        "lnbc", "Erbe", "234", "mzBc"):
                self.assertNotIn(bad, text, f"{bad!r} aus {h!r}")
            self.assertIn("<feld>", text)

    def test_account_and_file_names_in_any_spelling(self):
        import unicodedata
        nfd = unicodedata.normalize("NFD", "Kälte Reserve.csv")
        cases = [(nfd, nfd), ("Cold Storage.csv", "Cold  Storage.csv"), ("Cold\u200bStorage.csv", "Cold\u200bStorage.csv"),
                 ("Notgroschen\u202e.csv", "Notgroschen\u202e.csv")]
        for name, shown in cases:
            r = diagnose.redact(f"Sparrow {shown} Zeile 2: Txid fehlt", [name])
            for part in ("Kälte", "Ka", "Cold", "Storage", "Notgroschen"):
                self.assertNotIn(part.casefold(), r.casefold().replace("<name>", ""), (name, r))
            self.assertIn("Zeile 2", r)

    def test_short_stem_does_not_break_id_redaction(self):
        r = diagnose.redact("Trezor Suite ab.csv Zeile 4: Transaktion abcdef0123456789abcdef… hat Zeilen", ["ab.csv", "ab"])
        self.assertNotIn("cdef0123", r)

    def test_whole_amounts_units_and_dates(self):
        for msg in ("manual_sales.csv: Wallet (2024, 1 BTC) passend: x", "über 300 satoshi am 15. März 2024 um 14.30",
                    "Purchase vom Apr 02 2024 10:00 nicht verarbeitet", "Betrag ,5 und 1. und 20240315"):
            r = diagnose.redact(msg.replace("manual_sales.csv: ", "Datei: "))
            for bad in ("1 BTC", "300", "15.", "März", "14.30", "Apr 02", ",5", "20240315", "0315"):
                self.assertNotIn(bad, r, (msg, r))

    def test_private_errors_and_class_words_one_sentence(self):
        self.assertEqual(diagnose.redact("Sparrow x.csv Zeile 2: Txid fehlt", private=True), diagnose.PRIVATE_TEXT)
        self.assertEqual(diagnose.redact("manual_buys.csv: Spalte kyc unbekannt"), diagnose.PRIVATE_TEXT)

    def test_many_files_fast_and_grouped(self):
        import time
        files = [{"label": "BitBox-Wallet (KYC)", "lines": 10, "kb": 1} for _ in range(400)]
        names = [f"wallet{i}.csv" for i in range(400)]
        t = time.perf_counter()
        text = diagnose.build({"files": files, "names": names, "warnings": [f"Datei wallet{i}.csv Zeile 1: x" for i in range(400)]})
        self.assertLess(time.perf_counter() - t, 2.0)
        self.assertIn("400 Dateien", text)


class AuditRound4(unittest.TestCase):
    """Runde 4: Meldungen nur noch über die Positivliste (Wörter aus den eigenen Meldungstexten)."""

    def test_names_in_any_form_vanish(self):
        for msg, bad in (
            ("BitBox Lena Erbe 15.03.2021.csv Zeile 2, Spalte 'Amount': 'x' ist keine Zahl.", ("Lena", "Erbe", "15.03")),
            ("BitBox Großvater Erbe.csv Zeile 2: ungültig", ("Großvater", "Grossvater")),
            ("Trezor-Wallet „Martin's Sparkonto“ und „Erbe Oma's Konto“: denselben Abgang", ("Martin", "Sparkonto", "Oma")),
            ("Sammelimport x.csv: Depot Erbe Oma 2024: negativer Betrag bei buy (btc=1, eur=5, fee=0)", ("Erbe", "Oma", "=1", "=5")),
            ("Pflichtspalte(n) fehlen. Gelesen: Max Mustermann, DE89 3704 0044 0532 0130 00, max@example.com, 03/15/2024",
             ("Max", "Mustermann", "DE89", "3704", "example", "03/15")),
            ("Zeile 12345678 und Tel 0170-123-45-67, 1 234 567, 5 Bitcoin, Ref 123 456 789",
             ("12345678", "0170", "123", "234", "567", "5 Bitcoin", "456")),
            ("am 15 Mar 2024 und März 2024 und Sep 3", ("Mar", "März", "Sep")),
        ):
            r = diagnose.redact(msg)
            for b in bad:
                self.assertNotIn(b, r, (msg, r))

    def test_own_wording_stays_readable(self):
        r = diagnose.redact("ein Sparrow-Export: 1 Ausgang/Ausgänge im Jahr 2024 ohne bekannte Gebühr — als Übertrag gebucht.")
        self.assertIn("Ausgang/Ausgänge im Jahr 2024 ohne bekannte Gebühr", r)
        self.assertIn("Zeile 3", diagnose.redact("Datei Zeile 3: negativer Betrag"))

    def test_runtime_error_from_nokyc_file_is_private(self):
        """R4-B6: fehlender Wechselkurs (RuntimeError) aus einer noKYC-Sammeldatei."""
        head = '"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"\n'
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "Broker").mkdir()
            (d / "Broker" / "sammelimport_nokyc_1.csv").write_text(
                head + '"Trade","0.01000000","BTC","500","USD","","","Kraken","","","02.10.2030 10:00:00"\n')
            with self.assertRaises(parsers.PrivateError):
                run_dir(d)

    def test_warning_cap_counts_per_channel(self):
        """R4-B9: die Zählung unterdrückter Warnungen darf keine internen mitzählen."""
        parsers.reset_warnings()
        for i in range(parsers._MAX_WARNINGS + 50):
            parsers.warn(f"intern {i}", internal=True)
        parsers.warn("offiziell", internal=False)
        public = [w for w in parsers.parser_warnings if not w.internal]
        self.assertEqual([str(w) for w in public], ["offiziell"])
        parsers.reset_warnings()


class Build(unittest.TestCase):
    def test_hidden_files_only_counted_and_header_of_unknown(self):
        info = {"platform": "Web", "lang": "de", "ran": True, "error": None, "warnings": [],
                "names": ["geheim_nokyc.csv", "x/robosats-export.csv", "kraken_2024.csv"],
                "files": [
                    {"label": "Sparrow/Electrum/Trezor/Ledger (noKYC)", "lines": 12, "kb": 1.2, "hidden": True},
                    {"label": "Bisq (noKYC)", "lines": 3, "kb": 0.4, "hidden": True},
                    {"label": "✗ Nicht erkannt — bitte wählen", "lines": 40, "kb": 3, "hidden": False,
                     "header": "Date,Pair,Side,Amount,Fee,TxID 3a7c1f0e9b2d4c6a8e0f1a2b3c4d5e6f"},
                ]}
        text = diagnose.build(info)
        self.assertIn("weitere Dateien (nicht aufgeschlüsselt): 2", text)
        self.assertIn("6 Felder, Trennzeichen Komma: Date, Pair, Side, Amount, Fee, <feld>", text)
        self.assertNotIn("Bisq", text)
        assert_clean(self, text, info["names"])

    def test_real_runs_examples_and_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            shutil.copytree(EX, d, ignore=shutil.ignore_patterns("reports"))
            (d / "wallets" / "nokyc").mkdir(parents=True)
            for n in ("sparrow.csv", "trezor.csv", "electrum_46.csv"):
                shutil.copy(FX / n, d / "wallets" / f"privat_{n}")
            shutil.copy(FX / "ledger.csv", d / "wallets" / "nokyc" / "versteck.csv")
            names = [p.name for p in d.rglob("*.csv")] + ["fx_cache.json"]
            warnings = run_dir(d)
        self.assertTrue(warnings)
        text = diagnose.build({"platform": "Web", "lang": "de", "ran": True, "error": None,
                               "warnings": warnings, "names": names,
                               "files": [{"label": "x", "lines": 1, "kb": 1, "hidden": False}]})
        assert_clean(self, text, names)

    def test_real_errors(self):
        errors = []
        cases = {
            "wallets/kalt.csv": "Timestamp,Date,Time,Type,Transaction ID,Fee,Fee unit,Address,Label,Amount,Amount unit,Fiat (EUR),Other\n"
                                "1717243200,,,SENT,ab12,0.0001,BTC,x,,-0.08,BTC,,\n",
            "wallets/heiss.csv": "Date (UTC),Label,Value (BTC),Balance (BTC),Fee (BTC),Txid\n"
                                 "2024-01-02 03:04:05,,-0.00000100,0,0.00002100,3a7c1f0e9b2d4c6a8e0f1a2b3c4d5e6f\n",
        }
        for rel, text in cases.items():
            with tempfile.TemporaryDirectory() as tmp:
                d = Path(tmp)
                (d / rel).parent.mkdir(parents=True)
                (d / rel).write_text(text)
                try:
                    run_dir(d)
                except ValueError as e:
                    errors.append((rel, str(e)))
        self.assertEqual(len(errors), 2)
        for rel, err in errors:
            text = diagnose.build({"platform": "Web", "lang": "de", "ran": True, "error": err, "warnings": [],
                                   "names": [rel, rel.rsplit("/", 1)[-1]], "files": []})
            assert_clean(self, text, [rel])
            self.assertIn("Abbruch", text)


if __name__ == "__main__":
    unittest.main()
