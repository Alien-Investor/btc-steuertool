"""FiFo-Engine: Lot-Verwaltung und Gewinnberechnung nach deutschem Steuerrecht."""
from __future__ import annotations
from collections import deque
from decimal import Decimal, ROUND_HALF_UP
from datetime import timezone

from .models import Transaction, TxType, Lot, DisposalMatch, SellResult

HOLDING_PERIOD_DAYS = 365
CENT = Decimal("0.01")


def _round(val: Decimal) -> Decimal:
    return val.quantize(CENT, rounding=ROUND_HALF_UP)


class FifoEngine:
    def __init__(self):
        self.lots: deque[Lot] = deque()
        self.sell_results: list[SellResult] = []
        self.warnings: list[str] = []

    def process(self, transactions: list[Transaction]) -> None:
        """Verarbeitet alle Transaktionen chronologisch."""
        sorted_txs = sorted(transactions, key=lambda t: t.date)
        for tx in sorted_txs:
            if tx.type == TxType.BUY:
                self._add_lot(tx)
            elif tx.type == TxType.SELL:
                self._process_sell(tx)
            # TRANSFER_IN / TRANSFER_OUT: keine Lot-Änderung

    def _add_lot(self, tx: Transaction) -> None:
        # Einstandspreis inkl. Kaufgebühren
        cost_per_btc = _round((tx.eur_amount + tx.fee_eur) / tx.btc_amount) if tx.btc_amount else Decimal("0")
        self.lots.append(Lot(
            purchase_date=tx.date,
            btc_amount=tx.btc_amount,
            cost_per_btc=cost_per_btc,
            source=tx.source,
            tx_id=tx.tx_id,
            no_kyc=tx.no_kyc,
        ))

    def _process_sell(self, tx: Transaction) -> None:
        # Netto-Verkaufspreis pro BTC (Erlös minus Verkaufsgebühren)
        net_proceeds = tx.eur_amount - tx.fee_eur
        net_sell_price_per_btc = _round(net_proceeds / tx.btc_amount) if tx.btc_amount else Decimal("0")

        remaining = tx.btc_amount
        matches: list[DisposalMatch] = []

        while remaining > Decimal("0"):
            if not self.lots:
                self.warnings.append(
                    f"WARNUNG: Verkauf am {tx.date.date()} über {remaining:.8f} BTC "
                    f"kann nicht vollständig FiFo-Lots zugeordnet werden. "
                    f"Fehlende Menge: {remaining:.8f} BTC. "
                    f"Prüfe ob alle Käufe in den CSV-Dateien vorhanden sind."
                )
                break

            lot = self.lots[0]

            if lot.btc_amount <= remaining:
                # Dieses Lot wird vollständig verbraucht
                used = lot.btc_amount
                self.lots.popleft()
            else:
                # Lot wird nur teilweise verbraucht
                used = remaining
                lot.btc_amount -= used

            holding_days = (tx.date.replace(tzinfo=timezone.utc) - lot.purchase_date).days
            is_tax_free = holding_days > HOLDING_PERIOD_DAYS
            gain = _round((net_sell_price_per_btc - lot.cost_per_btc) * used)

            matches.append(DisposalMatch(
                lot_purchase_date=lot.purchase_date,
                lot_source=lot.source,
                btc_used=used,
                cost_per_btc=lot.cost_per_btc,
                net_sell_price_per_btc=net_sell_price_per_btc,
                gain_eur=gain,
                holding_days=holding_days,
                is_tax_free=is_tax_free,
            ))

            remaining -= used

        self.sell_results.append(SellResult(sell_tx=tx, matches=matches))

    def remaining_lots(self) -> list[Lot]:
        return list(self.lots)

    def total_btc_held(self) -> Decimal:
        return sum((lot.btc_amount for lot in self.lots), Decimal("0"))
