"""Bisq-Parser: deutscher und englischer Export (Etappe 5, 03.10.2026).

Die englischen Spaltenköpfe und Werte stammen aus dem Bisq-Quellcode
(`ClosedTradesView.ColumnNames`, `displayStrings.properties`), nicht aus einer echten
Datei. Die Zeitstempel folgen Javas `DateFormat.DEFAULT` je Länder-Locale, deshalb
prüft der Test jede belegte Form einzeln.

Aufruf:  python -m unittest discover tests
"""
from __future__ import annotations
import sys
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import src.parsers as parsers                      # noqa: E402
from src.parsers import bisq                        # noqa: E402
from src.models import TZ_DE                        # noqa: E402

EXAMPLE_DE = ROOT / "examples" / "Broker" / "bisq.csv"
FIXTURE_EN = ROOT / "tests" / "fixtures" / "bisq_en.csv"

HEADER_EN = ("Trade ID,Date/Time,Market,Price,Deviation,Amount in BTC,Amount,Currency,"
             "Transaction Fee,Trade Fee BTC,Trade Fee BSQ,Buyer Deposit,Seller Deposit,Offer type,Status")
HEADER_DE = ("Handels-ID,Datum/Zeit,Markt,Preis,Abweichung,Betrag in BTC,Betrag,Währung,"
             "Transaktionsgebühr,Handelsgebühr BTC,Handelsgebühr BSQ,Käufer-Kaution,"
             "Verkäufer-Kaution,Angebotstyp,Status")


def _parse_text(text: str, name: str = "bisq_test.csv", encoding: str = "utf-8") -> list:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / name
        p.write_bytes(text.encode(encoding))
        return bisq.parse(p)


def _warnings() -> list[str]:
    return [w.full for w in parsers.parser_warnings]


class EnglishEqualsGerman(unittest.TestCase):
    def setUp(self):
        parsers.reset_warnings()

    def test_fixture_en_parses_to_same_transactions_as_example_de(self):
        de = bisq.parse(EXAMPLE_DE)
        en = bisq.parse(FIXTURE_EN)
        self.assertEqual(len(de), 3)
        self.assertEqual(de, en)
        self.assertEqual(_warnings(), [])

    def test_detect_language(self):
        self.assertEqual(bisq.detect_language(HEADER_DE.split(",")), "de")
        self.assertEqual(bisq.detect_language(HEADER_EN.split(",")), "en")
        self.assertEqual(bisq.detect_language(["﻿Trade ID"] + HEADER_EN.split(",")[1:]), "en")
        # Nur der Anfang passt → keine Bisq-Datei (andere Plattformen exportieren auch "Trade ID")
        self.assertIsNone(bisq.detect_language(["Trade ID", "Pair", "Side", "Amount"]))
        self.assertIsNone(bisq.detect_language(None))
        self.assertIsNone(bisq.detect_language([]))

    def test_bom_in_header_is_tolerated(self):
        rows = FIXTURE_EN.read_text(encoding="utf-8")
        txs = _parse_text(rows, encoding="utf-8-sig")
        self.assertEqual(len(txs), 3)
        self.assertEqual(_warnings(), [])

    def test_unknown_language_warns_and_returns_nothing(self):
        text = ("ID de transaction,Date/Heure,Marché,Prix,Écart,Montant en BTC,Montant,Devise,"
                "Frais de transaction,Frais BTC,Frais BSQ,Dépôt acheteur,Dépôt vendeur,Type d'offre,Statut\n"
                "1,15 mars 2024 14:22:10,BTC/EUR,61500.0000,2.50%,0.01,615,EUR,0,0,,0,0,Acheter BTC,Terminé\n")
        self.assertEqual(_parse_text(text), [])
        self.assertEqual(len(parsers.parser_warnings), 1)
        self.assertIn("Deutsch oder Englisch", _warnings()[0])
        self.assertTrue(parsers.parser_warnings[0].internal)


