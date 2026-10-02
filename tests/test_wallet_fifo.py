"""Tests zur walletbezogenen FiFo-Rechnung (BMF 06.03.2025 Rn. 62).

Etappe 1: Übertrags-Zuordnung (src/transfer_matching.py).
Etappe 2: Engine mit einem FiFo-Topf je Wallet (src/fifo_engine.py).

Aufruf:  python -m unittest discover tests
"""
from __future__ import annotations
import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.models import Transaction, TxType, ANY_WALLET            # noqa: E402
from src.transfer_matching import match_transfers, LinkKind, giver_residual  # noqa: E402
from src.fifo_engine import FifoEngine                              # noqa: E402

T0 = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)


def tx(typ, btc, source, hours=0, fee_btc="0", tx_id="", no_kyc=False, direct=False, wallet=""):
    eur = D("0") if typ in (TxType.TRANSFER_IN, TxType.TRANSFER_OUT) else D("100")
    return Transaction(
        date=T0 + timedelta(hours=hours), type=typ, btc_amount=D(btc),
        eur_amount=eur, eur_price_per_btc=D("0"), fee_eur=D("0"), source=source,
        tx_id=tx_id, note="", no_kyc=no_kyc, fee_btc=D(fee_btc), wallet=wallet, direct=direct,
    )


OUT, IN, BUY, SELL = TxType.TRANSFER_OUT, TxType.TRANSFER_IN, TxType.BUY, TxType.SELL


