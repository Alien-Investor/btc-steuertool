"""Regressionstests zum Security-Audit run-1 (02.10.2026, Offline-App vor dem Release).

Fund 3: kein „KYC/noKYC" in Finanzamt-Dokumenten (Gebühr einer KYC-Wallet ohne erfassten Kauf).
Fund 4: Gutschein-Käufe und Verneinungen sind keine Schenkung.
Fund 5: Warnungen gehören ins deutsche Kalenderjahr, nicht ins UTC-Jahr.
Fund 6: kein „P2P" im Steuernachweis.
Härtung: fx_cache.json mit ungültigem Kurs bricht ab, statt still 0 EUR zu rechnen.

Aufruf:  python -m unittest discover tests
"""
from __future__ import annotations
import json
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tests.test_golden import _examples_copy, _run   # noqa: E402

# Dateien, die ans Finanzamt / den Steuerberater gehen (alles außer nokyc_intern_*)
OFFICIAL = re.compile(r"^(steuerreport|steuernachweis|kaeufe|verkaeufe)_\d{4}\.(txt|csv)$")


def _append(csv_path: Path, line: str) -> None:
    text = csv_path.read_text(encoding="utf-8")
    csv_path.write_text(text.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")


def _official(reports: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in reports.iterdir() if OFFICIAL.match(p.name)}


class OfficialDocsStayClean(unittest.TestCase):
    def test_stock_examples_have_no_nokyc_or_p2p(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = _official(_run(_examples_copy(tmp)))
        self.assertTrue(docs)
        for name, text in docs.items():
            with self.subTest(report=name):
                self.assertNotRegex(text, r"(?i)no-?kyc")
                self.assertNotIn("P2P", text)

    def test_kyc_wallet_fee_without_lots_does_not_mention_nokyc(self):
        # Gebühr einer KYC-Wallet VOR dem ersten KYC-Kauf → Pool leer → Warnung (Fund 3)
        with tempfile.TemporaryDirectory() as tmp:
            data = _examples_copy(tmp)
            _append(data / "bitbox" / "wallet1.csv",
                    "2021-03-01T12:00:00+01:00,sent,10000,satoshi,500,satoshi,"
                    "bc1qexampleauditaaaaaaaaaaaaaaaaaaaaaaaaaa,"
                    "cccc00000000000000000000000000000000000000000000000000000000a001,Übertrag")
            docs = _official(_run(data))
        self.assertIn("steuernachweis_2021.txt", docs)
        flat = " ".join(docs["steuernachweis_2021.txt"].split())   # Nachweis ist umbrochen
        self.assertIn("nicht vollständig FiFo-Lots zugeordnet", flat)
        self.assertIn("Stammt der Bestand dieser Wallet aus einem hier nicht erfassten Kauf?", flat)
        for name, text in docs.items():
            with self.subTest(report=name):
                self.assertNotRegex(text, r"(?i)no-?kyc")


class GiftClassifier(unittest.TestCase):
    def test_gift_words(self):
        from src.parsers.bitbox import is_gift_note
        for note in ("Spende an OpenSats", "Geschenk für Max", "Schenkung an Tochter", "donation", "gift to a friend"):
            with self.subTest(note=note):
                self.assertTrue(is_gift_note(note))
        for note in ("Gift Card Amazon", "Gift-Card Steam", "giftcard", "Geschenk-Gutschein bezahlt",
                     "Geschenkgutschein-Kauf", "kein Geschenk - an eigene Wallet", "Verkauf an Max, kein Geschenk",
                     "not a gift", "Vergiftung", "Konsolidierung", ""):
            with self.subTest(note=note):
                self.assertFalse(is_gift_note(note))


class WarningYear(unittest.TestCase):
    def test_unknown_fee_unit_warning_uses_german_year(self):
        # 01.01.2025 00:30 MEZ = 31.12.2024 23:30 UTC → Warnung gehört in den Report 2025 (Fund 5)
        with tempfile.TemporaryDirectory() as tmp:
            data = _examples_copy(tmp)
            _append(data / "bitbox" / "wallet1.csv",
                    "2025-01-01T00:30:00+01:00,sent,10000,satoshi,300,mbtc,"
                    "bc1qexampleauditbbbbbbbbbbbbbbbbbbbbbbbbbb,"
                    "cccc00000000000000000000000000000000000000000000000000000000a002,Übertrag")
            docs = _official(_run(data))
        flat = " ".join(docs["steuerreport_2025.txt"].split())
        self.assertIn("unbekannter Einheit", flat)
        self.assertIn("am 2025-01-01", flat)
        self.assertNotIn("unbekannter Einheit", docs.get("steuerreport_2024.txt", ""))


class FxOverrideValidation(unittest.TestCase):
    def _fx_with(self, payload) -> object:
        from src import fx_rates
        tmp = Path(tempfile.mkdtemp())
        (tmp / "fx_cache.json").write_text(json.dumps(payload), encoding="utf-8")
        fx_rates.init(tmp)
        return fx_rates

    def test_invalid_rates_fail_loudly(self):
        for payload in ({"2023-08-15:USD": "0"}, {"2023-08-15:USD": "-1"}, {"2023-08-15:USD": "NaN"},
                        {"2023-08-15:USD": "Infinity"}, {"2023-08-15:USD": "abc"}, {"15.08.2023:USD": "0.9"},
                        {"2023-08-15:USD": "100000"}, ["0.9"]):
            with self.subTest(payload=payload):
                fx = self._fx_with(payload)
                with self.assertRaises(RuntimeError):
                    fx.eur_rate_for_date(date(2023, 8, 15), "USD")

    def test_valid_override_is_used_and_flagged(self):
        fx = self._fx_with({"2023-08-15:USD": "0.91525"})
        self.assertEqual(str(fx.eur_rate_for_date(date(2023, 8, 15), "USD")), "0.91525")
        self.assertTrue(fx.used_override)


if __name__ == "__main__":
    unittest.main()
