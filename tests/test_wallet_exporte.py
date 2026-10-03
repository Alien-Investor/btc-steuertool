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
        self.assertEqual(len(set(parsers.ledger_keys.values())), 3)       # zwei „Bitcoin 1“ (xpub) + „Bitcoin 2“
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "wallets").mkdir()
            shutil.copy(FX / "ledger.csv", Path(tmp) / "wallets")
            with contextlib.redirect_stdout(io.StringIO()):
                loaded = _load(Path(tmp))
        self.assertEqual(sorted({t.source for t in loaded}), ["ledger:Bitcoin 1", "ledger:Bitcoin 1 (2)", "ledger:Bitcoin 2"])
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


class AuditPrivacy(unittest.TestCase):
    """Release-Audit v1.4, Runde 1 (Datenschutz): Überträge noKYC → KYC, die die Sperre umgingen
    und als „nicht eingelesen“ mit Datum und Betrag im Steuernachweis standen."""

    BISON = ("Transaction ID; Transaction type; Currency; Asset; Eur (amount); Asset (amount); Asset (market price); Fee; "
             "Date (UTC - Coordinated Universal Time)\n"
             "TX-1; Buy; ; Btc; 20000.00; 0.50000000; 40000.00; 0; 2024-01-10 10:00:00\n"
             "TX-2; Withdraw; ; Btc; 0.00; 0.50000000; 0.00; 0; 2024-01-11 10:00:00\n")
    KYC = ("Date (UTC),Label,Value (BTC),Balance (BTC),Fee (BTC),Txid\n"
           "2024-01-11 10:00:00,,0.50000000,0.50000000,,1111111111111111111111111111111111111111111111111111111111111111\n"
           "2024-03-01 11:00:00,,0.09990000,0.59990000,,3333333333333333333333333333333333333333333333333333333333333333\n")
    NOKYC = ("Date,Label,Value,Balance,Txid\n"
             "2024-02-02 12:00,Treffen,20000000,20000000,2222222222222222222222222222222222222222222222222222222222222222\n"
             "2024-03-01 12:00,Umzug,-10000000,10000000,3333333333333333333333333333333333333333333333333333333333333333\n")

    def _data(self, tmp, kyc_name="kyc_cold.csv", nokyc_name="p2p.csv"):
        d = Path(tmp) / "data"
        (d / "Broker").mkdir(parents=True)
        (d / "wallets" / "nokyc").mkdir(parents=True)
        (d / "Broker" / "Bison-CSV-Gesamt.csv").write_text(self.BISON)
        (d / "manual_buys.csv").write_text("date,btc_amount,eur_amount,note,kyc\n2024-02-01,0.2,8000.00,P2P,\n")
        (d / "wallets" / kyc_name).write_text(self.KYC)
        (d / "wallets" / "nokyc" / nokyc_name).write_text(self.NOKYC)
        return d

    def _run_load(self, d):
        from src.main import run_engine
        with contextlib.redirect_stdout(io.StringIO()):
            run_engine(_load(d))

    def test_b2_unknown_fee_same_txid_aborts(self):
        """Altes Sparrow-Format ohne Gebühr: Abgang 0,1 vs. Eingang 0,0999 — gleiche TX-ID muss abbrechen."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "noKYC-Bestand"):
                self._run_load(self._data(tmp))

    def test_b1_same_wallet_name_in_both_classes_aborts(self):
        """Trezor-Zeitstempel abgestreift → gleicher Name in wallets/ und wallets/nokyc/."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self._data(tmp, kyc_name="cold.csv", nokyc_name="cold.csv")
            with self.assertRaisesRegex(ValueError, "KYC- und im noKYC-Bestand"):
                with contextlib.redirect_stdout(io.StringIO()):
                    _load(d)


