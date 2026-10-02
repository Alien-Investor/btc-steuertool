"""Regressionstests zum Parser-Audit (03.10.2026): CSV-Robustheit, Encodings, Riesendateien.

Befund damals: fast jeder Parser las Spalten mit `row.get("Spalte", "")`. Eine BOM
oder eine umbenannte Spalte machte daraus still „leer" oder 0 — ganze Dateien
verschwanden (Pocket, Bison, Swissquote), Käufe standen mit 0 BTC im Report (Strike),
Gebühren wurden 0. Dazu: negative Übertragsmengen kippten die Haltefrist, ein
einzelnes Anführungszeichen verschluckte den Dateirest, Warnungen waren ungedeckelt.

Aufruf:  python -m unittest discover tests
"""
from __future__ import annotations
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.parsers as parsers                                            # noqa: E402
from src.parsers import (bitbox, broker_21bitcoin, broker_bison, broker_swissquote,   # noqa: E402
                         broker_strike, broker_pocket, bisq, manual_buys, manual_sales)
from src.main import load_all_transactions as _load                      # noqa: E402


def load_all_transactions(data_dir):
    with contextlib.redirect_stdout(io.StringIO()):     # Lader-Ausgabe nicht in den Testlauf
        return _load(data_dir)
from src.models import Transaction, TxType                               # noqa: E402
from datetime import datetime, timezone                                  # noqa: E402

EX = ROOT / "examples"
BOM = b"\xef\xbb\xbf"

# (Parser, Beispieldatei, Encoding, Spalte, die umbenannt wird)
CASES = [
    (bitbox, EX / "bitbox/wallet1.csv", "utf-8", "Fee"),
    (broker_21bitcoin, EX / "Broker/21bitcoin-gesamt.csv", "utf-8", "fee_amount"),
    (broker_bison, EX / "Broker/Bison-CSV-Gesamt.csv", "utf-8", "Asset"),
    (broker_swissquote, EX / "Broker/Swissquote_CSV-Gesamt.csv", "windows-1252", "Symbol"),
    (broker_strike, EX / "Broker/strike_2024.csv", "utf-8", "Amount BTC"),
    (broker_pocket, EX / "Broker/Pocket_2024.csv", "utf-8", "type"),
    (bisq, EX / "Broker/bisq.csv", "utf-8", "Betrag in BTC"),
    (manual_buys, EX / "manual_buys.csv", "utf-8", "btc_amount"),
    (manual_sales, EX / "manual_sales.csv", "utf-8", "btc_amount"),
]


class _Tmp(unittest.TestCase):
    def setUp(self):
        parsers.reset_warnings()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name: str, data: bytes) -> Path:
        p = self.tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def variant(self, src: Path, encoding: str, transform) -> Path:
        text = src.read_text(encoding=encoding)
        return self.write(src.name, transform(text).encode(encoding))


class BomAndHeader(_Tmp):
    def test_bom_gives_identical_transactions_for_every_parser(self):
        for module, src, enc, _ in CASES:
            with self.subTest(parser=module.__name__):
                parsers.reset_warnings()
                plain = module.parse(src)
                parsers.reset_warnings()
                bommed = module.parse(self.write(src.name, BOM + src.read_bytes()))
                self.assertEqual(plain, bommed)
                self.assertTrue(plain, "Beispieldatei liefert Transaktionen")

    def test_renamed_required_column_is_a_hard_error_naming_file_and_column(self):
        for module, src, enc, column in CASES:
            with self.subTest(parser=module.__name__, column=column):
                parsers.reset_warnings()
                p = self.variant(src, enc, lambda t: t.replace(column, column + "_X", 1))
                with self.assertRaises(ValueError) as ctx:
                    module.parse(p)
                msg = str(ctx.exception)
                self.assertIn(column, msg)
                self.assertTrue(src.name in msg or module in (manual_buys, manual_sales), msg)

    def test_extra_field_in_row_names_the_line(self):
        src = EX / "bitbox/wallet1.csv"
        lines = src.read_text(encoding="utf-8").splitlines()
        lines[2] = lines[2] + ",ueberzaehlig"
        p = self.write("wallet1.csv", "\n".join(lines).encode())
        with self.assertRaises(ValueError) as ctx:
            bitbox.parse(p)
        self.assertIn("Zeile 3", str(ctx.exception))
        self.assertIn("Felder", str(ctx.exception))

    def test_missing_field_in_row_names_the_line(self):
        src = EX / "Broker/Bison-CSV-Gesamt.csv"
        lines = src.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].rsplit(";", 2)[0]      # zwei Felder weg
        p = self.write(src.name, "\n".join(lines).encode())
        with self.assertRaises(ValueError) as ctx:
            broker_bison.parse(p)
        self.assertIn("Zeile 2", str(ctx.exception))

    def test_unbalanced_quote_does_not_swallow_the_rest_of_the_file(self):
        # Vorher: ab dem Anführungszeichen wurde der Dateirest EIN Feld → 9 → 1 Transaktion, still
        src = EX / "bitbox/wallet1.csv"
        lines = src.read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].rsplit(",", 1)[0] + ',"Kauf von 21bitcoin'
        p = self.write("wallet1.csv", "\n".join(lines).encode())
        with self.assertRaises(ValueError) as ctx:
            bitbox.parse(p)
        self.assertRegex(str(ctx.exception), r"Anführungszeichen|Felder")

    def test_bitbox_fraction_of_satoshi_is_rejected(self):
        src = EX / "bitbox/wallet1.csv"
        p = self.variant(src, "utf-8", lambda t: t.replace(",received,1000000,", ",received,1000000.5,", 1))
        with self.assertRaises(ValueError) as ctx:
            bitbox.parse(p)
        self.assertIn("ganze Zahl", str(ctx.exception))


