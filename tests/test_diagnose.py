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
            self.assertEqual(diagnose.redact(msg), diagnose._CLASS_TEXT)

    def test_control_characters_removed(self):
        r = diagnose.redact("a\x1b[31mb‮c\nd")
        self.assertTrue(all(c.isprintable() for c in r))


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
        self.assertIn("Date,Pair,Side,Amount,Fee,TxID", text)
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
