"""Sammelimport (CoinTracking/Blockpit) — Etappe 5.3, 03.10.2026.

Formate aus der Dokumentation und veröffentlichten Beispieldateien abgeleitet, noch nicht
an einem echten Export bestätigt. Die Fixtures unter tests/fixtures/sammel_*.csv bilden
dieselben Vorgänge in jedem Format ab, soweit das Format sie hergibt.

Aufruf:  python -m unittest discover tests
"""
from __future__ import annotations
import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.parsers as parsers                                  # noqa: E402
from src.parsers import sammelimport                           # noqa: E402
from src.models import TxType, TZ_DE                           # noqa: E402
from src.main import load_all_transactions as _load            # noqa: E402
from tests.test_golden import _run                             # noqa: E402

FX = ROOT / "tests" / "fixtures"
EX = ROOT / "examples"


def load(data_dir):
    with contextlib.redirect_stdout(io.StringIO()):
        return _load(data_dir)


def by_type(txs, typ):
    return [t for t in txs if t.type == typ]


class Formats(unittest.TestCase):
    def setUp(self):
        parsers.reset_warnings()

    def test_detect_format(self):
        cases = {
            "sammel_ct_import.csv": "CT_IMPORT", "sammel_ct_export.csv": "CT_EXPORT", "sammel_ct_full.csv": "CT_FULL",
            "sammel_blockpit_new.csv": "BP_NEW", "sammel_blockpit_old.csv": "BP_OLD",
        }
        for name, fmt in cases.items():
            with self.subTest(name=name):
                _, header = parsers.read_rows(FX / name, label="T", delimiter=sammelimport._delimiter(FX / name))
                self.assertEqual(sammelimport.detect_format(header), fmt)
        self.assertIsNone(sammelimport.detect_format(["Trade ID", "Date/Time", "Market"]))

    def test_same_core_transactions_in_every_format(self):
        """Kauf, Auszahlung (mit TX-ID), Eingang, Verkauf — in allen fünf Formaten gleich."""
        core = {}
        for name in ("sammel_ct_import.csv", "sammel_ct_export.csv", "sammel_blockpit_new.csv", "sammel_blockpit_old.csv"):
            parsers.reset_warnings()
            txs = sammelimport.parse(FX / name)
            buy = next(t for t in txs if t.type == TxType.BUY and t.source == "Kraken" and t.btc_amount == D("0.01"))
            out = next(t for t in txs if t.type == TxType.TRANSFER_OUT and t.btc_amount > 0)
            inn = next(t for t in txs if t.type == TxType.TRANSFER_IN)
            sell = next(t for t in txs if t.type == TxType.SELL)
            minute = lambda d: d.replace(second=0)     # BP_OLD hat nur Minutenauflösung
            core[name] = (
                minute(buy.date), buy.eur_amount, buy.fee_eur, buy.source,
                minute(out.date), out.btc_amount, out.fee_btc, out.source,
                minute(inn.date), inn.btc_amount, inn.source,
                minute(sell.date), sell.btc_amount, sell.eur_amount, sell.fee_eur, sell.source,
            )
        values = list(core.values())
        for name, v in core.items():
            with self.subTest(name=name):
                self.assertEqual(v, values[0])
        # Zeitzone: CoinTracking 14:22:10 Berlin == Blockpit 13:22:10 UTC
        self.assertEqual(values[0][0], datetime(2024, 3, 15, 13, 22, tzinfo=timezone.utc))
        # TX-ID aus dem Export (CoinTracking-Import, Blockpit) — die Zuordnung zur BitBox läuft darüber
        for name in ("sammel_ct_import.csv", "sammel_blockpit_new.csv", "sammel_blockpit_old.csv"):
            parsers.reset_warnings()
            txs = sammelimport.parse(FX / name)
            out = next(t for t in txs if t.type == TxType.TRANSFER_OUT and t.btc_amount > 0)
            self.assertTrue(out.tx_id.startswith("e1e1"), name)


