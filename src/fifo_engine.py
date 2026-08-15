"""FiFo-Engine: Lot-Verwaltung und Gewinnberechnung nach deutschem Steuerrecht.

Zwei strikt getrennte FiFo-Pools:
- KYC-Pool:   Broker-Käufe (no_kyc=False). KYC-Verkäufe konsumieren NUR diesen Pool.
- noKYC-Pool: Bisq/manual_buys (no_kyc=True). noKYC-Verkäufe konsumieren NUR diesen.

Dadurch kann ein noKYC-Lot niemals in der FiFo-Zuordnung eines offiziellen
Finanzamt-Dokuments auftauchen.
"""
from __future__ import annotations
from collections import deque
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .models import Transaction, TxType, Lot, DisposalMatch, SellResult, de_date
from .parsers import ParserWarning

CENT = Decimal("0.01")


def _round(val: Decimal) -> Decimal:
    return val.quantize(CENT, rounding=ROUND_HALF_UP)


def _is_tax_free(purchase: datetime, sale: datetime) -> bool:
    """Haltefrist nach § 23 EStG i.V.m. §§ 187 Abs. 1, 188 Abs. 2/3 BGB.

    Die Jahresfrist endet mit Ablauf des Tages im Folgejahr, der dem
    Anschaffungstag entspricht. Steuerfrei ist erst die Veräußerung DANACH.
    Kalenderdatum-Vergleich statt Tageszählung — korrekt auch in Schaltjahren
    (366 Tage können genau ein Jahr sein, nicht mehr als ein Jahr).
    Maßgeblich ist das deutsche Kalenderdatum (Europe/Berlin), nicht UTC.
    """
    p = de_date(purchase)
    try:
        anniversary = p.replace(year=p.year + 1)
    except ValueError:
        # 29. Februar: Frist endet mit Ablauf des 28. Februar (§ 188 Abs. 3 BGB)
        anniversary = p.replace(year=p.year + 1, day=28)
    return de_date(sale) > anniversary


class FifoEngine:
    def __init__(self):
        self.lots: deque[Lot] = deque()        # KYC-Pool
        self.nokyc_lots: deque[Lot] = deque()  # noKYC-Pool (strikt getrennt)
        self.sell_results: list[SellResult] = []
        self.warnings: list[str] = []

    # Bei identischem Zeitstempel zuerst Käufe, dann Verkäufe. manual_buys /
    # manual_sales stempeln beide exakt 12:00 UTC — ohne diesen Tiebreak liefe
    # ein gleichtägiger Verkauf vor seinem Kauf und fände kein Lot.
    _TYPE_ORDER = {
        TxType.BUY: 0,
        TxType.TRANSFER_IN: 1,
        TxType.TRANSFER_OUT: 2,
        TxType.SELL: 3,
    }

    def process(self, transactions: list[Transaction]) -> None:
        """Verarbeitet alle Transaktionen chronologisch."""
        sorted_txs = sorted(transactions, key=lambda t: (t.date, self._TYPE_ORDER[t.type]))
        for tx in sorted_txs:
            if tx.type == TxType.BUY:
                self._add_lot(tx)
            elif tx.type == TxType.SELL:
                self._process_sell(tx)
            # TRANSFER_IN / TRANSFER_OUT: keine Lot-Änderung

    def _add_lot(self, tx: Transaction) -> None:
        # Einstandspreis inkl. Kaufgebühren
        cost_per_btc = _round((tx.eur_amount + tx.fee_eur) / tx.btc_amount) if tx.btc_amount else Decimal("0")
        pool = self.nokyc_lots if tx.no_kyc else self.lots
        pool.append(Lot(
            purchase_date=tx.date,
            btc_amount=tx.btc_amount,
            cost_per_btc=cost_per_btc,
            source=tx.source,
            tx_id=tx.tx_id,
            no_kyc=tx.no_kyc,
        ))

    def _process_sell(self, tx: Transaction) -> None:
        # Pool nach Verkaufsart wählen — KYC-Verkäufe sehen noKYC-Lots NIE
        pool = self.nokyc_lots if tx.no_kyc else self.lots

        # Netto-Verkaufspreis pro BTC (Erlös minus Verkaufsgebühren)
        net_proceeds = tx.eur_amount - tx.fee_eur
        net_sell_price_per_btc = _round(net_proceeds / tx.btc_amount) if tx.btc_amount else Decimal("0")

        remaining = tx.btc_amount
        matches: list[DisposalMatch] = []

        while remaining > Decimal("0"):
            if not pool:
                # pool_label NICHT in die Meldung: bei noKYC-Verkäufen ginge das
                # Wort "noKYC" sonst in steuerreport/steuernachweis ans Finanzamt.
                # Stattdessen internal=True → nur interner Report + GUI-Log.
                self.warnings.append(ParserWarning(
                    f"WARNUNG: Verkauf am {de_date(tx.date)} über {remaining:.8f} BTC "
                    f"kann nicht vollständig FiFo-Lots zugeordnet werden. "
                    f"Fehlende Menge: {remaining:.8f} BTC. "
                    f"Prüfe ob alle Käufe in den CSV-Dateien vorhanden sind.",
                    internal=tx.no_kyc,
                ))
                break

            lot = pool[0]

            if lot.btc_amount <= remaining:
                # Dieses Lot wird vollständig verbraucht
                used = lot.btc_amount
                pool.popleft()
            else:
                # Lot wird nur teilweise verbraucht
                used = remaining
                lot.btc_amount -= used

            # Beide Zeitstempel sind timezone-aware — direkte Differenz.
            # (KEIN replace(tzinfo=...): das würde Nicht-UTC-Zeitstempel verfälschen.)
            holding_days = (tx.date - lot.purchase_date).days
            tax_free = _is_tax_free(lot.purchase_date, tx.date)
            gain = _round((net_sell_price_per_btc - lot.cost_per_btc) * used)

            matches.append(DisposalMatch(
                lot_purchase_date=lot.purchase_date,
                lot_source=lot.source,
                btc_used=used,
                cost_per_btc=lot.cost_per_btc,
                net_sell_price_per_btc=net_sell_price_per_btc,
                gain_eur=gain,
                holding_days=holding_days,
                is_tax_free=tax_free,
            ))

            remaining -= used

        # remaining NICHT verwerfen: > 0 heißt, dass ein Teil der veräußerten
        # Menge ohne Anschaffungsgeschäft dasteht. Die Reports müssen das sehen,
        # sonst bescheinigen sie Steuerfreiheit für eine nie berechnete Haltedauer.
        self.sell_results.append(SellResult(
            sell_tx=tx,
            matches=matches,
            unmatched_btc=max(remaining, Decimal("0")),
        ))

    def remaining_lots(self) -> list[Lot]:
        """Alle verbleibenden Lots (KYC + noKYC) — Filterung übernimmt der Report."""
        return list(self.lots) + list(self.nokyc_lots)

    def total_btc_held(self) -> Decimal:
        return sum((lot.btc_amount for lot in self.remaining_lots()), Decimal("0"))