class AuditRobust(unittest.TestCase):
    """Release-Audit v1.4, Runde 1 (Robustheit): laut abbrechen statt still falsch rechnen."""

    TREZOR_HEAD = "Timestamp,Date,Time,Type,Transaction ID,Fee,Fee unit,Address,Label,Amount,Amount unit,Fiat (EUR),Other\n"
    LEDGER_HEAD = ("Operation Date,Status,Currency Ticker,Operation Type,Operation Amount,Operation Fees,Operation Hash,"
                   "Account Name,Account xpub,Countervalue Ticker,Countervalue at Operation Date,Countervalue at CSV Export\n")

    def _parse_text(self, name, text):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / name
            p.write_text(text)
            parsers.reset_warnings()
            return wallet_export.parse(p), list(parsers.parser_warnings)

    def test_negative_amounts_rejected(self):
        with self.assertRaisesRegex(ValueError, "negativer Betrag"):
            self._parse_text("t.csv", self.TREZOR_HEAD + "1717243200,,,SENT,ab,0.0001,BTC,x,,-0.1,BTC,,\n")
        with self.assertRaisesRegex(ValueError, "negativer Betrag"):
            self._parse_text("l.csv", self.LEDGER_HEAD + "2024-06-01T12:00:00.000Z,Confirmed,BTC,OUT,-0.5,0.0001,ab,Bitcoin 1,xpubA,,,\n")

    def test_trezor_sat_unit_is_an_error_not_skipped(self):
        with self.assertRaisesRegex(ValueError, "statt BTC"):
            self._parse_text("t.csv", self.TREZOR_HEAD + "1717243200,,,RECV,ab,,,x,,10000,sat,,\n")

    def test_missing_txid_rejected(self):
        with self.assertRaisesRegex(ValueError, "Transaction ID fehlt"):
            self._parse_text("t.csv", self.TREZOR_HEAD + "1717243200,,,RECV,,,,x,,0.1,BTC,,\n")
        with self.assertRaisesRegex(ValueError, "Operation Hash fehlt"):
            self._parse_text("l.csv", self.LEDGER_HEAD + "2024-06-01T12:00:00.000Z,Confirmed,BTC,IN,0.5,,,Bitcoin 1,xpubA,,,\n")

    def test_unconfirmed_not_booked(self):
        txs, warns = self._parse_text("l.csv", self.LEDGER_HEAD + "2024-06-01T12:00:00.000Z,Pending,BTC,IN,0.5,,ab,Bitcoin 1,xpubA,,,\n")
        self.assertEqual(txs, [])
        self.assertTrue(any("unbestätigte" in w.full for w in warns))
        txs, _ = self._parse_text("e.csv", "oc_transaction_hash,ln_payment_hash,label,confirmations,amount_chain_bc,"
                                  "amount_lightning_bc,fiat_value,network_fee_bc,fiat_fee,timestamp\n"
                                  "ab,,,0,0.1,0.,,0.,,2026-09-01 10:00:00\n")
        self.assertEqual(txs, [])

    def test_implausible_amount_rejected(self):
        with self.assertRaisesRegex(ValueError, "unplausibel"):
            self._parse_text("s.csv", "Date (UTC),Label,Value (BTC),Balance (BTC),Fee (BTC),Txid\n"
                             "2024-01-02 03:04:05,,999999999.00000000,0,,ab\n")

    def _two_files(self, tmp, names, texts):
        d = Path(tmp) / "data"
        (d / "wallets").mkdir(parents=True)
        for n, t in zip(names, texts):
            (d / "wallets" / n).write_text(t)
        return d

    def test_ledger_same_name_two_devices_are_two_wallets(self):
        """Runde 2 (F2): Nummerierung über alle Dateien nach xpub — zwei Geräte mit „Bitcoin 1“ sind
        zwei Wallets, gleich benannt in jeder Datei, kein Abbruch mehr."""
        a = self.LEDGER_HEAD + "2024-01-10T12:00:00.000Z,Confirmed,BTC,IN,0.5,,aa,Bitcoin 1,xpubDEVICE1,,,\n"
        b = self.LEDGER_HEAD + "2024-03-10T12:00:00.000Z,Confirmed,BTC,IN,0.2,,bb,Bitcoin 1,xpubDEVICE2,,,\n"
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                txs = _load(self._two_files(tmp, ["ledger_a.csv", "ledger_b.csv"], [a, b]))
        self.assertEqual({(t.tx_id, t.source) for t in txs}, {("aa", "ledger:Bitcoin 1"), ("bb", "ledger:Bitcoin 1 (2)")})

    def test_ledger_numbering_stable_when_new_account_appears(self):
        """Runde 2 (F2): alter Export nur mit X, neuer mit X und später angelegtem Y (gleicher Name,
        xpub sortiert vor X) — X behält über beide Dateien EINEN Namen."""
        old = self.LEDGER_HEAD + "2023-01-10T12:00:00.000Z,Confirmed,BTC,IN,0.5,,aa,Bitcoin 1,xpubZZZ,,,\n"
        new = self.LEDGER_HEAD + ("2023-01-10T12:00:00.000Z,Confirmed,BTC,IN,0.5,,aa,Bitcoin 1,xpubZZZ,,,\n"
                                  "2024-04-10T12:00:00.000Z,Confirmed,BTC,IN,0.3,,bb,Bitcoin 1,xpubAAA,,,\n")
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                txs = _load(self._two_files(tmp, ["ledger_2023.csv", "ledger_2024.csv"], [old, new]))
        x = {t.source for t in txs if t.tx_id == "aa"}
        self.assertEqual(len(x), 1)
        self.assertEqual(len(txs), 2)          # aa dedupliziert

    def test_ledger_renamed_account_with_old_export_aborts(self):
        """Runde 2 (F3): derselbe xpub unter zwei Namen = umbenannt, alter Export liegt dabei."""
        a = self.LEDGER_HEAD + "2024-01-10T12:00:00.000Z,Confirmed,BTC,IN,0.5,,aa,Bitcoin 1,xpubX,,,\n"
        b = self.LEDGER_HEAD + "2024-01-10T12:00:00.000Z,Confirmed,BTC,IN,0.5,,aa,Cold,xpubX,,,\n"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "umbenannt"):
                with contextlib.redirect_stdout(io.StringIO()):
                    _load(self._two_files(tmp, ["ledger_a.csv", "ledger_b.csv"], [a, b]))

    def test_ledger_overlapping_exports_same_xpub_ok(self):
        a = self.LEDGER_HEAD + "2024-01-10T12:00:00.000Z,Confirmed,BTC,IN,0.5,,aa,Bitcoin 1,xpubDEVICE1,,,\n"
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                txs = _load(self._two_files(tmp, ["ledger_a.csv", "ledger_b.csv"], [a, a]))
            self.assertEqual(len(txs), 1)          # Dedup über beide Dateien

    def test_trezor_two_files_same_name_warns(self):
        a = self.TREZOR_HEAD + "1717243200,,,RECV,aa,,,x,,0.1,BTC,,\n"
        b = self.TREZOR_HEAD + "1717329600,,,RECV,bb,,,x,,0.2,BTC,,\n"
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                _load(self._two_files(tmp, ["Bitcoin #1_20250105T101010.csv", "Bitcoin #1_20250106T111111.csv"], [a, b]))
            w = [w for w in parsers.parser_warnings if "Trezor: 2 Dateien" in w.full]
            self.assertEqual(len(w), 1)
            self.assertIn("Bitcoin #1", w[0].full)
            self.assertNotIn("Bitcoin #1", str(w[0]))     # Name nur im internen Kanal