class CoinTrackingImport(unittest.TestCase):
    def setUp(self):
        parsers.reset_warnings()
        self.txs = sammelimport.parse(FX / "sammel_ct_import.csv")
        self.msgs = [w.full for w in parsers.parser_warnings]

    def test_buy_in_usd_is_converted_and_btc_fee_handled_like_bisq(self):
        buy = next(t for t in self.txs if t.type == TxType.BUY and "USD" in t.note)
        self.assertEqual(buy.btc_amount, D("0.005"))
        self.assertGreater(buy.eur_amount, D("250"))
        self.assertLess(buy.eur_amount, D("320"))
        self.assertEqual(buy.fee_btc, D("0.00001"))
        self.assertGreater(buy.fee_eur, 0)       # Anschaffungsnebenkosten aus der BTC-Gebühr

    def test_withdrawal_amount_excludes_fee(self):
        out = next(t for t in self.txs if t.type == TxType.TRANSFER_OUT and t.btc_amount > 0)
        self.assertEqual((out.btc_amount, out.fee_btc), (D("0.0099"), D("0.0001")))

    def test_btc_fee_on_non_btc_trade_is_a_fee_disposal(self):
        fees = [t for t in self.txs if t.type == TxType.TRANSFER_OUT and t.btc_amount == 0]
        self.assertEqual(sorted(t.fee_btc for t in fees), [D("0.00001"), D("0.00002")])

    def test_rows_without_btc_are_silent(self):
        self.assertFalse(any("ohne BTC" in m for m in self.msgs))

    def test_gift_out_and_nokyc_account(self):
        gift = next(t for t in self.txs if t.type == TxType.GIFT_OUT)
        self.assertEqual(gift.btc_amount, D("0.0004"))
        bisq = next(t for t in self.txs if t.source == "Bisq")
        self.assertTrue(bisq.no_kyc)
        self.assertFalse(any(t.no_kyc for t in self.txs if t.source != "Bisq"))

    def test_loud_warnings_for_unpriced_rows(self):
        joined = "\n".join(self.msgs)
        self.assertIn("USDT→BTC", joined)
        self.assertIn("ANSCHAFFUNG", joined)
        self.assertIn("BTC→ETH", joined)
        self.assertIn("VERÄUSSERUNG von BTC", joined)
        self.assertIn("Zufluss", joined)
        self.assertIn("Bezahlung mit", joined)
        self.assertIn("'Lost'", joined)
        self.assertTrue(all(w.year == 2024 for w in parsers.parser_warnings if w.year is not None))

    def test_unconfirmed_format_warning_is_public_and_redacts_filename(self):
        w = next(w for w in parsers.parser_warnings if "noch nicht an einem echten Export" in w.full)
        self.assertFalse(w.internal)
        self.assertIn("sammel_ct_import.csv", w.full)
        self.assertNotIn("sammel_ct_import.csv", str(w))      # offizieller Kanal
        self.assertIn("Sammelimport-Datei", str(w))

    def test_aggregate_sources_registered_without_nokyc(self):
        self.assertEqual(parsers.aggregate_sources, {"Kraken": "CoinTracking-Importformat",
                                                     "Bitpanda": "CoinTracking-Importformat"})


class CoinTrackingFullView(unittest.TestCase):
    def test_values_in_eur_price_crypto_trades_income_and_spend(self):
        parsers.reset_warnings()
        txs = sammelimport.parse(FX / "sammel_ct_full.csv")
        kinds = [(t.type, t.btc_amount, t.eur_amount) for t in txs]
        self.assertEqual(kinds, [
            (TxType.BUY, D("0.003"), D("180.00")),
            (TxType.BUY, D("0.00001"), D("0.55")),
            (TxType.SELL, D("0.0005"), D("28.00")),
        ])
        self.assertIn("steuerliche Einordnung", txs[1].note)
        self.assertEqual(len([w for w in parsers.parser_warnings if w.year]), 0)


class Blockpit(unittest.TestCase):
    def test_new_format_labels(self):
        parsers.reset_warnings()
        txs = sammelimport.parse(FX / "sammel_blockpit_new.csv")
        self.assertEqual([t.type for t in txs], [TxType.BUY, TxType.TRANSFER_OUT, TxType.TRANSFER_IN, TxType.SELL,
                                                 TxType.GIFT_OUT, TxType.TRANSFER_OUT])
        self.assertEqual(txs[-1].fee_btc, D("0.00001"))          # Label Fee → Gebührenabgang
        self.assertEqual({t.source for t in txs}, {"Kraken", "Bitpanda"})   # Source Name, nicht „Mein Kraken"
        msgs = "\n".join(w.full for w in parsers.parser_warnings)
        self.assertIn("Payment", msgs)
        self.assertIn("Staking", msgs)
        self.assertNotIn("Non-Taxable", msgs)                     # EUR-Zeile: still

    def test_old_format_semicolon_and_minutes(self):
        parsers.reset_warnings()
        txs = sammelimport.parse(FX / "sammel_blockpit_old.csv")
        self.assertEqual(len(txs), 4)
        self.assertEqual(txs[0].date, datetime(2024, 3, 15, 13, 22, tzinfo=timezone.utc))
        self.assertEqual({t.source for t in txs}, {"Kraken", "Bitpanda"})
        self.assertFalse(any("BNB" in w.full for w in parsers.parser_warnings))


