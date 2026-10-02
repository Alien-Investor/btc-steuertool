"""FiFo-Engine: Lot-Verwaltung und Gewinnberechnung nach deutschem Steuerrecht.

Walletbezogene Betrachtung (BMF 06.03.2025 Rn. 62, Standard): jede Wallet —
Broker-Konto oder BitBox-Account — ist ein eigener FiFo-Topf. Bei einem
Übertrag zwischen eigenen Wallets gibt die sendende Wallet ihre ältesten Lots
ab; sie behalten Anschaffungsdatum und Einstandspreis und werden in der
Ziel-Wallet nach dem ANSCHAFFUNGSdatum eingereiht (Rn. 61 „zuerst angeschafft"),
nicht nach dem Zugangsdatum. Welcher Abgang zu welchem Eingang gehört, ermittelt
transfer_matching vorab.

Die Töpfe sind nach (Klasse, Wallet) geschlüsselt, Klasse = KYC oder noKYC.
KYC-Vorgänge sehen noKYC-Lots nie — ein noKYC-Lot kann niemals in der
FiFo-Zuordnung eines offiziellen Finanzamt-Dokuments auftauchen.

mode="global" rechnet wie bis Oktober 2026: ein Topf je Klasse über alle
Wallets, Überträge bewegen nichts. Nur noch als Vergleich im internen Report.

Drei Arten von Bestandsabgang (DisposalKind), alle über denselben FiFo-Verbrauch:
- SELL: Verkauf gegen EUR — Gewinn = (Netto-Erlös − Einstand) je Lot.
- FEE:  in BTC entrichtete Gebühr (Miner-Fee, Auszahlungsgebühr, Bisq-Handelsgebühr)
        — Tausch gegen Dienstleistung = Veräußerung des Gebührenanteils zum
        Tagesschlusskurs (BMF 06.03.2025 Rn. 33, 54, 60, 91). Auch beim Übertrag
        zwischen eigenen Wallets: der Bestand wandert, die Gebühr geht — aus den
        Lots der SENDENDEN Wallet.
- GIFT: unentgeltliche Übertragung (Schenkung/Spende) — kein Veräußerungsgeschäft
        (Rn. 54: Veräußerung = ENTGELTLICHE Übertragung), aber die Lots verlassen
        den Topf, sonst führt die Bestandsliste Phantom-Bestand.
"""
from __future__ import annotations
from bisect import insort
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from .models import (Transaction, TxType, Lot, DisposalMatch, SellResult, DisposalKind,
                     de_date, ANY_WALLET, EXTERN_WALLET, wallet_label)
from .parsers import make_warning, make_warning_fmt
from .transfer_matching import match_transfers, MatchResult, LinkKind, giver_residual
from . import btc_prices

CENT = Decimal("0.01")
ZERO = Decimal("0")


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


def _lot_key(lot: Lot):
    return lot.purchase_date