class Encodings(_Tmp):
    def test_latin1_note_in_bitbox_is_reported_with_filename(self):
        src = EX / "bitbox/wallet1.csv"
        data = src.read_bytes().replace(b"Kauf von 21bitcoin", "Kauf für Oma".encode("latin-1"), 1)
        p = self.write("wallet1.csv", data)
        with self.assertRaises(ValueError) as ctx:
            bitbox.parse(p)
        self.assertIn("wallet1.csv", str(ctx.exception))
        self.assertIn("UTF-8", str(ctx.exception))

    def test_utf16_is_named_as_such(self):
        src = EX / "Broker/strike_2024.csv"
        p = self.write(src.name, src.read_text(encoding="utf-8").encode("utf-16"))
        with self.assertRaises(ValueError) as ctx:
            broker_strike.parse(p)
        self.assertIn("UTF-16", str(ctx.exception))

    def test_swissquote_saved_as_utf8_is_read_like_the_original(self):
        src = EX / "Broker/Swissquote_CSV-Gesamt.csv"
        parsers.reset_warnings()
        orig = broker_swissquote.parse(src)
        p = self.write(src.name, src.read_text(encoding="windows-1252").encode("utf-8"))
        parsers.reset_warnings()
        self.assertEqual(orig, broker_swissquote.parse(p))

    def test_swissquote_empty_currency_is_a_hard_error(self):
        src = EX / "Broker/Swissquote_CSV-Gesamt.csv"
        p = self.variant(src, "windows-1252", lambda t: t.replace(";USD", ";", 1))
        with self.assertRaises(ValueError) as ctx:
            broker_swissquote.parse(p)
        self.assertIn("Währung", str(ctx.exception))


