"""FiFo-Engine: Lot-Verwaltung und Gewinnberechnung nach deutschem Steuerrecht.

Zwei strikt getrennte FiFo-Pools:
- KYC-Pool:   Broker-Käufe (no_kyc=False). KYC-Verkäufe konsumieren NUR diesen Pool.
- noKYC-Pool: Bisq/manual_buys (no_kyc=True). noKYC-Verkäufe konsumieren NUR diesen.

Dadurch kann ein noKYC-Lot niemals in der FiFo-Zuordnung eines offiziellen
Finanzamt-Dokuments auftauchen.

Drei Arten von Bestandsabgang (DisposalKind), alle über denselben FiFo-Verbrauch:
- SELL: Verkauf gegen EUR — Gewinn = (Netto-Erlös − Einstand) je Lot.
- FEE:  in BTC entrichtete Gebühr (Miner-Fee, Auszahlungsgebühr, Bisq-Handelsgebühr)
        — Tausch gegen Dienstleistung = Veräußerung des Gebührenanteils zum
        Tagesschlusskurs (BMF 06.03.2025 Rn. 33, 54, 60, 91). Auch beim Übertrag
        zwischen eigenen Wallets: der Bestand bleibt, die Gebühr geht.
- GIFT: unentgeltliche Übertragung (Schenkung/Spende) — kein Veräußerungsgeschäft
        (Rn. 54: Veräußerung = ENTGELTLICHE Übertragung), aber die Lots verlassen
        den Pool, sonst führt die Bestandsliste Phantom-Bestand.
"""
from __future__ import annotations
from collections import deque
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .models import Transaction, TxType, Lot, DisposalMatch, SellResult, DisposalKind, de_date
from .parsers import make_warning
from . import btc_prices

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
        self.sell_results: list[SellResult] = []   # Verkäufe (kind=SELL)
        # In BTC entrichtete Gebühren = Veräußerung des Gebührenanteils (H8).
        # Bewusst getrennt von sell_results: die Verkaufs-Abschnitte der Reports
        # bleiben Verkäufe; Gebühren bekommen eigene Abschnitte, ihre Gewinne
        # fließen aber in die Jahressummen und die Freigrenze ein.
        self.fee_results: list[SellResult] = []
        # Unentgeltliche Übertragungen (Schenkung/Spende): Bestandsabgang ohne
        # Veräußerungsgeschäft — Gewinn je Match ist 0.
        self.gift_results: list[SellResult] = []
        self.warnings: list = []  # ParserWarning, nicht str (H4)

    # Bei identischem Zeitstempel zuerst Käufe, dann Verkäufe. manual_buys /
    # manual_sales stempeln beide exakt 12:00 UTC — ohne diesen Tiebreak liefe
    # ein gleichtägiger Verkauf vor seinem Kauf und fände kein Lot.
    _TYPE_ORDER = {
        TxType.BUY: 0,
        TxType.TRANSFER_IN: 1,
        TxType.TRANSFER_OUT: 2,
        TxType.GIFT_OUT: 2,
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
            elif tx.type == TxType.GIFT_OUT:
                self._process_gift(tx)
            # TRANSFER_IN / TRANSFER_OUT: der übertragene Bestand bleibt im Pool
            # (eigene Wallet ↔ eigene Wallet ist keine Veräußerung, BMF Rn. 20/54).

            # Die in BTC entrichtete Gebühr verlässt den Bestand IMMER — auch beim
            # Übertrag zwischen eigenen Wallets. Nach dem Kauf-Lot gebucht, damit
            # eine Bisq-Handelsgebühr notfalls aus dem gerade erworbenen Lot
            # bedient wird statt eine leere Pool-Warnung auszulösen.
            if tx.fee_btc > 0:
                self._process_fee(tx)

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
        # Netto-Verkaufspreis pro BTC (Erlös minus Verkaufsgebühren)
        net_proceeds = tx.eur_amount - tx.fee_eur
        net_sell_price_per_btc = _round(net_proceeds / tx.btc_amount) if tx.btc_amount else Decimal("0")
        self.sell_results.append(
            self._consume(tx, tx.btc_amount, DisposalKind.SELL, net_sell_price_per_btc)
        )

    def _process_fee(self, tx: Transaction) -> None:
        """Gebühr in BTC: Tausch gegen Dienstleistung = Veräußerung des Gebührenanteils
        zum Tagesschlusskurs des deutschen Kalendertags (BMF 06.03.2025 Rn. 33/54/60/91).
        Ohne Kurs (Tabelle endet vorher) wird der Bestandsabgang trotzdem gebucht,
        Erlös und Gewinn bleiben aber unermittelt — sichtbar, nicht stillschweigend."""
        price = btc_prices.price_for_date(de_date(tx.date))
        if price is None:
            rng = btc_prices.table_range()
            ende = f"endet am {rng[1]}" if rng else "fehlt"
            self.warnings.append(make_warning(
                f"Gebühr von {tx.fee_btc:.8f} BTC am {de_date(tx.date)} ohne Tageskurs "
                f"(Kurstabelle {ende}) — Bestandsabgang gebucht, Veräußerungsgewinn daraus "
                f"NICHT ermittelt. Bitte Kurstabelle aktualisieren (tools/update_btc_prices.py).",
                internal=tx.no_kyc,
                year=de_date(tx.date).year,
            ))
        result = self._consume(tx, tx.fee_btc, DisposalKind.FEE, price)
        result.fee_price_per_btc = price
        self.fee_results.append(result)

    def _process_gift(self, tx: Transaction) -> None:
        """Unentgeltliche Übertragung: Lots verlassen den Pool, Gewinn = 0 (keine
        entgeltliche Übertragung → keine Veräußerung i.S.d. § 23 EStG)."""
        self.gift_results.append(self._consume(tx, tx.btc_amount, DisposalKind.GIFT, None))

    _KIND_LABEL = {
        DisposalKind.SELL: "Verkauf",
        DisposalKind.FEE: "Gebühren-Abgang",
        DisposalKind.GIFT: "Unentgeltliche Übertragung",
    }

    def _consume(self, tx: Transaction, quantity: Decimal, kind: DisposalKind,
                 price_per_btc: Decimal | None) -> SellResult:
        """Verbraucht `quantity` BTC FiFo aus dem passenden Pool.

        price_per_btc: Netto-Erlös je BTC (SELL), Tageskurs (FEE) oder None
        (GIFT, oder FEE ohne Kurs) — bei None ist der Gewinn je Match 0, denn
        entweder gibt es keinen Erlös (Schenkung) oder er ist nicht ermittelbar
        (dann trägt SellResult.is_priced == False die Information weiter).
        """
        # Pool nach Vorgang wählen — KYC-Vorgänge sehen noKYC-Lots NIE
        pool = self.nokyc_lots if tx.no_kyc else self.lots

        remaining = quantity
        matches: list[DisposalMatch] = []

        while remaining > Decimal("0"):
            if not pool:
                # pool_label NICHT in die Meldung: bei noKYC-Verkäufen ginge das
                # Wort "noKYC" sonst in steuerreport/steuernachweis ans Finanzamt.
                # Stattdessen internal=True → nur interner Report + GUI-Log.
                if kind == DisposalKind.SELL:
                    hint = "Prüfe ob alle Käufe in den CSV-Dateien vorhanden sind."
                else:
                    # Typischer Grund bei Gebühr/Schenkung: die Wallet hält Bestand,
                    # dessen Kauf hier nicht erfasst ist — oder sie liegt im
                    # falschen Pool (eine Wallet unter bitbox/nokyc/, deren Coins
                    # aus KYC-Käufen stammen, findet dort keine Lots).
                    hint = ("Stammt der Bestand dieser Wallet aus einem hier nicht erfassten "
                            "Kauf, oder ist die Wallet dem falschen Bestand (KYC/noKYC) zugeordnet?")
                self.warnings.append(make_warning(
                    f"WARNUNG: {self._KIND_LABEL[kind]} am {de_date(tx.date)} über {quantity:.8f} BTC "
                    f"kann nicht vollständig FiFo-Lots zugeordnet werden. "
                    f"Fehlende Menge: {remaining:.8f} BTC. {hint}",
                    internal=tx.no_kyc,
                    year=de_date(tx.date).year,
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
            if price_per_btc is None:
                gain = Decimal("0")
            else:
                gain = _round((price_per_btc - lot.cost_per_btc) * used)

            matches.append(DisposalMatch(
                lot_purchase_date=lot.purchase_date,
                lot_source=lot.source,
                btc_used=used,
                cost_per_btc=lot.cost_per_btc,
                net_sell_price_per_btc=price_per_btc if price_per_btc is not None else Decimal("0"),
                gain_eur=gain,
                holding_days=holding_days,
                is_tax_free=tax_free,
            ))

            remaining -= used

        # remaining NICHT verwerfen: > 0 heißt, dass ein Teil der veräußerten
        # Menge ohne Anschaffungsgeschäft dasteht. Die Reports müssen das sehen,
        # sonst bescheinigen sie Steuerfreiheit für eine nie berechnete Haltedauer.
        return SellResult(
            sell_tx=tx,
            matches=matches,
            unmatched_btc=max(remaining, Decimal("0")),
            kind=kind,
        )

    def remaining_lots(self) -> list[Lot]:
        """Alle verbleibenden Lots (KYC + noKYC) — Filterung übernimmt der Report."""
        return list(self.lots) + list(self.nokyc_lots)

    def total_btc_held(self) -> Decimal:
        return sum((lot.btc_amount for lot in self.remaining_lots()), Decimal("0"))