class AuditCalc(unittest.TestCase):
    """Release-Audit v1.4, Runde 1 (Rechenrichtigkeit)."""

    SP = "Date (UTC),Label,Value (BTC),Balance (BTC),Fee (BTC),Txid\n"
    EL = ("oc_transaction_hash,ln_payment_hash,label,confirmations,amount_chain_bc,amount_lightning_bc,"
          "fiat_value,network_fee_bc,fiat_fee,timestamp\n")
    LH = AuditRobust.LEDGER_HEAD
    TH = AuditRobust.TREZOR_HEAD

    def _load_files(self, tmp, files):
        d = Path(tmp) / "data"
        for rel, text in files.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text)
        with contextlib.redirect_stdout(io.StringIO()):
            return _load(d)

    def test_batch_tx_to_two_own_wallets_not_deduplicated(self):
        """Gleiche TX-ID, gleicher Betrag in zwei verschiedenen Wallets ist kein überlappender Export."""
        row = "2024-03-03 10:00:00,,0.05000000,0.05000000,,bb\n"
        with tempfile.TemporaryDirectory() as tmp:
            txs = self._load_files(tmp, {"wallets/a.csv": self.SP + row, "wallets/b.csv": self.SP + row})
        self.assertEqual(sorted(t.source for t in txs), ["sparrow:a", "sparrow:b"])

    def test_same_wallet_overlap_still_deduplicated(self):
        row = "2024-03-03 10:00:00,,0.05000000,0.05000000,,bb\n"
        with tempfile.TemporaryDirectory() as tmp:
            txs = self._load_files(tmp, {"wallets/a.csv": self.SP + row, "wallets/nokyc/x.csv": self.SP.replace("BTC", "BTC") + "2024-03-04 10:00:00,,0.01000000,0.01000000,,cc\n"})
        self.assertEqual(len([t for t in txs if t.source == "sparrow:a"]), 1)

    def test_ledger_numbering_follows_xpub_not_row_order(self):
        rows = {"X": "2024-01-10T12:00:00.000Z,Confirmed,BTC,IN,0.1,,aa,Bitcoin 1,xpubX,,,\n",
                "Y": "2024-01-11T12:00:00.000Z,Confirmed,BTC,IN,0.3,,bb,Bitcoin 1,xpubY,,,\n"}
        a, _ = AuditRobust()._parse_text("l.csv", self.LH + rows["X"] + rows["Y"])
        b, _ = AuditRobust()._parse_text("l.csv", self.LH + rows["Y"] + rows["X"])
        self.assertEqual({(t.tx_id, t.source) for t in a}, {(t.tx_id, t.source) for t in b})
        self.assertEqual({t.source for t in a if t.tx_id == "aa"}, {"ledger:Bitcoin 1"})     # xpubX < xpubY

    def test_ledger_old_account_id_matches_new_xpub(self):
        old = ("Operation Date,Currency Ticker,Operation Type,Operation Amount,Operation Fees,Operation Hash,"
               "Account Name,Account id\n2024-01-10T12:00:00.000Z,BTC,IN,0.1,,aa,Bitcoin 1,libcore:1:bitcoin:xpubX:native_segwit\n")
        new = self.LH + "2024-02-10T12:00:00.000Z,Confirmed,BTC,IN,0.2,,bb,Bitcoin 1,xpubX,,,\n"
        with tempfile.TemporaryDirectory() as tmp:
            txs = self._load_files(tmp, {"wallets/alt.csv": old, "wallets/neu.csv": new})
        self.assertEqual({t.source for t in txs}, {"ledger:Bitcoin 1"})

    def test_trezor_sent_to_own_address_warns(self):
        txt = (self.TH + "1717243200,,,RECV,aa,,,bc1qown,,0.1,BTC,,\n"
               "1717329600,,,SENT,bb,0.0001,BTC,bc1qfremd,,0.05,BTC,,\n"
               "1717329600,,,SENT,bb,,,bc1qown,,0.02,BTC,,\n")
        _, warns = AuditRobust()._parse_text("t.csv", txt)
        self.assertTrue(any("eigene Empfangsadresse" in w.full for w in warns))

    def test_dst_fold_resolved_by_counterpart(self):
        """27.10.2024: Sparrow (UTC) 01:10 → Electrum zeigt 02:10 (zweite 02:10, MEZ). Electrum gibt um 02:30
        weiter. Ohne Auflösung lief der Abgang vor dem Eingang seiner Lots."""
        sp = self.SP + ("2024-10-26 10:00:00,,0.10000000,0.10000000,,a1\n"
                        "2024-10-27 01:10:00,,-0.05001000,0.04999000,0.00001000,a2\n")
        el = self.EL + ("a2,,,1,0.05,0.,,0.,,2024-10-27 02:10:00\n"
                        "a3,,,1,-0.04,0.,,0.00001,,2024-10-27 02:30:00\n")
        with tempfile.TemporaryDirectory() as tmp:
            txs = self._load_files(tmp, {"wallets/sp.csv": sp, "wallets/el.csv": el})
        inn = next(t for t in txs if t.source == "electrum:el" and t.tx_id == "a2")
        out = next(t for t in txs if t.source == "electrum:el" and t.tx_id == "a3")
        self.assertEqual(inn.date, datetime(2024, 10, 27, 1, 10, tzinfo=UTC))
        self.assertEqual(out.date, datetime(2024, 10, 27, 1, 30, tzinfo=UTC))      # Reihenfolge: zweite Lesart