class Amounts(_Tmp):
    def _pa(self, text, **kw):
        return parsers.parse_amount(text, label="T", filename="f.csv", line=2, field="x", **kw)

    def test_decimal_rules(self):
        self.assertEqual(self._pa("0.01"), Decimal("0.01"))
        self.assertEqual(self._pa(""), Decimal("0"))
        self.assertEqual(self._pa("-"), Decimal("0"))           # CoinTracking-Leerwert
        self.assertEqual(self._pa("300,00"), Decimal("300.00"))  # eindeutiges Dezimalkomma
        self.assertEqual(self._pa("-1.5"), Decimal("-1.5"))
        self.assertEqual(self._pa("1E-8"), Decimal("1E-8"))
        for bad in ("2,500", "1.300,00", "-1,189.00", "1,2,3", "NaN", "Infinity", "sNaN", "abc", "1e999999", "1e16"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as ctx:
                    self._pa(bad)
                self.assertIn("f.csv Zeile 2", str(ctx.exception))

    def test_thousands_separator_in_strike_is_not_silently_divided(self):
        src = EX / "Broker/strike_2024.csv"
        p = self.variant(src, "utf-8", lambda t: t.replace("-189.00", '"-2,189"', 1))
        with self.assertRaises(ValueError) as ctx:
            broker_strike.parse(p)
        self.assertIn("mehrdeutig", str(ctx.exception))

    def test_nan_fee_in_strike_is_a_clear_error(self):
        src = EX / "Broker/strike_2024.csv"
        p = self.variant(src, "utf-8", lambda t: t.replace(",0.00300000,0,", ",NaN,0,", 1))
        with self.assertRaises(ValueError) as ctx:
            broker_strike.parse(p)
        self.assertIn("Amount BTC", str(ctx.exception))
        self.assertIn("strike_2024.csv Zeile 2", str(ctx.exception))

    def test_negative_transfer_amount_is_rejected_by_the_model(self):
        with self.assertRaises(ValueError):
            Transaction(date=datetime(2024, 1, 1, tzinfo=timezone.utc), type=TxType.TRANSFER_IN,
                        btc_amount=Decimal("-0.004"), eur_amount=Decimal(0), eur_price_per_btc=Decimal(0),
                        fee_eur=Decimal(0), source="bison", tx_id="x", note="")

    def test_negative_bison_deposit_fails_loud(self):
        src = EX / "Broker/Bison-CSV-Gesamt.csv"
        text = src.read_text(encoding="utf-8")
        line = next(l for l in text.splitlines() if "Deposit" in l)
        fields = [f.strip() for f in line.split(";")]
        fields[5] = "-" + fields[5]
        p = self.write(src.name, text.replace(line, "; ".join(fields)).encode())
        with self.assertRaises(ValueError) as ctx:
            broker_bison.parse(p)
        self.assertIn("negativ", str(ctx.exception))


class Timestamps(_Tmp):
    def test_bitbox_timestamp_without_offset_is_rejected(self):
        src = EX / "bitbox/wallet1.csv"
        p = self.variant(src, "utf-8", lambda t: t.replace("2022-05-02T16:00:00+02:00", "2022-05-02T16:00:00", 1))
        with self.assertRaises(ValueError) as ctx:
            bitbox.parse(p)
        self.assertIn("Zeitzone", str(ctx.exception))

    def test_z_suffix_and_offsets_are_handled(self):
        pi = parsers.parse_iso_datetime
        kw = dict(label="T", filename="f", line=1, field="d")
        self.assertEqual(pi("2025-08-14T19:10:57.000Z", **kw), datetime(2025, 8, 14, 19, 10, 57, tzinfo=timezone.utc))
        self.assertEqual(pi("2025-08-14T21:10:57+02:00", **kw), datetime(2025, 8, 14, 19, 10, 57, tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            pi("2025-08-14 19:10:57", **kw)

    def test_pocket_offset_is_honoured_not_truncated(self):
        src = EX / "Broker/Pocket_2024.csv"
        parsers.reset_warnings()
        orig = broker_pocket.parse(src)
        # Dieselben Zeitpunkte als +02:00 geschrieben → identische UTC-Transaktionen
        text = src.read_text(encoding="utf-8")
        import re
        def shift(m):
            dt = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
            from datetime import timedelta
            return (dt + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S") + ".000+02:00"
        p = self.write(src.name, re.sub(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.000Z", shift, text).encode())
        parsers.reset_warnings()
        self.assertEqual([t.date for t in orig], [t.date for t in broker_pocket.parse(p)])


class LoaderAndWarnings(_Tmp):
    def _examples_copy(self) -> Path:
        dst = self.tmp / "data"
        shutil.copytree(EX, dst)
        shutil.rmtree(dst / "reports", ignore_errors=True)
        return dst

    def test_loader_error_names_the_file(self):
        data = self._examples_copy()
        p = data / "Broker/Pocket_2024.csv"
        p.write_text(p.read_text(encoding="utf-8").replace("value.amount", "valueAmount", 1), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_all_transactions(data)
        self.assertIn("Pocket_2024.csv", str(ctx.exception))
        self.assertIn("value.amount", str(ctx.exception))

    def test_file_with_rows_but_no_transaction_is_reported(self):
        data = self._examples_copy()
        (data / "Broker/Pocket_2024.csv").write_text(
            "type,date,value.currency,value.amount,cost.currency,cost.amount,fee.currency,fee.amount,price.amount\n"
            "deposit,2024-06-01T10:00:00.000Z,EUR,65.00,,,,,\n", encoding="utf-8")
        load_all_transactions(data)
        msgs = [w.full for w in parsers.parser_warnings]
        self.assertTrue(any("Pocket_2024.csv" in m and "keine davon ergab eine Transaktion" in m for m in msgs), msgs)

    def test_manual_sales_is_found_case_insensitively_and_unknown_root_csv_is_reported(self):
        data = self._examples_copy()
        (data / "manual_sales.csv").rename(data / "Manual_Sales.csv")
        (data / "verkaeufe-alt.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        txs = load_all_transactions(data)
        self.assertTrue(any(t.source == "manual" and t.type == TxType.SELL for t in txs))
        msgs = [w.full for w in parsers.parser_warnings]
        self.assertTrue(any("verkaeufe-alt.csv" in m and "NICHT geladen" in m for m in msgs), msgs)

    def test_warning_cap_bounds_the_report(self):
        for i in range(parsers._MAX_WARNINGS + 500):
            parsers.warn(f"Warnung {i}", internal=False)
        self.assertEqual(len(parsers.parser_warnings), parsers._MAX_WARNINGS)
        self.assertIn("500 weitere", parsers.parser_warnings[-1].full)
        parsers.reset_warnings()
        parsers.warn("x", internal=False)
        self.assertEqual(len(parsers.parser_warnings), 1)

    def test_bitbox_unknown_types_are_counted_per_type_and_year(self):
        src = EX / "bitbox/wallet1.csv"
        header, *rows = src.read_text(encoding="utf-8").splitlines()
        junk = [rows[0].replace("received", "staking_reward", 1)] * 50
        p = self.write("wallet1.csv", "\n".join([header, *rows, *junk]).encode())
        bitbox.parse(p)
        msgs = [w.full for w in parsers.parser_warnings]
        self.assertEqual(len(msgs), 1)
        self.assertIn("50 Zeile(n)", msgs[0])
        self.assertIn("staking_reward", msgs[0])
        self.assertEqual(parsers.parser_warnings[0].year, 2022)


if __name__ == "__main__":
    unittest.main()
