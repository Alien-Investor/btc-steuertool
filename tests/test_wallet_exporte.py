"""Wallet-Exporte Sparrow, Electrum, Trezor Suite, Ledger Live — v1.4, 03.10.2026.

Formate aus dem Quellcode der Programme abgeleitet (Versionen über die Git-Historie), noch
nicht an einem echten Export bestätigt. Fixtures: tests/fixtures/{sparrow,electrum,trezor,ledger}*.csv
bilden dieselben Vorgänge ab, soweit das Format sie hergibt (Eingang, Ausgang mit Gebühr,
Übertrag an sich selbst = nur Gebühr).

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

import src.parsers as parsers                                           # noqa: E402
from src.parsers import wallet_export                                   # noqa: E402
from src.parsers.transfer_zuordnung import resolve_wallet               # noqa: E402
from src.models import TxType, Transaction                              # noqa: E402
from src.main import load_all_transactions as _load                     # noqa: E402
from src import wallet_report                                           # noqa: E402
from tests.test_golden import _run                                      # noqa: E402

FX = ROOT / "tests" / "fixtures"
UTC = timezone.utc


def parse(name: str):
    parsers.reset_warnings()
    txs = wallet_export.parse(FX / name)
    return txs, [w for w in parsers.parser_warnings]


def by_tx(txs, prefix):
    hits = [t for t in txs if t.tx_id.lower().startswith(prefix)]
    assert len(hits) == 1, (prefix, hits)
    return hits[0]


class Detection(unittest.TestCase):
    def test_header_decides_program(self):
        cases = {"sparrow.csv": "sparrow", "sparrow_alt.csv": "sparrow", "electrum.csv": "electrum",
                 "electrum_46.csv": "electrum", "electrum_45.csv": "electrum", "trezor.csv": "trezor",
                 "trezor_semikolon.csv": "trezor", "ledger.csv": "ledger"}
        for name, kind in cases.items():
            with self.subTest(name=name):
                self.assertEqual(wallet_export.detect(wallet_export.first_line(FX / name)), kind)

    def test_bitbox_and_broker_headers_are_not_wallet_exports(self):
        for p in (ROOT / "examples/bitbox/wallet1.csv", ROOT / "examples/Broker/strike_2024.csv",
                  FX / "sammel_blockpit_new.csv", FX / "bisq_en.csv"):
            with self.subTest(p=p.name):
                self.assertIsNone(wallet_export.detect(wallet_export.first_line(p)))
                with self.assertRaises(ValueError):
                    wallet_export.parse(p)

    def test_every_file_warns_format_unconfirmed(self):
        for name in ("sparrow.csv", "electrum.csv", "trezor.csv", "ledger.csv"):
            with self.subTest(name=name):
                _, warns = parse(name)
                w = [w for w in warns if "noch nicht an einem echten Export bestätigt" in w.full]
                self.assertEqual(len(w), 1)
                self.assertFalse(w[0].internal)
                self.assertNotIn(name, str(w[0]))          # Dateiname redigiert im offiziellen Kanal


class SameCoreInEveryFormat(unittest.TestCase):
    """Eingang 0,25 BTC, Ausgang 0,1 BTC + Gebühr, Konsolidierung = nur Gebühr — Sparrow und Electrum
    beschreiben dieselben Vorgänge (Electrum in Ortszeit, Sparrow in UTC)."""

    def test_sparrow_equals_electrum(self):
        sp, _ = parse("sparrow.csv")
        el, _ = parse("electrum.csv")
        for prefix in ("3a7c", "b81e", "c4d5", "d5e6"):
            with self.subTest(tx=prefix):
                a, b = by_tx(sp, prefix), by_tx(el, prefix)
                self.assertEqual((a.date, a.type, a.btc_amount, a.fee_btc), (b.date, b.type, b.btc_amount, b.fee_btc))

    def test_net_amount_minus_fee(self):
        sp, _ = parse("sparrow.csv")
        out = by_tx(sp, "c4d5")
        self.assertEqual((out.type, out.btc_amount, out.fee_btc), (TxType.TRANSFER_OUT, D("0.1"), D("0.000021")))
        self.assertEqual(out.date, datetime(2024, 8, 3, 6, 45, 10, tzinfo=UTC))

    def test_self_transfer_is_fee_only(self):
        for name, prefix, fee in (("sparrow.csv", "d5e6", "0.0000085"), ("electrum.csv", "d5e6", "0.0000085"),
                                  ("trezor.csv", "ca97", "0.0000282"), ("ledger.csv", "ca97", "0.0000282")):
            with self.subTest(name=name):
                txs, _ = parse(name)
                t = by_tx(txs, prefix)
                self.assertEqual((t.type, t.btc_amount, t.fee_btc), (TxType.TRANSFER_OUT, D("0"), D(fee)))


class Sparrow(unittest.TestCase):
    def test_gift_word_in_label(self):
        txs, _ = parse("sparrow.csv")
        g = by_tx(txs, "f1e2")
        self.assertEqual((g.type, g.btc_amount, g.fee_btc), (TxType.GIFT_OUT, D("0.01"), D("0.00001")))

    def test_unknown_fee_and_unconfirmed_are_loud(self):
        txs, warns = parse("sparrow.csv")
        cj = by_tx(txs, "a0a1")
        self.assertEqual((cj.btc_amount, cj.fee_btc), (D("0.02"), D("0")))
        msgs = " ".join(w.full for w in warns)
        self.assertIn("ohne bekannte Gebühr", msgs)
        self.assertIn("1 unbestätigte Transaktion", msgs)
        self.assertFalse(any(t.tx_id.startswith("e6f7") for t in txs))

    def test_old_header_sats_local_time_comment_tail(self):
        txs, warns = parse("sparrow_alt.csv")
        inn, out = txs
        self.assertEqual(inn.btc_amount, D("0.005"))
        self.assertEqual(inn.date, datetime(2023, 6, 1, 10, 30, tzinfo=UTC))      # 12:30 MESZ
        self.assertEqual((out.btc_amount, out.fee_btc), (D("0.002"), D("0.0000045")))
        msgs = " ".join(w.full for w in warns)
        self.assertIn("Einheit aus der Schreibweise abgeleitet", msgs)
        self.assertIn("deutsche Ortszeit", msgs)

    def test_decimal_comma_and_sats_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "k.csv"
            p.write_text('Date (UTC),Label,Value (BTC),Balance (BTC),Fee (BTC),Txid\n'
                         '2024-01-02 03:04:05,,"-0,10002100","0,89997900","0,00002100",ab\n')
            parsers.reset_warnings()
            t, = wallet_export.parse(p)
            self.assertEqual((t.btc_amount, t.fee_btc), (D("0.1"), D("0.000021")))
            p.write_text('Date (UTC),Label,Value (sats),Balance (sats),Fee (sats),Txid\n'
                         '2024-01-02 03:04:05,,-10002100,0,2100,ab\n')
            t, = wallet_export.parse(p)
            self.assertEqual((t.btc_amount, t.fee_btc), (D("0.1"), D("0.000021")))
            p.write_text('Date (UTC),Label,Value (sats),Balance (sats),Fee (sats),Txid\n'
                         '2024-01-02 03:04:05,,-1000.5,0,2100,ab\n')
            with self.assertRaises(ValueError):
                wallet_export.parse(p)

    def test_format_without_fee_column_before_172(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "alt.csv"
            p.write_text("Date,Label,Value,Balance,Txid\n"
                         "2021-03-01 12:00,,0.50000000,0.50000000,aa\n"
                         "2021-04-01 12:00,,-0.10001000,0.39999000,bb\n")
            parsers.reset_warnings()
            inn, out = wallet_export.parse(p)
            self.assertEqual((inn.btc_amount, out.btc_amount, out.fee_btc), (D("0.5"), D("0.10001"), D("0")))
            msgs = " ".join(w.full for w in parsers.parser_warnings)
            self.assertIn("Ohne Gebührenspalte", msgs)
            self.assertIn("ohne bekannte Gebühr", msgs)

    def test_fee_larger_than_outflow_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "k.csv"
            p.write_text('Date (UTC),Label,Value (sats),Balance (sats),Fee (sats),Txid\n'
                         '2024-01-02 03:04:05,,-100,0,2100,ab\n')
            parsers.reset_warnings()
            with self.assertRaises(ValueError):
                wallet_export.parse(p)


class Electrum(unittest.TestCase):
    def test_local_time_read_as_berlin(self):
        txs, _ = parse("electrum.csv")
        self.assertEqual(by_tx(txs, "3a7c").date, datetime(2024, 3, 1, 9, 14, 27, tzinfo=UTC))

    def test_lightning_not_booked_but_reported(self):
        txs, warns = parse("electrum.csv")
        self.assertFalse(any("Kaffee" in t.note for t in txs))
        ch = by_tx(txs, "9e8d")     # On-Chain-Teil der Kanal-Öffnung bleibt als Abgang
        self.assertEqual((ch.btc_amount, ch.fee_btc), (D("0.00302547"), D("0.00000153")))
        self.assertTrue(any("Lightning" in w.full for w in warns))

    def test_fee_in_satoshi_46_and_unconfirmed(self):
        txs, warns = parse("electrum_46.csv")
        t, = txs
        self.assertEqual((t.btc_amount, t.fee_btc), (D("0.01"), D("0.0000141")))
        self.assertTrue(any("unbestätigte" in w.full for w in warns))

    def test_old_format_45(self):
        txs, _ = parse("electrum_45.csv")
        self.assertEqual([(t.type, t.btc_amount, t.fee_btc) for t in txs],
                         [(TxType.TRANSFER_IN, D("0.02"), D("0")), (TxType.TRANSFER_OUT, D("0.005"), D("0.00000705"))])
        # 27.03.2022 03:30 MESZ (Tag der Zeitumstellung) = 01:30 UTC
        self.assertEqual(txs[1].date, datetime(2022, 3, 27, 1, 30, tzinfo=UTC))


class Trezor(unittest.TestCase):
    def test_outputs_summed_fee_counted_once(self):
        txs, _ = parse("trezor.csv")
        out = by_tx(txs, "3e23")
        self.assertEqual((out.type, out.btc_amount, out.fee_btc), (TxType.TRANSFER_OUT, D("0.1"), D("0.000141")))
        self.assertIn("-Rest", out.note)            # Formelschutz-Apostroph entfernt
        self.assertNotIn("'-Rest", out.note)

    def test_receive_and_timestamp_utc(self):
        txs, _ = parse("trezor.csv")
        r = by_tx(txs, "2e7d")
        self.assertEqual((r.type, r.btc_amount, r.fee_btc), (TxType.TRANSFER_IN, D("0.5"), D("0")))
        self.assertEqual(r.date, datetime(2024, 3, 10, 12, 0, tzinfo=UTC))

    def test_semicolon_era_reads_the_same(self):
        a, _ = parse("trezor_semikolon.csv")
        b, _ = parse("trezor.csv")
        x = by_tx(b, "18ac")
        self.assertEqual([(t.date, t.type, t.btc_amount) for t in a], [(x.date, x.type, x.btc_amount)])

    def test_export_timestamp_not_part_of_wallet_name(self):
        """Die Suite schlägt <Konto>_JJJJMMTTTHHMMSS.csv vor — zwei Exporte desselben Kontos bleiben eine Wallet."""
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "Bitcoin_1_20260101T120000.csv"
            b = Path(tmp) / "Bitcoin_1_20260301T093015.csv"
            for p in (a, b):
                shutil.copy(FX / "trezor.csv", p)
            parsers.reset_warnings()
            self.assertEqual({t.source for t in wallet_export.parse(a) + wallet_export.parse(b)}, {"trezor:Bitcoin_1"})

    def test_non_btc_account_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eth.csv"
            p.write_text("Timestamp,Date,Time,Type,Transaction ID,Fee,Fee unit,Address,Label,Amount,Amount unit,Fiat (EUR),Other\n"
                         "1717243200,1.6.2024,14:00:00 GMT+2,RECV,0xab,,,0x1,,1.5,ETH,,\n")
            parsers.reset_warnings()
            self.assertEqual(wallet_export.parse(p), [])


class Ledger(unittest.TestCase):
    def test_accounts_are_wallets_and_eth_skipped(self):
        txs, warns = parse("ledger.csv")
        self.assertEqual(sorted({t.source for t in txs}), ["ledger:Bitcoin 1", "ledger:Bitcoin 1 (2)", "ledger:Bitcoin 2"])
        self.assertTrue(any("anderer Kryptowährungen" in w.full and w.internal for w in warns))
        self.assertFalse(any("xpub" in t.source or "xpub" in t.note for t in txs))

    def test_out_amount_includes_fee_in_fee_ignored(self):
        txs, _ = parse("ledger.csv")
        out = next(t for t in txs if t.tx_id.startswith("3e23") and t.type == TxType.TRANSFER_OUT)
        inn = next(t for t in txs if t.tx_id.startswith("3e23") and t.type == TxType.TRANSFER_IN)
        self.assertEqual((out.source, out.btc_amount, out.fee_btc), ("ledger:Bitcoin 1", D("0.1"), D("0.000141")))
        self.assertEqual((inn.source, inn.btc_amount, inn.fee_btc), ("ledger:Bitcoin 2", D("0.1"), D("0")))

    def test_hash_lowercased(self):
        txs, _ = parse("ledger.csv")
        self.assertTrue(by_tx(txs, "ca97").tx_id.islower())


class Labels(unittest.TestCase):
    def _tx(self, src, no_kyc=False):
        return Transaction(date=datetime(2024, 1, 1, tzinfo=UTC), type=TxType.TRANSFER_IN, btc_amount=D("1"),
                           eur_amount=D(0), eur_price_per_btc=D(0), fee_eur=D(0), source=src, tx_id="", note="",
                           no_kyc=no_kyc)

    def test_official_labels_per_kind_kyc_only(self):
        txs = [self._tx("bitbox:a"), self._tx("bitbox:b"), self._tx("sparrow:cold"), self._tx("ledger:Bitcoin 1"),
               self._tx("trezor:geheim", no_kyc=True)]
        labels = wallet_report.official_labels(txs)
        self.assertEqual(labels, {"bitbox:a": "BitBox-Wallet 1", "bitbox:b": "BitBox-Wallet 2",
                                  "sparrow:cold": "Sparrow-Wallet", "ledger:Bitcoin 1": "Ledger-Wallet"})
        self.assertEqual(wallet_report.label("trezor:geheim", labels), "Trezor-Wallet")    # fail closed
        self.assertEqual(wallet_report.label("sparrow:cold", None), "cold (Sparrow)")
        self.assertEqual(wallet_report.label("bitbox:a", None), "a")

    def test_resolve_wallet_by_file_name(self):
        known = {"bitbox:wallet1", "sparrow:cold", "electrum:hot", "bitbox:hot"}
        self.assertEqual(resolve_wallet("cold", known), "sparrow:cold")
        self.assertEqual(resolve_wallet("wallet1", known), "bitbox:wallet1")
        self.assertIsNone(resolve_wallet("hot", known))            # mehrdeutig
        self.assertEqual(resolve_wallet("electrum:hot", known), "electrum:hot")


SPARROW_COLD = (
    "Date (UTC),Label,Value (BTC),Balance (BTC),Fee (BTC),Txid\n"
    "2022-05-02 14:00:00,,0.01000000,0.01000000,,c0c0000000000000000000000000000000000000000000000000000000000001\n"
    "2023-06-01 10:00:00,Konsolidierung,-0.00001000,0.00999000,0.00001000,c0c0000000000000000000000000000000000000000000000000000000000002\n"
)
SPARROW_NOKYC = (
    "Date (UTC),Label,Value (sats),Balance (sats),Fee (sats),Txid\n"
    "2023-02-02 10:00:00,,150000,150000,,d0d0000000000000000000000000000000000000000000000000000000000001\n"
)


class FullRun(unittest.TestCase):
    """Gesamtlauf über den Loader und die Reports: Zuordnung Broker → Sparrow, Gebühr als Veräußerung
    aus der Sparrow-Wallet, Datenschutz der offiziellen Dokumente."""

    def _data(self, tmp):
        data = Path(tmp) / "data"
        (data / "Broker").mkdir(parents=True)
        shutil.copy(ROOT / "examples/Broker/21bitcoin-gesamt.csv", data / "Broker")
        (data / "wallets" / "nokyc").mkdir(parents=True)
        (data / "wallets" / "cold.csv").write_text(SPARROW_COLD)
        (data / "wallets" / "nokyc" / "versteck.csv").write_text(SPARROW_NOKYC)
        return data

    def test_loader_classifies_and_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                txs = _load(self._data(tmp))
            cold = [t for t in txs if t.source == "sparrow:cold"]
            self.assertEqual(len(cold), 2)
            self.assertFalse(any(t.no_kyc for t in cold))
            self.assertTrue(all(t.no_kyc for t in txs if t.source == "sparrow:versteck"))

    def test_reports_name_kind_never_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = _run(self._data(tmp))
            official = {p.name: p.read_text() for p in reports.iterdir()
                        if p.name.startswith(("steuerreport_", "steuernachweis_", "kaeufe_", "verkaeufe_"))}
            self.assertTrue(official)
            for name, text in official.items():
                with self.subTest(report=name):
                    self.assertNotIn("cold", text)
                    self.assertNotIn("versteck", text)
                    self.assertNotIn("noKYC", text)
            nachweis = (reports / "steuernachweis_2023.txt").read_text()
            self.assertIn("Sparrow Wallet CSV-Export (1 Wallet)", nachweis)
            self.assertIn("Sparrow-Wallet", nachweis)
            self.assertIn("noch nicht an einem echten Export bestätigt", nachweis)
            intern = (reports / "wallet_abgleich_intern_2022.txt").read_text()
            self.assertIn("cold (Sparrow)", intern)
            nokyc = (reports / "nokyc_intern_2023.txt").read_text()
            self.assertIn("versteck (Sparrow)", nokyc)
            self.assertIn("wallets/nokyc/", nokyc)


if __name__ == "__main__":
    unittest.main()