class FifoEngine:
    def __init__(self, mode: str = "wallet"):
        if mode not in ("wallet", "global"):
            raise ValueError(f"unbekannter FiFo-Modus {mode!r}")
        self.mode = mode
        # (no_kyc, wallet) → Lots, nach Anschaffungsdatum sortiert (älteste vorn)
        self.pots: dict[tuple[bool, str], list[Lot]] = {}
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
        # Ergebnis der Übertrags-Zuordnung (nur mode="wallet")
        self.matching: MatchResult | None = None
        # Ausgeführte Umbuchungen: (Link, Lots wie sie die Ziel-Wallet erreichten)
        self.moves: list[tuple] = []
        # Abgänge ohne Eingang: (Transaktion, Lots, die nach „extern" gingen)
        self.parked: list[tuple] = []
        # Eingänge ohne Abgang: (Transaktion, Lots, die aus „extern" kamen)
        self.pulled: list[tuple] = []
        # Bestand zum 31.12. je Jahr — im selben Lauf festgehalten. Ein zweiter
        # Lauf über die Daten bis zum Stichtag zerrisse Überträge über Silvester
        # (Abgang 31.12., Eingang 01.01.) und sähe ein anderes Matching.
        self._year_end: dict[int, list[Lot]] = {}
        self._first_year: int | None = None
        self._last_year: int | None = None
        # id(Kauf) → sein Lot: eine Lieferung bewegt GENAU das Lot des
        # gelieferten Kaufs, nicht das älteste beim Anbieter
        self._lot_of: dict[int, Lot] = {}
        # Töpfe ohne bekannten Verwahrort — siehe _untracked_wallets()
        self._untracked: set[str] = {EXTERN_WALLET}

    # Bei identischem Zeitstempel zuerst Käufe, dann Verkäufe. manual_buys /
    # manual_sales stempeln beide exakt 12:00 UTC — ohne diesen Tiebreak liefe
    # ein gleichtägiger Verkauf vor seinem Kauf und fände kein Lot. Umbuchungen
    # laufen vor Abgängen desselben Zeitpunkts.
    _TYPE_ORDER = {
        TxType.BUY: 0,
        TxType.TRANSFER_IN: 1,
        TxType.TRANSFER_OUT: 2,
        TxType.GIFT_OUT: 2,
        TxType.SELL: 3,
    }
    _MOVE_ORDER = 1

    # ── Töpfe ──

    def _wallet(self, wallet: str) -> str:
        return ANY_WALLET if self.mode == "global" else wallet

    def _pot(self, no_kyc: bool, wallet: str) -> list[Lot]:
        return self.pots.setdefault((no_kyc, self._wallet(wallet)), [])

    def _untracked_lots(self, no_kyc: bool) -> list[tuple[list[Lot], Lot]]:
        """Lots einer Klasse ohne bekannten Verwahrort, nach Anschaffungsdatum."""
        pairs = [(pot, lot) for (cls, w), pot in self.pots.items()
                 if cls == no_kyc and w in self._untracked for lot in pot]
        return sorted(pairs, key=lambda p: _lot_key(p[1]))

    @staticmethod
    def _untracked_wallets(transactions: list[Transaction]) -> set[str]:
        """Töpfe, deren Bestand an keinem eingelesenen Ort liegt: „extern" (Abgänge
        ohne Eingang) und die Anbieter direkter Käufe ohne eigene Wallet-Angabe
        (Pocket, Bisq, manual — deren Lots dort nur liegen, wenn keine Lieferung
        zugeordnet werden konnte). Eingelesene Wallets und Broker-Konten sind
        vollständig: jeder Abgang daraus steht im Export."""
        return {EXTERN_WALLET} | {t.wallet for t in transactions
                                  if t.direct and t.type == TxType.BUY and t.wallet == t.source}

    # ── Ablauf ──

    def process(self, transactions: list[Transaction], manual_links=()) -> None:
        """Verarbeitet alle Transaktionen chronologisch.

        manual_links: Zeilen aus transfer_zuordnung.csv (nur mode="wallet")."""
        sale_wallet: dict[int, str] = {}   # id(SELL) → Wallet aus VERKAUF-Verbindung
        events: list[tuple] = []
        for tx in transactions:
            events.append((tx.date, self._TYPE_ORDER[tx.type], len(events), "tx", tx))
        if self.mode == "wallet":
            self._untracked = self._untracked_wallets(transactions)
            self.matching = match_transfers(transactions, manual_links)
            self.warnings.extend(self.matching.warnings)
            for link in self.matching.links:
                if link.kind == LinkKind.VERKAUF:
                    sale_wallet[id(link.taker)] = link.giver.wallet
                else:
                    # Verfügbar ab Zugang — und nie vor dem Abgang (Zeitzonen-Versatz)
                    when = max(link.giver.date, link.taker.date)
                    events.append((when, self._MOVE_ORDER, len(events), "move", link))
        events.sort(key=lambda e: (e[0], e[1], e[2]))
        moved = self._moved_per_giver()
        orphans = {id(t) for t in self.matching.unmatched_in} if self.matching else set()

        for when, _, _, what, obj in events:
            self._roll_year(de_date(when).year)
            if what == "move":
                self._move(obj)
                continue
            tx = obj
            if tx.type == TxType.BUY:
                self._add_lot(tx)
            elif tx.type == TxType.SELL:
                self._process_sell(tx, sale_wallet.get(id(tx), tx.wallet))
            elif tx.type == TxType.GIFT_OUT:
                self._process_gift(tx)
            elif tx.type == TxType.TRANSFER_OUT and self.mode == "wallet":
                self._park_unmatched(tx, moved.get(id(tx), ZERO))
            elif tx.type == TxType.TRANSFER_IN and id(tx) in orphans:
                self._pull_orphan(tx)
            # Zugeordneter TRANSFER_IN: Lots kommen über die Umbuchung (move).

            # Die in BTC entrichtete Gebühr verlässt den Bestand IMMER — auch beim
            # Übertrag zwischen eigenen Wallets. Nach dem Kauf-Lot gebucht, damit
            # eine Bisq-Handelsgebühr notfalls aus dem gerade erworbenen Lot
            # bedient wird statt eine leere Pool-Warnung auszulösen.
            if tx.fee_btc > 0:
                self._process_fee(tx)
        if self._last_year is not None:
            self._year_end[self._last_year] = self._snapshot()

    def _moved_per_giver(self) -> dict[int, Decimal]:
        moved: dict[int, Decimal] = {}
        if self.matching:
            for link in self.matching.links:
                moved[id(link.giver)] = moved.get(id(link.giver), ZERO) + link.btc_amount
        return moved

    def _roll_year(self, year: int) -> None:
        if self._first_year is None:
            self._first_year = self._last_year = year
            return
        while self._last_year < year:
            self._year_end[self._last_year] = self._snapshot()
            self._last_year += 1

    def _snapshot(self) -> list[Lot]:
        return [replace(lot) for lot in self.remaining_lots()]

    # ── Zugänge und Umbuchungen ──

    def _add_lot(self, tx: Transaction) -> None:
        # Einstandspreis inkl. Kaufgebühren
        cost_per_btc = _round((tx.eur_amount + tx.fee_eur) / tx.btc_amount) if tx.btc_amount else ZERO
        lot = Lot(
            purchase_date=tx.date,
            btc_amount=tx.btc_amount,
            cost_per_btc=cost_per_btc,
            source=tx.source,
            tx_id=tx.tx_id,
            no_kyc=tx.no_kyc,
            wallet=self._wallet(tx.wallet),
        )
        self._lot_of[id(tx)] = lot
        insort(self._pot(tx.no_kyc, tx.wallet), lot, key=_lot_key)

    def _take(self, pot: list[Lot], quantity: Decimal) -> tuple[list[Lot], Decimal]:
        """Nimmt `quantity` BTC von vorn aus dem Topf; liefert die Teil-Lots und
        die Menge, die der Topf nicht decken konnte."""
        taken: list[Lot] = []
        remaining = quantity
        while remaining > ZERO and pot:
            lot = pot[0]
            if lot.btc_amount <= remaining:
                pot.pop(0)
                taken.append(lot)
                remaining -= lot.btc_amount
            else:
                lot.btc_amount -= remaining
                taken.append(replace(lot, btc_amount=remaining))
                remaining = ZERO
        return taken, remaining

    def _transfer(self, no_kyc: bool, src: str, dst: str, quantity: Decimal,
                  first: Lot | None = None) -> tuple[list[Lot], Decimal]:
        """Bewegt `quantity` BTC FiFo von src nach dst. `first`: dieses Lot
        zuerst (Lieferung eines bestimmten Kaufs), nur der Rest FiFo."""
        pot = self._pot(no_kyc, src)
        taken: list[Lot] = []
        if first is not None and quantity > 0 and any(l is first for l in pot):
            part, quantity = self._take_lot(pot, first, quantity)
            taken.append(part)
        more, missing = self._take(pot, quantity)
        taken += more
        target = self._pot(no_kyc, dst)
        for lot in taken:
            lot.wallet = dst
            insort(target, lot, key=_lot_key)
        return taken, missing

    def _move(self, link) -> None:
        g, t = link.giver, link.taker
        if g.wallet == t.wallet:
            # Kauf mit ausdrücklicher Wallet: das Lot liegt schon dort, der
            # Eingang ist nur seine Lieferung — nichts zu bewegen
            return
        own = self._lot_of.get(id(g)) if link.kind == LinkKind.LIEFERUNG else None
        taken, missing = self._transfer(g.no_kyc, g.wallet, t.wallet, link.btc_amount, first=own)
        self.moves.append((link, [replace(l) for l in taken]))
        if missing > 0:
            what = "Lieferung des Kaufs" if link.kind == LinkKind.LIEFERUNG else "Übertrag"
            self.warnings.append(make_warning_fmt(
                "WARNUNG: {what} vom {tag} über {menge} BTC von {quelle} nach {ziel}: die "
                "abgebende Wallet hält dafür zu wenig Bestand mit Anschaffungsdaten. "
                "Fehlende Menge: {fehlt} BTC — sie kommt ohne Anschaffungsdaten an. "
                "Fehlt ein Kauf oder ein Eingang dieser Wallet?",
                internal=g.no_kyc, year=de_date(max(g.date, t.date)).year, what=what,
                tag=de_date(g.date), menge=f"{link.btc_amount:.8f}",
                quelle=wallet_label(g.wallet), ziel=wallet_label(t.wallet), fehlt=f"{missing:.8f}",
            ))

    def _park_unmatched(self, tx: Transaction, moved: Decimal) -> None:
        """Abgang ohne (vollständigen) Eingang: der Rest geht in die Wallet
        „extern" — nicht verloren, aber auch nicht mehr in der Absender-Wallet.
        Gemeldet hat das schon transfer_matching."""
        residual = giver_residual(tx, moved)
        if residual > 0:
            taken, _ = self._transfer(tx.no_kyc, tx.wallet, EXTERN_WALLET, residual)
            self.parked.append((tx, [replace(l) for l in taken]))

    def _pull_orphan(self, tx: Transaction) -> None:
        """Eingang ohne zugeordneten Abgang: er kommt aus einer nicht eingelesenen
        eigenen Wallet. Was zuvor in nicht eingelesene Wallets abging, liegt in
        „extern" — von dort kommen FiFo die zuerst angeschafften Einheiten.
        Reicht „extern" nicht, bleibt der Rest ohne Anschaffungsdaten (keine
        erfundenen Lots); ein späterer Abgang daraus meldet die Lücke.
        Beispiel aus echten Daten: Broker → nicht exportierte Wallet → zurück
        zum Broker → Verkauf. Ohne diese Regel stünde der Verkauf ohne Kauf da."""
        taken, missing = self._transfer(tx.no_kyc, EXTERN_WALLET, tx.wallet, tx.btc_amount)
        self.pulled.append((tx, [replace(l) for l in taken], missing))

    # ── Abgänge ──

    def _process_sell(self, tx: Transaction, wallet: str) -> None:
        # Netto-Verkaufspreis pro BTC (Erlös minus Verkaufsgebühren)
        net_proceeds = tx.eur_amount - tx.fee_eur
        net_sell_price_per_btc = _round(net_proceeds / tx.btc_amount) if tx.btc_amount else ZERO
        self.sell_results.append(
            self._consume(tx, tx.btc_amount, DisposalKind.SELL, net_sell_price_per_btc, wallet)
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
        result = self._consume(tx, tx.fee_btc, DisposalKind.FEE, price, tx.wallet)
        result.fee_price_per_btc = price
        self.fee_results.append(result)

    def _process_gift(self, tx: Transaction) -> None:
        """Unentgeltliche Übertragung: Lots verlassen den Topf, Gewinn = 0 (keine
        entgeltliche Übertragung → keine Veräußerung i.S.d. § 23 EStG)."""
        self.gift_results.append(self._consume(tx, tx.btc_amount, DisposalKind.GIFT, None, tx.wallet))

    _KIND_LABEL = {
        DisposalKind.SELL: "Verkauf",
        DisposalKind.FEE: "Gebühren-Abgang",
        DisposalKind.GIFT: "Unentgeltliche Übertragung",
    }

    def _consume(self, tx: Transaction, quantity: Decimal, kind: DisposalKind,
                 price_per_btc: Decimal | None, wallet: str) -> SellResult:
        """Verbraucht `quantity` BTC FiFo aus dem Topf der Wallet.

        price_per_btc: Netto-Erlös je BTC (SELL), Tageskurs (FEE) oder None
        (GIFT, oder FEE ohne Kurs) — bei None ist der Gewinn je Match 0, denn
        entweder gibt es keinen Erlös (Schenkung) oder er ist nicht ermittelbar
        (dann trägt SellResult.is_priced == False die Information weiter).

        wallet == ANY_WALLET (Verkauf ohne Wallet-Angabe und ohne passenden
        Abgang): Er kann aus keiner eingelesenen Wallet stammen — deren Exporte
        sind vollständig, ein Abgang stünde darin. Bedient wird er deshalb nur aus
        Beständen ohne bekannten Verwahrort, FiFo über diese Töpfe, mit Warnung.
        """
        cross_wallet = self.mode == "wallet" and wallet == ANY_WALLET
        if cross_wallet:
            taken: list[Lot] = []
            remaining = quantity
            for pot, lot in self._untracked_lots(tx.no_kyc):
                if remaining <= ZERO:
                    break
                part, rest = self._take_lot(pot, lot, remaining)
                taken.append(part)
                remaining = rest
            self.warnings.append(make_warning(
                f"{self._KIND_LABEL[kind]} am {de_date(tx.date)} über {quantity:.8f} BTC ohne "
                f"Wallet-Angabe und ohne passenden Abgang aus einer eingelesenen Wallet: "
                f"nach FiFo aus Beständen ohne bekannten Verwahrort bedient (Abgänge in "
                f"nicht eingelesene Wallets, nicht zugeordnete Lieferungen). Bitte in "
                f"manual_sales.csv die Spalte wallet ergänzen.",
                internal=tx.no_kyc, year=de_date(tx.date).year,
            ))
        else:
            taken, remaining = self._take(self._pot(tx.no_kyc, wallet), quantity)

        matches: list[DisposalMatch] = []
        for lot in taken:
            used = lot.btc_amount
            # Beide Zeitstempel sind timezone-aware — direkte Differenz.
            # (KEIN replace(tzinfo=...): das würde Nicht-UTC-Zeitstempel verfälschen.)
            holding_days = (tx.date - lot.purchase_date).days
            if price_per_btc is None:
                gain = ZERO
            else:
                gain = _round((price_per_btc - lot.cost_per_btc) * used)
            matches.append(DisposalMatch(
                lot_purchase_date=lot.purchase_date,
                lot_source=lot.source,
                btc_used=used,
                cost_per_btc=lot.cost_per_btc,
                net_sell_price_per_btc=price_per_btc if price_per_btc is not None else ZERO,
                gain_eur=gain,
                holding_days=holding_days,
                is_tax_free=_is_tax_free(lot.purchase_date, tx.date),
                lot_wallet=lot.wallet,
            ))

        if remaining > ZERO:
            self._warn_shortfall(tx, quantity, remaining, kind, wallet)

        # remaining NICHT verwerfen: > 0 heißt, dass ein Teil der veräußerten
        # Menge ohne Anschaffungsgeschäft dasteht. Die Reports müssen das sehen,
        # sonst bescheinigen sie Steuerfreiheit für eine nie berechnete Haltedauer.
        return SellResult(
            sell_tx=tx,
            matches=matches,
            unmatched_btc=max(remaining, ZERO),
            kind=kind,
        )

    @staticmethod
    def _take_lot(pot: list[Lot], lot: Lot, quantity: Decimal) -> tuple[Lot, Decimal]:
        if lot.btc_amount <= quantity:
            pot.remove(lot)
            return lot, quantity - lot.btc_amount
        lot.btc_amount -= quantity
        return replace(lot, btc_amount=quantity), ZERO

    def _warn_shortfall(self, tx, quantity, remaining, kind, wallet) -> None:
        # pool_label NICHT in die Meldung: bei noKYC-Verkäufen ginge das
        # Wort "noKYC" sonst in steuerreport/steuernachweis ans Finanzamt.
        # Stattdessen internal=True → nur interner Report + GUI-Log.
        if kind == DisposalKind.SELL:
            hint = "Prüfe ob alle Käufe in den CSV-Dateien vorhanden sind."
        else:
            # Typischer Grund bei Gebühr/Schenkung: die Wallet hält Bestand,
            # dessen Kauf hier nicht erfasst ist — oder sie liegt im
            # falschen Pool (eine Wallet unter bitbox/nokyc/, deren Coins
            # aus KYC-Käufen stammen, findet dort keine Lots). Den Pool-Hinweis
            # NUR bei noKYC-Vorgängen (Warnung ist dann ohnehin intern): bei
            # KYC-Wallets ginge „noKYC" sonst ans Finanzamt (Audit run-1, Fund 3).
            hint = "Stammt der Bestand dieser Wallet aus einem hier nicht erfassten Kauf?"
            if tx.no_kyc:
                hint += " Oder gehört die Wallet in den KYC-Bestand?"
        text = (f"WARNUNG: {self._KIND_LABEL[kind]} am {de_date(tx.date)} über {quantity:.8f} BTC "
                f"kann nicht vollständig FiFo-Lots zugeordnet werden. "
                f"Fehlende Menge: {remaining:.8f} BTC. {hint}")
        if self.mode == "global" or wallet == ANY_WALLET:
            self.warnings.append(make_warning(text, internal=tx.no_kyc, year=de_date(tx.date).year))
            return
        # Walletbezogen: die Wallet nennen und offene Eingänge dieser Wallet
        # als wahrscheinliche Ursache zeigen (Bestand ohne Anschaffungsdaten).
        extra = " Gerechnet wird walletbezogen (Bestand {quelle})."
        values = dict(quelle=wallet_label(wallet))
        orphans = [t for t, _, missing in self.pulled
                   if missing > 0 and t.wallet == wallet and t.no_kyc == tx.no_kyc and t.date <= tx.date]
        if orphans:
            extra += (" Diese Wallet hat {n} Eingang/Eingänge ohne zugeordneten Abgang, die auch "
                      "aus nicht eingelesenen Wallets nicht gedeckt waren (zuletzt {letzt}) — "
                      "Herkunft und Anschaffungsdaten unbekannt.")
            values.update(n=len(orphans), letzt=de_date(orphans[-1].date))
        self.warnings.append(make_warning_fmt(
            text.replace("{", "{{").replace("}", "}}") + extra,
            internal=tx.no_kyc, year=de_date(tx.date).year, **values,
        ))

    # ── Abfragen ──

    def remaining_lots(self) -> list[Lot]:
        """Alle verbleibenden Lots (KYC + noKYC) — Filterung übernimmt der Report."""
        return [lot for pot in self.pots.values() for lot in pot]

    def lots_at_year_end(self, year: int) -> list[Lot]:
        """Bestand zum 31.12. des Jahres, im Hauptlauf festgehalten."""
        if self._first_year is None or year < self._first_year:
            return []
        if year in self._year_end:
            return list(self._year_end[year])
        return self.remaining_lots()

    def total_btc_held(self) -> Decimal:
        return sum((lot.btc_amount for lot in self.remaining_lots()), ZERO)