class MatchingTest(unittest.TestCase):

    def test_txid_links_two_bitbox_wallets(self):
        a = tx(OUT, "0.5", "bitbox:a", fee_btc="0.0001", tx_id="abc")
        b = tx(IN, "0.5", "bitbox:b", hours=1, tx_id="abc")
        r = match_transfers([a, b])
        self.assertEqual(len(r.links), 1)
        self.assertEqual(r.links[0].method, "tx-id")
        self.assertFalse(r.unmatched_out or r.unmatched_in or r.warnings)

    def test_amount_match_receive_before_send(self):
        # Zeitzonen-Versatz: Eingang 4 h VOR der Broker-Auszahlung (wie in examples/)
        out = tx(OUT, "0.002", "swissquote", hours=4, tx_id="swissquote-WD-1")
        inn = tx(IN, "0.002", "bitbox:main", tx_id="bbbb")
        r = match_transfers([out, inn])
        self.assertEqual([(l.kind, l.method) for l in r.links], [(LinkKind.TRANSFER, "betrag")])

    def test_amount_match_fee_included_in_send(self):
        # Abgang enthält die Gebühr (Abgang − Gebühr = Eingang): kein offener Rest
        out = tx(OUT, "0.0101", "21bitcoin", fee_btc="0.0001")
        inn = tx(IN, "0.01", "bitbox:main", hours=1)
        r = match_transfers([out, inn])
        self.assertEqual(len(r.links), 1)
        self.assertEqual(giver_residual(out, r.links[0].btc_amount), D("0"))
        self.assertFalse(r.unmatched_out)

    def test_outside_window_not_linked(self):
        out = tx(OUT, "0.01", "21bitcoin")
        inn = tx(IN, "0.01", "bitbox:main", hours=49)
        r = match_transfers([out, inn])
        self.assertFalse(r.links)
        self.assertEqual(r.unmatched_out, [out])
        self.assertEqual(r.unmatched_in, [inn])
        self.assertEqual(len(r.warnings), 1)
        self.assertIn("kein passender Eingang", r.warnings[0].full)

    def test_same_wallet_pair_chronological(self):
        # Gleich hohe Sparplan-Auszahlungen zwischen denselben Wallets: eindeutig genug
        outs = [tx(OUT, "0.001", "21bitcoin", hours=24 * i) for i in range(3)]
        ins = [tx(IN, "0.001", "bitbox:main", hours=24 * i + 1) for i in range(3)]
        r = match_transfers(outs + ins)
        self.assertEqual(len(r.links), 3)
        for l in r.links:
            self.assertEqual(outs.index(l.giver), ins.index(l.taker))
        self.assertFalse(r.warnings)

    def test_ambiguous_across_wallets_not_linked(self):
        # Zwei Broker zahlen am selben Tag gleich viel aus, eine Wallet empfängt beides
        # — welche Lots wohin? Steuerlich relevant, also nicht raten.
        o1 = tx(OUT, "0.01", "21bitcoin")
        o2 = tx(OUT, "0.01", "strike", hours=1)
        i1 = tx(IN, "0.01", "bitbox:main", hours=2)
        i2 = tx(IN, "0.01", "bitbox:main", hours=3)
        r = match_transfers([o1, o2, i1, i2])
        self.assertFalse(r.links)
        self.assertEqual(len(r.warnings), 1)
        self.assertIn("nicht eindeutig", r.warnings[0].full)

    def test_mutual_unique_pair_resolves_first(self):
        o1 = tx(OUT, "0.01", "21bitcoin")
        o2 = tx(OUT, "0.02", "strike")
        i1 = tx(IN, "0.01", "bitbox:a", hours=1)
        i2 = tx(IN, "0.02", "bitbox:b", hours=1)
        r = match_transfers([o1, o2, i1, i2])
        pairs = {(l.giver.source, l.taker.source) for l in r.links}
        self.assertEqual(pairs, {("21bitcoin", "bitbox:a"), ("strike", "bitbox:b")})

    def test_delivery_of_direct_buy(self):
        buy = tx(BUY, "0.005", "pocket", direct=True)
        inn = tx(IN, "0.005", "bitbox:main", hours=0.1)
        r = match_transfers([buy, inn])
        self.assertEqual([l.kind for l in r.links], [LinkKind.LIEFERUNG])

    def test_delivery_minus_trade_fee_days_later(self):
        # Bisq: Handelsgebühr in BTC, Auszahlung Tage später
        buy = tx(BUY, "0.01", "bisq", fee_btc="0.00012", no_kyc=True, direct=True)
        inn = tx(IN, "0.00988", "bitbox:nokyc", hours=24 * 5, no_kyc=True)
        r = match_transfers([buy, inn])
        self.assertEqual([l.kind for l in r.links], [LinkKind.LIEFERUNG])

    def test_direct_sale_consumes_send(self):
        # P2P-Verkauf: der BitBox-Abgang IST die Lieferung an den Käufer
        out = tx(OUT, "0.005", "bitbox:main", fee_btc="0.00001")
        sale = tx(SELL, "0.005", "manual", hours=20, direct=True, wallet=ANY_WALLET)
        r = match_transfers([out, sale])
        self.assertEqual([l.kind for l in r.links], [LinkKind.VERKAUF])
        self.assertFalse(r.unmatched_out)

    def test_direct_sale_with_other_explicit_wallet_not_linked(self):
        out = tx(OUT, "0.005", "bitbox:main")
        sale = tx(SELL, "0.005", "manual", direct=True, wallet="bitbox:other")
        r = match_transfers([out, sale])
        self.assertFalse(r.links)
        self.assertEqual(r.unmatched_sells, [sale])

    def test_kyc_nokyc_never_linked_warning_internal(self):
        out = tx(OUT, "0.01", "bitbox:main")
        inn = tx(IN, "0.01", "bitbox:nokyc", hours=1, no_kyc=True)
        r = match_transfers([out, inn])
        self.assertFalse(r.links)
        internal = [w for w in r.warnings if w.internal]
        official = [w for w in r.warnings if not w.internal]
        self.assertEqual(len(internal), 1)
        self.assertIn("noKYC", internal[0].full)
        for w in official:
            self.assertNotIn("KYC", str(w))
            self.assertNotIn("nokyc", str(w).lower())

    def test_official_warning_hides_bitbox_name(self):
        out = tx(OUT, "0.01", "bitbox:Sparschwein")
        r = match_transfers([out])
        self.assertEqual(len(r.warnings), 1)
        w = r.warnings[0]
        self.assertFalse(w.internal)
        self.assertIn("Sparschwein", w.full)
        self.assertNotIn("Sparschwein", str(w))

    def test_near_miss_only_suggested(self):
        out = tx(OUT, "0.0100", "21bitcoin")
        inn = tx(IN, "0.0099", "bitbox:main", hours=1)
        r = match_transfers([out, inn])
        self.assertFalse(r.links)
        self.assertIn("Möglicher Eingang", r.warnings[0].full)

    def test_txid_batch_to_two_wallets(self):
        out = tx(OUT, "0.3", "bitbox:a", fee_btc="0.0001", tx_id="batch")
        b = tx(IN, "0.1", "bitbox:b", tx_id="batch")
        c = tx(IN, "0.2", "bitbox:c", tx_id="batch")
        r = match_transfers([out, b, c])
        self.assertEqual(len(r.links), 2)
        self.assertFalse(r.unmatched_out)

    def test_zero_amount_self_transfer_ignored(self):
        own = tx(OUT, "0", "bitbox:a", fee_btc="0.00001")
        r = match_transfers([own])
        self.assertFalse(r.links or r.unmatched_out or r.warnings)