class AuditRound2(unittest.TestCase):
    """Release-Audit v1.4, Runde 2 (frische Prüfer, gezielt auf die Fixes aus Runde 1)."""

    BTC21 = ("id,exchange_name,depot_name,transaction_date,buy_asset,buy_amount,sell_asset,sell_amount,fee_asset,"
             "fee_amount,transaction_type,note,linked_transaction\n"
             "1,21bitcoin,depot,01.05.2024 14:00:00,BTC,0.01000000,EUR,600.00,EUR,3.00,trade,BTC Kauf,\n"
             "2,21bitcoin,depot,02.05.2024 15:30:00,,,BTC,0.01000000,BTC,0,withdrawal,Auszahlung,1\n")
    BB = "Time,Type,Amount,Unit,Fee,Fee Unit,Address,Transaction ID,Note\n"
    BB_KYC = BB + "2024-05-02T16:00:00+02:00,received,1000000,satoshi,,,bc1qkyc,aaaa01,Kauf\n"
    SP = "Date (UTC),Label,Value (BTC),Balance (BTC),Fee (BTC),Txid\n"
    NK_BUY = "date,btc_amount,eur_amount,note,kyc\n2024-03-10,0.02000000,1100.00,Bargeld,\n"
    NK_IN = "2024-03-11 10:00:00,Treffen,0.02000000,0.02000000,,cccc01\n"

    def _run(self, files):
        from src.main import run_engine
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for rel, text in files.items():
                (d / rel).parent.mkdir(parents=True, exist_ok=True)
                (d / rel).write_text(text)
            with contextlib.redirect_stdout(io.StringIO()):
                txs = _load(d)
                run_engine(txs)
            return txs

    def _base(self, **extra):
        files = {"Broker/21bitcoin-gesamt.csv": self.BTC21, "manual_buys.csv": self.NK_BUY}
        files.update(extra)
        return files

    def test_batch_tx_partly_to_second_nokyc_wallet_aborts(self):
        """B1/F1: ein Output in eine zweite noKYC-Wallet (Stufe 1 verbunden), einer in die KYC-Wallet."""
        files = self._base(**{
            "bitbox/kyc1.csv": self.BB_KYC + "2024-06-10T12:10:00+02:00,received,500000,satoshi,,,bc1q,ffff01,\n",
            "wallets/nokyc/nk.csv": self.SP + self.NK_IN + "2024-06-10 10:00:00,,-0.01501000,0.00499000,0.00001000,ffff01\n",
            "bitbox/nokyc/nk2.csv": self.BB + "2024-06-10T12:10:00+02:00,received,1000000,satoshi,,,bc1q,ffff01,\n"})
        with self.assertRaisesRegex(ValueError, "noKYC-Bestand"):
            self._run(files)

    def test_gift_from_nokyc_to_own_kyc_wallet_aborts(self):
        """B2: Schenkungswort im Label machte den Abgang zu GIFT_OUT — kein Giver, keine Sperre."""
        files = self._base(**{
            "bitbox/kyc1.csv": self.BB_KYC + "2024-06-10T12:10:00+02:00,received,500000,satoshi,,,bc1q,ffff01,\n",
            "wallets/nokyc/nk.csv": self.SP + self.NK_IN + "2024-06-10 10:00:00,Geschenk,-0.00501000,0.01499000,0.00001000,ffff01\n"})
        with self.assertRaisesRegex(ValueError, "noKYC-Bestand"):
            self._run(files)

    def test_unknown_fee_amount_near_kyc_deposit_without_txid_aborts(self):
        """B5: Abgang mit unbekannter Gebühr (−0,00501) an ein KYC-Konto ohne TX-ID (0,005)."""
        bison = ("Transaction ID; Transaction type; Currency; Asset; Eur (amount); Asset (amount); Asset (market price); "
                 "Fee; Date (UTC - Coordinated Universal Time)\n"
                 "TX-9; Deposit; ; Btc; 0.00; 0.00500000; 0.00; 0; 2024-06-10 11:00:00\n")
        files = self._base(**{
            "Broker/Bison-CSV-Gesamt.csv": bison,
            "wallets/nokyc/nk.csv": self.SP + self.NK_IN + "2024-06-10 10:00:00,,-0.00501000,0.01499000,,ffff01\n"})
        with self.assertRaisesRegex(ValueError, "noKYC-Bestand"):
            self._run(files)

    def test_aggregate_account_in_both_classes_aborts(self):
        """B3: Sammelimport-Konto „Hardware“ in KYC- und noKYC-Datei galt als eine Wallet."""
        head = '"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"\n'
        files = self._base(**{
            "Broker/cointracking_nokyc.csv": head + '"Trade","0.01000000","BTC","500","EUR","","","Hardware","","","01.04.2024 10:00:00"\n',
            "Broker/cointracking.csv": head + '"Deposit","0.00500000","BTC","","","","","Hardware","","","10.06.2024 11:00:00"\n'})
        with self.assertRaisesRegex(ValueError, "KYC- und im noKYC-Bestand"):
            self._run(files)

    def test_nokyc_only_year_gets_no_official_documents(self):
        """B6: ein Jahr nur mit noKYC-Gebühr erzeugte einen leeren Steuerreport/Nachweis."""
        from src.main import report_years
        files = self._base(**{
            "bitbox/kyc1.csv": self.BB_KYC,
            "wallets/nokyc/nk.csv": self.SP + self.NK_IN + "2025-03-01 10:00:00,Konsolidierung,-0.00001000,0.01999000,0.00001000,dd01\n"})
        txs = self._run(files)
        self.assertIn(2025, report_years(txs))
        self.assertNotIn(2025, report_years(txs, official=True))
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for rel, text in files.items():
                (d / rel).parent.mkdir(parents=True, exist_ok=True)
                (d / rel).write_text(text)
            names = {p.name for p in _run(d).iterdir()}
        self.assertNotIn("steuerreport_2025.txt", names)
        self.assertNotIn("steuernachweis_2025.txt", names)
        self.assertIn("nokyc_intern_2025.txt", names)

    def test_same_wallet_loaded_twice_aborts(self):
        """M1/F3: Jahres- und Gesamtexport derselben Sparrow-Wallet zählten doppelt."""
        body = self.SP + ("2024-05-02 14:00:00,,0.01000000,0.01000000,,aaaa01\n"
                          "2024-08-03 06:45:10,,-0.00502100,0.00497900,0.00002100,bbbb01\n")
        files = {"Broker/21bitcoin-gesamt.csv": self.BTC21, "wallets/cold_2024.csv": body, "wallets/cold_full.csv": body}
        with self.assertRaisesRegex(ValueError, "doppelt geladen"):
            self._run(files)

    def test_receive_only_wallet_twice_warns_batch_does_not_abort(self):
        """Nur Eingänge geteilt: Hinweis statt Abbruch (nicht unterscheidbar von gleichen Batch-Outputs)."""
        body = self.SP + ("2024-05-02 14:00:00,,0.01000000,0.01000000,,aaaa01\n"
                          "2024-06-02 14:00:00,,0.02000000,0.03000000,,aaaa02\n")
        self._run({"wallets/a.csv": body, "wallets/b.csv": body})
        self.assertTrue(any("dieselben Eingänge" in w.full for w in parsers.parser_warnings))

    def test_trezor_hint_of_nokyc_files_stays_internal_without_transactions(self):
        """N1: die Klasse kam aus den Transaktionen — leere noKYC-Dateien galten als KYC."""
        th = AuditRobust.TREZOR_HEAD
        files = {"wallets/nokyc/geheim_20250101T120000.csv": th, "wallets/nokyc/geheim_20250102T120000.csv": th}
        self._run(files)
        w = [w for w in parsers.parser_warnings if "Trezor: 2 Dateien" in w.full]
        self.assertTrue(w and all(x.internal for x in w))

    def test_control_characters_in_file_name_are_removed(self):
        """N2: Steuer-/Bidi-Zeichen im Dateinamen brachen Tabellenzeilen der internen Reports um."""
        txs = self._run({"wallets/a\x1b[31mb\u202ec.csv": self.SP + "2024-05-02 14:00:00,,0.01000000,0.01000000,,aaaa01\n"})
        self.assertTrue(all(c.isprintable() and c not in "\u202e" for c in txs[0].source))

    def test_more_strict_checks(self):
        """N5: leere Txid (Sparrow), Trezor-Zeit vor 2009, Einheit msat, Electrum confirmations −1."""
        with self.assertRaisesRegex(ValueError, "Txid fehlt"):
            AuditRobust()._parse_text("s.csv", self.SP + "2024-05-02 14:00:00,,0.01000000,0.01000000,,\n")
        with self.assertRaisesRegex(ValueError, "vor dem ersten Bitcoin-Block"):
            AuditRobust()._parse_text("t.csv", AuditRobust.TREZOR_HEAD + "0,,,RECV,ab,,,x,,0.1,BTC,,\n")
        with self.assertRaisesRegex(ValueError, "statt BTC"):
            AuditRobust()._parse_text("t.csv", AuditRobust.TREZOR_HEAD + "1717243200,,,RECV,ab,,,x,,100,msat,,\n")
        txs, _ = AuditRobust()._parse_text("e.csv", AuditCalc.EL + "ab,,,-1,0.1,0.,,0.,,2024-06-01 10:00:00\n")
        self.assertEqual(txs, [])

    def test_trezor_stamp_with_counter_suffix(self):
        from src.parsers.wallet_trezor import _EXPORT_STAMP
        for n in ("cold_20240101T120000_2", "cold_20240101T120000 (2)", "cold_20240101T120000"):
            self.assertEqual(_EXPORT_STAMP.sub("", n), "cold")


if __name__ == "__main__":
    unittest.main()