class Dates(unittest.TestCase):
    def test_ct_date_forms(self):
        p = sammelimport._parse_ct_date
        self.assertEqual(p("15.03.2024 14:22:10", "f", 1), datetime(2024, 3, 15, 14, 22, 10, tzinfo=TZ_DE).astimezone(timezone.utc))
        self.assertEqual(p("15.03.2024 14:22", "f", 1), datetime(2024, 3, 15, 14, 22, tzinfo=TZ_DE).astimezone(timezone.utc))
        self.assertEqual(p("2024-03-15 14:22:10", "f", 1), datetime(2024, 3, 15, 14, 22, 10, tzinfo=TZ_DE).astimezone(timezone.utc))
        self.assertEqual(p("2024-03-15T13:22:10Z", "f", 1), datetime(2024, 3, 15, 13, 22, 10, tzinfo=timezone.utc))
        with self.assertRaises(ValueError) as ctx:
            p("5/9/2017 21:14", "f", 1)
        self.assertIn("mehrdeutig", str(ctx.exception))
        with self.assertRaises(ValueError):
            p("15 Mar 2024 14:22:10", "f", 1)

    def test_bp_date_is_utc(self):
        self.assertEqual(sammelimport._parse_bp_date("06.01.2023 20:08", "f", 1), datetime(2023, 1, 6, 20, 8, tzinfo=timezone.utc))


class Loader(unittest.TestCase):
    def setUp(self):
        parsers.reset_warnings()
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name) / "data"
        shutil.copytree(EX, self.data)
        shutil.rmtree(self.data / "reports", ignore_errors=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_loader_picks_up_all_name_patterns_and_reports_run(self):
        shutil.copy(FX / "sammel_ct_import.csv", self.data / "Broker" / "cointracking_2024.csv")
        shutil.copy(FX / "sammel_blockpit_new.csv", self.data / "Broker" / "Blockpit-Export.csv")
        txs = load(self.data)
        sources = {t.source for t in txs}
        self.assertIn("Kraken", sources)
        self.assertIn("Bitpanda", sources)
        reports = _run(self.data)
        nachweis = (reports / "steuernachweis_2024.txt").read_text(encoding="utf-8")
        self.assertIn("Kraken (CoinTracking-Importformat)", nachweis)
        self.assertIn("Bitpanda (CoinTracking-Importformat)", nachweis)
        self.assertNotIn("cointracking_2024.csv", nachweis)    # Dateiname nur intern, auch in Zeilenwarnungen
        self.assertIn("Sammelimport-Datei, Zeile", nachweis)
        report = (reports / "steuerreport_2024.txt").read_text(encoding="utf-8")
        self.assertIn("noch nicht an einem echten Export", report)
        self.assertIn("Sammelimport-Datei", report)
        self.assertNotIn("cointracking_2024.csv", report)      # Dateiname nur intern
        intern = (reports / "nokyc_intern_2024.txt").read_text(encoding="utf-8")
        self.assertIn("Bisq", intern)                           # noKYC-Konto nur intern
        self.assertNotIn("Bisq", report)

    def test_nokyc_in_filename_marks_everything_internal(self):
        shutil.copy(FX / "sammel_ct_export.csv", self.data / "Broker" / "cointracking_nokyc.csv")
        txs = load(self.data)
        self.assertTrue(all(t.no_kyc for t in txs if t.source in ("Kraken", "Bitpanda")))
        w = next(w for w in parsers.parser_warnings if "noch nicht an einem echten Export" in w.full)
        self.assertTrue(w.internal)

    def test_double_loaded_wallet_is_reported(self):
        # Dieselbe TX-ID in gleicher Richtung wie ein BitBox-Eingang → Hinweis auf Doppelzählung
        wallet = (self.data / "bitbox" / "wallet1.csv")
        txid = wallet.read_text(encoding="utf-8").splitlines()[1].split(",")[7]
        fixture = (FX / "sammel_blockpit_new.csv").read_text(encoding="utf-8").replace(
            "d2d2000000000000000000000000000000000000000000000000000000000002", txid)
        (self.data / "Broker" / "blockpit.csv").write_text(fixture, encoding="utf-8")
        load(self.data)
        msgs = [w.full for w in parsers.parser_warnings]
        self.assertTrue(any("doppelt geladen" in m for m in msgs), msgs)

    def test_unknown_header_is_hard_error(self):
        (self.data / "Broker" / "cointracking_x.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load(self.data)
        self.assertIn("cointracking_x.csv", str(ctx.exception))
        self.assertIn("CoinTracking", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