def at(y, m, d, h=12):
    return datetime(y, m, d, h, 0, tzinfo=timezone.utc)


def tx_at(when, typ, btc, source, eur="0", **kw):
    t = tx(typ, btc, source, **kw)
    t.date = when
    t.eur_amount = D(eur)
    return t


def run(txs, mode="wallet"):
    e = FifoEngine(mode=mode)
    e.process(txs)
    return e


def held(engine, wallet):
    return sum((l.btc_amount for l in engine.remaining_lots() if l.wallet == wallet), D("0"))


class WalletEngineTest(unittest.TestCase):

    def test_sale_uses_only_own_wallet(self):
        # Kern von Rn. 62: Broker B verkauft seinen jungen Kauf, nicht das alte Lot von A
        txs = [tx_at(at(2022, 1, 10), BUY, "0.01", "brokerA", eur="300"),
               tx_at(at(2024, 1, 10), BUY, "0.01", "brokerB", eur="400"),
               tx_at(at(2024, 6, 10), SELL, "0.01", "brokerB", eur="600")]
        sale = run(txs).sell_results[0]
        self.assertEqual([m.lot_wallet for m in sale.matches], ["brokerB"])
        self.assertFalse(sale.matches[0].is_tax_free)
        # Zum Vergleich der alte gemeinsame Topf: nimmt das Lot von A, steuerfrei
        self.assertTrue(run(txs, mode="global").sell_results[0].matches[0].is_tax_free)

    def test_transferred_lots_sorted_by_purchase_date(self):
        # Übertragenes Lot von 2022 wird VOR dem eigenen Kauf von 2023 verbraucht
        txs = [tx_at(at(2022, 1, 10), BUY, "0.01", "brokerA", eur="300"),
               tx_at(at(2023, 5, 1), BUY, "0.01", "bison", eur="250"),
               tx_at(at(2024, 2, 1, 10), OUT, "0.01", "brokerA"),
               tx_at(at(2024, 2, 1, 11), IN, "0.01", "bison"),
               tx_at(at(2024, 2, 2), SELL, "0.01", "bison", eur="400")]
        sale = run(txs).sell_results[0]
        self.assertEqual(de_year(sale.matches[0].lot_purchase_date), 2022)
        self.assertEqual(sale.matches[0].lot_source, "brokerA")
        self.assertEqual(held(run(txs), "bison"), D("0.01"))

    def test_unmatched_send_goes_extern(self):
        txs = [tx_at(at(2024, 1, 10), BUY, "0.01", "strike", eur="400"),
               tx_at(at(2024, 2, 1), OUT, "0.004", "strike")]
        e = run(txs)
        self.assertEqual(held(e, "strike"), D("0.006"))
        self.assertEqual(held(e, "extern"), D("0.004"))

    def test_direct_sale_consumes_once_from_sending_wallet(self):
        txs = [tx_at(at(2023, 1, 10), BUY, "0.01", "brokerA", eur="300"),
               tx_at(at(2023, 1, 11, 10), OUT, "0.01", "brokerA"),
               tx_at(at(2023, 1, 11, 11), IN, "0.01", "bitbox:main"),
               tx_at(at(2024, 6, 15, 18), OUT, "0.004", "bitbox:main", fee_btc="0.00001"),
               tx_at(at(2024, 6, 15), SELL, "0.004", "manual", eur="250",
                     direct=True, wallet=ANY_WALLET)]
        e = run(txs)
        self.assertEqual([m.lot_wallet for m in e.sell_results[0].matches], ["bitbox:main"])
        self.assertEqual(held(e, "bitbox:main"), D("0.00599"))   # 0.01 − 0.004 − Gebühr
        self.assertEqual(held(e, "extern"), D("0"))
        self.assertFalse([w for w in e.warnings if "kann nicht vollständig" in w.full])

    def test_sale_without_wallet_never_touches_tracked_wallet(self):
        txs = [tx_at(at(2023, 1, 10), BUY, "0.01", "brokerA", eur="300"),
               tx_at(at(2024, 6, 15), SELL, "0.004", "manual", eur="250",
                     direct=True, wallet=ANY_WALLET)]
        e = run(txs)
        self.assertEqual(e.sell_results[0].unmatched_btc, D("0.004"))
        self.assertEqual(held(e, "brokerA"), D("0.01"))

    def test_sale_without_wallet_uses_extern_and_undelivered(self):
        txs = [tx_at(at(2023, 1, 10), BUY, "0.003", "strike", eur="90"),
               tx_at(at(2023, 2, 1), OUT, "0.003", "strike"),             # → extern
               tx_at(at(2023, 3, 1), BUY, "0.001", "pocket", eur="30", direct=True),
               tx_at(at(2024, 6, 15), SELL, "0.004", "manual", eur="250",
                     direct=True, wallet=ANY_WALLET)]
        sale = run(txs).sell_results[0]
        self.assertTrue(sale.is_fully_covered)
        self.assertEqual({m.lot_wallet for m in sale.matches}, {"extern", "pocket"})

    def test_transfer_fee_from_sending_wallet(self):
        txs = [tx_at(at(2023, 1, 10), BUY, "0.01", "brokerA", eur="300"),
               tx_at(at(2024, 1, 10), BUY, "0.01", "bison", eur="400"),
               tx_at(at(2024, 3, 1, 10), OUT, "0.005", "brokerA", fee_btc="0.0001"),
               tx_at(at(2024, 3, 1, 11), IN, "0.005", "bison")]
        e = run(txs)
        self.assertEqual([m.lot_wallet for m in e.fee_results[0].matches], ["brokerA"])
        self.assertEqual(held(e, "brokerA"), D("0.0049"))
        self.assertEqual(held(e, "bison"), D("0.015"))

    def test_kyc_never_receives_nokyc_lots(self):
        txs = [tx_at(at(2023, 1, 10), BUY, "0.01", "bisq", eur="300", no_kyc=True, direct=True),
               tx_at(at(2023, 1, 11), IN, "0.01", "bitbox:main"),        # KYC-Wallet
               tx_at(at(2024, 1, 11), OUT, "0.01", "bitbox:main"),
               tx_at(at(2024, 1, 11, 13), IN, "0.01", "bison"),
               tx_at(at(2024, 1, 12), SELL, "0.01", "bison", eur="400")]
        e = run(txs)
        for r in e.sell_results:
            self.assertFalse(any(m.lot_source == "bisq" for m in r.matches))
        self.assertTrue(all(l.no_kyc for l in e.remaining_lots() if l.source == "bisq"))

    def test_year_end_keeps_lots_in_transit(self):
        # Abgang 31.12. abends, Eingang 01.01. — der Bestand zum 31.12. verliert nichts
        txs = [tx_at(at(2023, 6, 1), BUY, "0.01", "brokerA", eur="300"),
               tx_at(datetime(2023, 12, 31, 22, 0, tzinfo=timezone.utc), OUT, "0.01", "brokerA"),
               tx_at(datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc), IN, "0.01", "bitbox:main")]
        e = run(txs)
        self.assertEqual(sum(l.btc_amount for l in e.lots_at_year_end(2023)), D("0.01"))
        self.assertEqual(held(e, "bitbox:main"), D("0.01"))
        self.assertEqual(e.lots_at_year_end(2022), [])

    def test_year_end_snapshot_matches_rerun_in_global_mode(self):
        txs = [tx_at(at(2022, 1, 10), BUY, "0.01", "brokerA", eur="300"),
               tx_at(at(2023, 1, 10), SELL, "0.004", "brokerA", eur="200"),
               tx_at(at(2024, 1, 10), SELL, "0.002", "brokerA", eur="200")]
        e = run(txs, mode="global")
        self.assertEqual(sum(l.btc_amount for l in e.lots_at_year_end(2023)), D("0.006"))
        self.assertEqual(sum(l.btc_amount for l in e.lots_at_year_end(2024)), D("0.004"))


def de_year(dt):
    from src.models import de_date
    return de_date(dt).year


if __name__ == "__main__":
    unittest.main()