class EnglishDateFormats(unittest.TestCase):
    """Java `DateFormat.DEFAULT` (CLDR, Java 21) der englischen Länder-Locales."""

    CASES = {
        "15 Mar 2024 14:22:10": (2024, 3, 15, 14, 22, 10),          # en_GB, en_DE, en_AT, en_CH, en_IE
        "5 Nov 2024 18:03:55": (2024, 11, 5, 18, 3, 55),            # Tag ohne führende Null
        "15 Sept 2024 14:22:10": (2024, 9, 15, 14, 22, 10),         # „Sept" ab CLDR 38 (en_GB u. a.)
        "Mar 15, 2024 2:22:10 PM": (2024, 3, 15, 14, 22, 10),       # en_US (Java < 20)
        "Mar 15, 2024 2:22:10 PM": (2024, 3, 15, 14, 22, 10),  # en_US, Java ≥ 20: NNBSP vor PM
        "Mar 15, 2024 2:22:10 PM": (2024, 3, 15, 14, 22, 10),  # NBSP-Variante
        "Mar 15, 2024 2:22:10 p.m.": (2024, 3, 15, 14, 22, 10),     # en_CA
        "15 Mar 2024 2:22:10 pm": (2024, 3, 15, 14, 22, 10),        # en_AU, en_SG
        "15-Mar-2024 2:22:10 pm": (2024, 3, 15, 14, 22, 10),        # en_IN
        "15/03/2024 2:22:10 pm": (2024, 3, 15, 14, 22, 10),         # en_NZ (Tag zuerst)
        "Mar 15, 2024 12:05:00 AM": (2024, 3, 15, 0, 5, 0),         # Mitternacht
        "Mar 15, 2024 12:05:00 PM": (2024, 3, 15, 12, 5, 0),        # Mittag
        "Mar 15, 2024 11:59:59 PM": (2024, 3, 15, 23, 59, 59),
        "  15 Mar 2024   14:22:10 ": (2024, 3, 15, 14, 22, 10),     # Leerraum
    }

    def test_known_forms(self):
        for raw, parts in self.CASES.items():
            with self.subTest(raw=raw):
                self.assertEqual(bisq.parse_datetime_en(raw), datetime(*parts, tzinfo=TZ_DE))

    def test_rejects_garbage(self):
        for raw in ("", "2024-03-15 14:22:10", "15 Foo 2024 14:22:10", "15 Mar 24 14:22:10",
                    "Mar 15, 2024 14:22:10 PM", "Mar 15, 2024 0:22:10 PM", "32 Mar 2024 14:22:10",
                    "15 Mar 2024", "15 Mar 2024 14:22"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    bisq.parse_datetime_en(raw)

    def test_german_export_keeps_strict_format(self):
        self.assertEqual(bisq.parse_datetime_de("15.03.2024 14:22:10"), datetime(2024, 3, 15, 14, 22, 10, tzinfo=TZ_DE))
        with self.assertRaises(ValueError):
            bisq.parse_datetime_de("15 Mar 2024 14:22:10")

    def test_unreadable_date_in_file_is_a_hard_error_naming_the_trade(self):
        parsers.reset_warnings()
        text = HEADER_EN + "\n100009,2024-03-15T14:22:10,BTC/EUR,61500.0000,2.50%,0.01,615,EUR,0,0,,0,0,Buy BTC,Completed\n"
        with self.assertRaises(ValueError) as ctx:
            _parse_text(text)
        self.assertIn("100009", str(ctx.exception))


class RowHandling(unittest.TestCase):
    def setUp(self):
        parsers.reset_warnings()

    def _row(self, *, market="BTC/EUR", cur="EUR", offer="Buy BTC", status="Completed",
             date="15 Mar 2024 14:22:10", tid="7") -> str:
        return f"{tid},{date},{market},61500.0000,2.50%,0.01000000,615,{cur},0.00005000,0.000070,,0.0010,0.0010,{offer},{status}"

    def test_english_buy_values(self):
        txs = _parse_text(HEADER_EN + "\n" + self._row() + "\n")
        self.assertEqual(len(txs), 1)
        t = txs[0]
        self.assertEqual(t.btc_amount, Decimal("0.01000000"))
        self.assertEqual(t.eur_amount, Decimal("615"))
        self.assertEqual(t.eur_price_per_btc, Decimal("61500.0000"))
        self.assertEqual(t.fee_btc, Decimal("0.00012000"))
        self.assertEqual(t.fee_eur, Decimal("7.38"))
        self.assertTrue(t.no_kyc)
        self.assertTrue(t.direct)
        self.assertEqual(t.source, "bisq")
        self.assertEqual(t.tx_id, "7")

    def test_english_sell_warns(self):
        txs = _parse_text(HEADER_EN + "\n" + self._row(offer="Sell BTC") + "\n")
        self.assertEqual(txs, [])
        self.assertEqual(len(parsers.parser_warnings), 1)
        self.assertIn("Bisq-Verkauf", _warnings()[0])
        self.assertIn("manual_sales.csv", _warnings()[0])
        self.assertEqual(parsers.parser_warnings[0].year, 2024)

    def test_sell_only_file_gets_no_second_summary_warning(self):
        # Altfehler: zusätzlich zur Verkaufswarnung kam „keine Bisq-Transaktion erkannt"
        _parse_text(HEADER_EN + "\n" + self._row(offer="Sell BTC") + "\n" + self._row(offer="Sell BTC", tid="8") + "\n")
        self.assertEqual(len(parsers.parser_warnings), 2)
        self.assertTrue(all("Bisq-Verkauf" in m for m in _warnings()))

    def test_english_not_completed_is_counted(self):
        txs = _parse_text(HEADER_EN + "\n" + self._row(status="Canceled") + "\n" + self._row(status="Arbitrated", tid="8") + "\n")
        self.assertEqual(txs, [])
        msgs = _warnings()
        self.assertEqual(len(msgs), 2)
        self.assertTrue(any("'Canceled'" in m for m in msgs))
        self.assertTrue(any("'Arbitrated'" in m for m in msgs))

    def test_non_eur_fiat_warns(self):
        txs = _parse_text(HEADER_EN + "\n" + self._row(market="BTC/USD", cur="USD") + "\n")
        self.assertEqual(txs, [])
        self.assertIn("in USD statt EUR", _warnings()[0])

    def test_altcoin_buy_is_a_btc_disposal_warning(self):
        # „Buy XMR" auf dem Markt XMR/BTC: BTC hergegeben → Veräußerung, bisher nur stumm gezählt
        for header, offer in ((HEADER_EN, "Buy XMR"), (HEADER_DE, "XMR kaufen")):
            parsers.reset_warnings()
            en = header is HEADER_EN
            txs = _parse_text(header + "\n" + self._row(market="XMR/BTC", cur="XMR", offer=offer,
                                                          date="15 Mar 2024 14:22:10" if en else "15.03.2024 14:22:10",
                                                          status="Completed" if en else "Abgeschlossen") + "\n")
            with self.subTest(offer=offer):
                self.assertEqual(txs, [])
                self.assertEqual(len(parsers.parser_warnings), 1)
                self.assertIn("VERÄUSSERUNG von BTC", _warnings()[0])
                self.assertIn("manual_sales.csv", _warnings()[0])
                self.assertTrue(parsers.parser_warnings[0].internal)
                self.assertEqual(parsers.parser_warnings[0].year, 2024)

    def test_altcoin_sell_is_a_btc_acquisition_warning(self):
        txs = _parse_text(HEADER_EN + "\n" + self._row(market="BSQ/BTC", cur="BSQ", offer="Sell BSQ") + "\n")
        self.assertEqual(txs, [])
        self.assertIn("ANSCHAFFUNG von BTC", _warnings()[0])
        self.assertIn("manual_buys.csv", _warnings()[0])

    def test_real_world_shape_of_english_export(self):
        # Form eines veröffentlichten englischen Exports (rotki-Testdaten, eigene Werte hier):
        # Deviation „N/A", Mengen ohne 8 Nachkommastellen, leere Beträge bei Canceled,
        # Handelsgebühr in BSQ statt BTC, Altcoin-Märkte, Status Mediated.
        text = HEADER_EN + "\n" + "\n".join([
            "xxA,10 Mar 2021 10:40:20,BTC/EUR,49000.0000,N/A,0.01,490,EUR,0.00005,,0.29,0.00250,0.00250,Sell BTC,Mediated",
            "xxB,11 Dec 2020 17:13:40,BTC/EUR,15883.3283,-0.10%,0.05,794,EUR,0.0001,,2.01,0.00165,0.00165,Sell BTC,Completed",
            "552,1 Jan 2020 17:01:24,BSQ/BTC,0.00008487,N/A,0.0099,116.65,BSQ,0.0001,0.00005940,,0.0010,0.0050,Buy BSQ,Mediated",
            "GxxL,23 Dec 2019 06:33:02,BTC/EUR,6785.6724,2.00%,0.01,68,EUR,0.0001,0.00109140,,0.0010914,0.0009095,Buy BTC,Completed",
            "04555,11 Jun 2019 23:31:21,BTC/EUR,10020.0000,N/A,,,EUR,0.00003120,0.0001,,0.0050,0.0050,Sell BTC,Canceled",
            "LxxAob,11 Jun 2019 20:21:44,DASH/BTC,0.01541873,3.00%,0.30,19.45685539,DASH,0.000228,0.0009,,0.03,0.03,Sell DASH,Completed",
            "VxxABMN,21 Dec 2018 18:29:18,BTC/EUR,3376.9400,0.00%,0.1850,625,EUR,0.000096,0.000370,,0.01,0.0030,Buy BTC,Completed",
        ]) + "\n"
        txs = _parse_text(text)
        self.assertEqual([t.tx_id for t in txs], ["GxxL", "VxxABMN"])
        self.assertEqual(txs[0].date, datetime(2019, 12, 23, 6, 33, 2, tzinfo=TZ_DE))
        self.assertEqual(txs[0].fee_btc, Decimal("0.00119140"))
        self.assertEqual(txs[1].btc_amount, Decimal("0.1850"))
        msgs = _warnings()
        self.assertEqual(len([m for m in msgs if "Bisq-Verkauf" in m]), 1)            # nur der abgeschlossene Verkauf
        self.assertEqual(len([m for m in msgs if "ANSCHAFFUNG von BTC" in m]), 1)    # Sell DASH
        self.assertTrue(any("'Mediated'" in m for m in msgs))
        self.assertTrue(any("'Canceled'" in m for m in msgs))
        self.assertFalse(any("BSQ" in m and "ANSCHAFFUNG" in m for m in msgs))      # Buy BSQ war Mediated → nur gezählt

    def test_german_behaviour_unchanged(self):
        row = "100001,15.03.2024 14:22:10,BTC/EUR,61500.0000,2.50%,0.01000000,615,EUR,0.00005000,0.000070,,0.0010,0.0010,BTC kaufen,Abgeschlossen"
        txs = _parse_text(HEADER_DE + "\n" + row + "\n")
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0].date, datetime(2024, 3, 15, 14, 22, 10, tzinfo=TZ_DE))
        self.assertEqual(_warnings(), [])


if __name__ == "__main__":
    unittest.main()
