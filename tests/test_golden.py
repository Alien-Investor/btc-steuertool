"""Golden-Tests: Reports für examples/ müssen byte-genau dem Snapshot entsprechen.

Der Snapshot in tests/golden/ wurde mit `--all --nachweis --csv` erzeugt. Jede
Abweichung ist entweder ein Fehler oder eine gewollte Änderung — dann den Snapshot
bewusst neu erzeugen (siehe unten) und den Diff im Commit begründen.
Einzige Normalisierung: die Zeile „Erstellt am" (Tagesdatum des Laufs).

Aufruf:  python -m unittest discover tests      (oder pytest, falls installiert)
Snapshot neu:  python tests/test_golden.py --update
"""
from __future__ import annotations
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / "golden"
sys.path.insert(0, str(ROOT))

_CREATED = re.compile(rb"^(\s*Erstellt am:\s*).*$", re.MULTILINE)


def _normalize(data: bytes) -> bytes:
    return _CREATED.sub(rb"\1<DATUM>", data)


def _run(data_dir: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "src.main", "--all", "--nachweis", "--csv", "--data-dir", str(data_dir)],
        cwd=ROOT, check=True, capture_output=True,
    )
    return data_dir / "reports"


def _examples_copy(tmp: str, with_fx_cache: bool = True) -> Path:
    data = Path(tmp) / "data"
    shutil.copytree(ROOT / "examples", data, ignore=shutil.ignore_patterns("reports"))
    if not with_fx_cache:
        (data / "fx_cache.json").unlink()
    return data


class GoldenReports(unittest.TestCase):
    def test_examples_match_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = _run(_examples_copy(tmp))
            produced = sorted(p.name for p in reports.iterdir())
            self.assertEqual(produced, sorted(p.name for p in GOLDEN.iterdir()))
            for name in produced:
                with self.subTest(report=name):
                    self.assertEqual(_normalize((reports / name).read_bytes()),
                                     _normalize((GOLDEN / name).read_bytes()))

    def test_ecb_table_gives_same_numbers_as_fx_cache(self):
        """Ohne fx_cache.json rechnet die EZB-Tabelle — Zahlen identisch, nur die
        Quellenangabe im Nachweis kommt hinzu."""
        with tempfile.TemporaryDirectory() as tmp:
            reports = _run(_examples_copy(tmp, with_fx_cache=False))
            for p in reports.iterdir():
                got = _normalize(p.read_bytes())
                if p.name.startswith("steuernachweis_"):
                    self.assertIn("Euro-Referenzkurse der Europäischen".encode(), got)
                    got = re.sub(rb"    - Fremdw\xc3\xa4hrung in EUR umgerechnet:.*?\)\n", b"",
                                 got, flags=re.DOTALL)
                with self.subTest(report=p.name):
                    self.assertEqual(got, _normalize((GOLDEN / p.name).read_bytes()))


class FxRates(unittest.TestCase):
    def setUp(self):
        from src import fx_rates
        self.fx = fx_rates
        fx_rates.init(Path(tempfile.gettempdir()) / "kein-datenverzeichnis")

    def test_known_values(self):
        # Gegen die frankfurter-API geprüft (02.10.2026), 5 signifikante Stellen
        self.assertEqual(self.fx.eur_rate_for_date(date(2023, 8, 15), "USD"), Decimal("0.91525"))
        self.assertEqual(self.fx.eur_rate_for_date(date(2025, 11, 14), "CHF"), Decimal("1.0887"))
        self.assertEqual(str(self.fx.eur_rate_for_date(date(2024, 4, 1), "CHF")), "1.024")

    def test_weekend_and_holiday_use_last_published_rate(self):
        self.assertEqual(self.fx.eur_rate_for_date(date(2021, 3, 6), "CHF"),   # Samstag
                         self.fx.eur_rate_for_date(date(2021, 3, 5), "CHF"))
        self.assertEqual(self.fx.eur_rate_for_date(date(2019, 12, 25), "USD"),  # Weihnachten
                         self.fx.eur_rate_for_date(date(2019, 12, 24), "USD"))

    def test_after_table_end_fails_loudly(self):
        last = self.fx.table_range()[1]
        with self.assertRaises(RuntimeError):
            self.fx.eur_rate_for_date(date(last.year + 1, 1, 1), "USD")

    def test_unknown_currency_fails_loudly(self):
        with self.assertRaises(RuntimeError):
            self.fx.eur_rate_for_date(date(2024, 1, 2), "GBP")

    def test_no_network_code_in_engine(self):
        for p in (ROOT / "src").rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            with self.subTest(file=p.name):
                self.assertNotRegex(text, r"^\s*(import|from)\s+(requests|urllib|http|socket)\b")


if __name__ == "__main__":
    if "--update" in sys.argv:
        with tempfile.TemporaryDirectory() as tmp:
            reports = _run(_examples_copy(tmp))
            shutil.rmtree(GOLDEN, ignore_errors=True)
            shutil.copytree(reports, GOLDEN)
        print(f"Snapshot neu geschrieben: {GOLDEN}")
    else:
        unittest.main()
