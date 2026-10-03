"""Übertrags-Zuordnung für die walletbezogene FiFo-Rechnung (BMF 06.03.2025 Rn. 62).

Walletbezogen heißt: jede Wallet (Broker-Konto, BitBox-Account) ist ein eigener
FiFo-Topf, und bei einem Übertrag zwischen eigenen Wallets wandern die Lots mit.
Dazu muss jeder Abgang seinem Eingang zugeordnet werden. Die Exporte liefern
dafür selten eine gemeinsame TX-ID — Broker vergeben eigene IDs —, also wird
meist über Betrag und Zeit zugeordnet.

Drei Arten von Verbindung (LinkKind), immer „abgebend → aufnehmend“:
- TRANSFER:  TRANSFER_OUT → TRANSFER_IN (Übertrag zwischen eigenen Wallets)
- LIEFERUNG: direkter Kauf → TRANSFER_IN (Pocket, Bisq, manual_buys liefern an
             eine eigene Wallet; der Export des Anbieters hat keine Auszahlung)
- VERKAUF:   TRANSFER_OUT → direkter Verkauf (Pocket, manual_sales: der Abgang
             aus der Wallet IST die Lieferung an den Käufer — ohne diese
             Verbindung verbrauchte die Engine die Lots zweimal)

Stufen: (0) transfer_zuordnung.csv des Nutzers, (1) gleiche TX-ID, (2) Betrag
passt im Zeitfenster. Grundsatz: lieber
keine Verbindung und eine laute Warnung als eine geratene — eine falsche
Zuordnung verschiebt Anschaffungsdaten in ein Dokument fürs Finanzamt.

Mehrere passende Kandidaten sind nur dann unschädlich, wenn alle zwischen
denselben beiden Wallets liegen (z.B. gleich hohe Sparplan-Auszahlungen): dann
ist steuerlich egal, welcher Abgang zu welchem Eingang gehört, und es wird
chronologisch gepaart. Liegen die Kandidaten in verschiedenen Wallets, bleibt
der Fall offen und wird gemeldet.

KYC und noKYC werden nie verbunden (Invariante: ein noKYC-Lot erscheint nie in
einem Finanzamt-Dokument). Ein solches Paar wird erkannt und nur intern gemeldet.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from enum import Enum

from .models import Transaction, TxType, ANY_WALLET, de_date, wallet_label, wallet_name
from .parsers import ParserWarning, PrivateError, make_warning_fmt
from .parsers.transfer_zuordnung import FILENAME as ZUORDNUNG, resolve_wallet

# Zeitfenster Abgang ↔ Eingang, in BEIDE Richtungen: die Quellen stempeln in
# verschiedenen Zeitzonen (Swissquote/Bisq lokal, manual_* 12:00 UTC ohne
# Uhrzeit), der Eingang kann im Export also vor dem Abgang liegen.
WINDOW = timedelta(hours=48)
# Lieferung eines direkten Kaufs: der Eingang kann einige Tage später kommen
# (Bisq: Auszahlung aus der Bisq-Wallet erst nach Abschluss des Trades).
DELIVERY_AFTER = timedelta(days=30)
# Bis zu dieser relativen Abweichung wird ein Betrag als Vorschlag genannt —
# nie automatisch verbunden.
NEAR_MISS = Decimal("0.01")


class LinkKind(Enum):
    TRANSFER = "transfer"
    LIEFERUNG = "lieferung"
    VERKAUF = "verkauf"


@dataclass
class TransferLink:
    kind: LinkKind
    giver: Transaction       # TRANSFER_OUT oder direkter BUY
    taker: Transaction       # TRANSFER_IN oder direkter SELL
    btc_amount: Decimal      # Menge, die von giver.wallet nach taker.wallet wandert
    method: str              # "tx-id" | "betrag" | "manuell"


@dataclass
class MatchResult:
    links: list[TransferLink] = field(default_factory=list)
    warnings: list[ParserWarning] = field(default_factory=list)
    # Vorgänge ohne (vollständiges) Gegenstück — für Engine-Hinweise und den
    # internen Report. Abgänge stehen hier auch, wenn nur ein Rest offen ist.
    unmatched_out: list[Transaction] = field(default_factory=list)
    unmatched_in: list[Transaction] = field(default_factory=list)
    unmatched_buys: list[Transaction] = field(default_factory=list)
    unmatched_sells: list[Transaction] = field(default_factory=list)

    def links_of(self, tx: Transaction) -> list[TransferLink]:
        return [l for l in self.links if l.giver is tx or l.taker is tx]


def giver_residual(giver: Transaction, moved: Decimal) -> Decimal:
    """Menge eines Abgangs, die durch keine Verbindung gedeckt ist.

    Manche Exporte zählen die Gebühr in den Abgangsbetrag hinein (Abgang −
    Gebühr = Eingang), andere nicht (BitBox: Abgang = Eingang, Gebühr extra).
    Die Gebühr verbucht die Engine ohnehin selbst (fee_btc) — ein Rest in genau
    dieser Höhe ist also kein offener Bestand.
    """
    rest = giver.btc_amount - moved
    if giver.fee_btc > 0 and rest == giver.fee_btc:
        return Decimal("0")
    return max(rest, Decimal("0"))


def _amount_fits(giver: Transaction, amount: Decimal) -> bool:
    return amount == giver.btc_amount or (
        giver.fee_btc > 0 and amount == giver.btc_amount - giver.fee_btc
    )


def _kind(giver: Transaction, taker: Transaction) -> LinkKind | None:
    if giver.type == TxType.TRANSFER_OUT and taker.type == TxType.TRANSFER_IN:
        return LinkKind.TRANSFER
    if giver.type == TxType.BUY and taker.type == TxType.TRANSFER_IN:
        return LinkKind.LIEFERUNG
    if giver.type == TxType.TRANSFER_OUT and taker.type == TxType.SELL:
        return LinkKind.VERKAUF
    return None


def _structurally_possible(giver: Transaction, taker: Transaction) -> LinkKind | None:
    """Art, Zeitfenster und Wallets passen — Betrag und Klasse noch ungeprüft."""
    kind = _kind(giver, taker)
    if kind is None:
        return None
    delta = taker.date - giver.date
    if kind == LinkKind.LIEFERUNG:
        if not (-WINDOW <= delta <= DELIVERY_AFTER):
            return None
        # Kauf mit ausdrücklicher Wallet (manual_buys, Spalte wallet): nur der
        # Eingang IN dieser Wallet ist seine Lieferung; sonst eine andere Wallet.
        explicit = giver.wallet != giver.source
        if (taker.wallet == giver.wallet) != explicit:
            return None
    elif kind == LinkKind.TRANSFER:
        if abs(delta) > WINDOW or taker.wallet == giver.wallet:
            return None
    else:  # VERKAUF: ausdrücklich gesetzte Wallet des Verkaufs hat Vorrang
        if abs(delta) > WINDOW or taker.wallet not in (ANY_WALLET, taker.source, giver.wallet):
            return None
    return kind


def _sort_key(tx: Transaction):
    return (tx.date, tx.type.value, tx.source, tx.tx_id)


def transferable(giver: Transaction) -> Decimal:
    """Menge, die ein abgebender Vorgang weitergeben kann: beim Direktkauf
    abzüglich der in BTC entrichteten Handelsgebühr (die verbucht die Engine
    aus demselben Lot), beim Abgang der übertragene Betrag."""
    return giver.btc_amount - giver.fee_btc if giver.type == TxType.BUY else giver.btc_amount


def _find(pool: list[Transaction], day, wallet: str, amount: Decimal, line: int, side: str):
    # Ein manueller Verkauf ohne Spalte wallet (ANY_WALLET) heißt hier „manual“
    hits = [t for t in pool if de_date(t.date) == day
            and (t.wallet == wallet or (t.wallet == ANY_WALLET and t.source == wallet))
            and amount in (t.btc_amount, t.btc_amount + t.fee_btc)]
    if len(hits) != 1:
        raise PrivateError(
            f"{ZUORDNUNG} Zeile {line}: {side} am {day} über {amount:.8f} BTC in "
            f"'{wallet_name(wallet)}' "
            + ("nicht gefunden." if not hits else f"nicht eindeutig ({len(hits)} Treffer).")
            + " Datum (deutsches Kalenderdatum), Wallet und Menge wie in der Warnung angeben."
        )
    return hits[0]


def match_transfers(transactions: list[Transaction], manual_rows=()) -> MatchResult:
    result = MatchResult()
    givers = sorted(
        (t for t in transactions
         if (t.type == TxType.TRANSFER_OUT and t.btc_amount > 0)
         or (t.type == TxType.BUY and t.direct)),
        key=_sort_key,
    )
    takers = sorted(
        (t for t in transactions
         if t.type == TxType.TRANSFER_IN or (t.type == TxType.SELL and t.direct)),
        key=_sort_key,
    )
    moved: dict[int, Decimal] = {}      # id(giver) → verbundene Menge
    taken: set[int] = set()             # id(taker) → schon verbunden
    ambiguous: set[int] = set()         # id(giver) in einem offenen Mehrdeutigkeits-Fall

    def link(kind, g, t, method, amount=None):
        amount = t.btc_amount if amount is None else amount
        result.links.append(TransferLink(kind, g, t, amount, method))
        moved[id(g)] = moved.get(id(g), Decimal("0")) + amount
        taken.add(id(t))

    # ── Stufe 0: transfer_zuordnung.csv (Absicht des Nutzers, Rn. 90) ──
    if manual_rows:
        known = {t.wallet for t in transactions} | {t.source for t in transactions}
        filled: dict[int, Decimal] = {}     # id(taker) → bereits zugeordnet
        manual_takers: list[Transaction] = []
        resolved = []
        for row in manual_rows:
            wallets = []
            for raw in (row.giver_wallet, row.taker_wallet):
                w = resolve_wallet(raw, known)
                if w is None:
                    raise PrivateError(f"{ZUORDNUNG} Zeile {row.line}: Wallet '{raw}' gehört zu keiner "
                                     f"eingelesenen Datei.")
                wallets.append(w)
            g = _find(givers, row.giver_date, wallets[0], row.giver_amount, row.line, "Abgang/Kauf")
            t = _find(takers, row.taker_date, wallets[1], row.taker_amount, row.line, "Eingang/Verkauf")
            resolved.append((row, g, t))
        # Mehrere Abgänge in einen Eingang: enthalten die Abgangsbeträge die
        # Gebühr (Summe minus Gebühren = Eingang), zählt je Abgang der Betrag
        # ohne Gebühr — die Gebühr verbucht die Engine separat (Audit F7).
        net_takers = set()
        for t in {id(t): t for _, _, t in resolved}.values():
            gs = [g for _, g, t2 in resolved if t2 is t]
            if (sum((transferable(g) for g in gs), Decimal("0")) != t.btc_amount
                    and sum((transferable(g) - g.fee_btc for g in gs), Decimal("0")) == t.btc_amount):
                net_takers.add(id(t))
        for row, g, t in resolved:
            kind = _kind(g, t)
            if kind is None:
                raise PrivateError(f"{ZUORDNUNG} Zeile {row.line}: ein Kauf kann nicht direkt mit einem "
                                 f"Verkauf verbunden werden.")
            if g.no_kyc != t.no_kyc:
                # Wortlaut ohne „noKYC“: Fehlermeldung, kein Dokument — trotzdem neutral
                raise PrivateError(f"{ZUORDNUNG} Zeile {row.line}: Abgang und Eingang gehören zu "
                                 f"getrennten Beständen (KYC/noKYC) — nicht verbindbar.")
            avail = transferable(g) - (g.fee_btc if id(t) in net_takers else Decimal("0"))
            amount = min(avail - moved.get(id(g), Decimal("0")),
                         t.btc_amount - filled.get(id(t), Decimal("0")))
            if amount <= 0:
                raise PrivateError(f"{ZUORDNUNG} Zeile {row.line}: Abgang oder Eingang ist durch "
                                 f"vorherige Zeilen schon vollständig zugeordnet.")
            link(kind, g, t, "manuell", amount)
            filled[id(t)] = filled.get(id(t), Decimal("0")) + amount
            if t not in manual_takers:
                manual_takers.append(t)
        for t in manual_takers:
            if filled[id(t)] < t.btc_amount:
                result.warnings.append(make_warning_fmt(
                    "Manuelle Zuordnung: Eingang am {tag} über {menge} BTC in {ziel} nur zu {gedeckt} BTC "
                    "durch die angegebenen Abgänge gedeckt — der Rest kommt ohne Anschaffungsdaten an.",
                    internal=t.no_kyc, year=de_date(t.date).year, tag=de_date(t.date),
                    menge=f"{t.btc_amount:.8f}", ziel=wallet_label(t.wallet),
                    gedeckt=f"{filled[id(t)]:.8f}",
                ))

    # ── Stufe 1: gleiche TX-ID (On-Chain zwischen zwei BitBox-Wallets, Strike-Hash) ──
    by_txid: dict[str, tuple[list, list]] = {}
    for g in givers:
        if g.type == TxType.TRANSFER_OUT and g.tx_id:
            by_txid.setdefault(g.tx_id, ([], []))[0].append(g)
    for t in takers:
        if t.type == TxType.TRANSFER_IN and t.tx_id in by_txid:
            by_txid[t.tx_id][1].append(t)
    for outs, ins in by_txid.values():
        if len(outs) != 1 or not ins or id(outs[0]) in moved:
            continue
        g = outs[0]
        ins = [t for t in ins if t.wallet != g.wallet and t.no_kyc == g.no_kyc and id(t) not in taken]
        # Eine Transaktion kann mehrere eigene Wallets bedienen — dann muss die
        # Summe der Eingänge in den Abgang passen, sonst lieber Stufe 2.
        if ins and sum((t.btc_amount for t in ins), Decimal("0")) <= g.btc_amount:
            for t in ins:
                link(LinkKind.TRANSFER, g, t, "tx-id")

    # Kandidatensuche nur im Zeitfenster (bisect statt jeder gegen jeden: ein
    # mehrjähriger Sparplan hat tausende gleich hohe Auszahlungen)
    taker_dates = [t.date for t in takers]     # takers ist nach Datum sortiert

    def window(g):
        """Noch offene Eingänge/Direktverkäufe im weitesten Zeitfenster um g."""
        lo = bisect_left(taker_dates, g.date - WINDOW)
        # Lieferfrist nur für Direktkäufe; Überträge und Verkäufe liegen in ±WINDOW (Laufzeit,
        # Audit v1.4: das 30-Tage-Fenster für jeden Abgang machte große Exporte quadratisch langsam)
        hi = bisect_right(taker_dates, g.date + (DELIVERY_AFTER if g.type == TxType.BUY else WINDOW))
        return [t for t in takers[lo:hi] if id(t) not in taken]

    # ── Stufe 1b: Käufe mit ausdrücklicher Wallet (manual_buys, Spalte wallet) ──
    # Der Nutzer hat erklärt, wohin geliefert wurde. Ein Eingang in dieser Wallet
    # ist die Lieferung — exakt, sonst ein einziger fast passender Betrag. Ohne
    # diese Stufe würde ein abweichender Eingang als „ohne Abgang“ zusätzlich
    # Bestand aus „extern“ holen (doppelter Bestand, Audit F3).
    for g in givers:
        if g.type != TxType.BUY or g.wallet == g.source or id(g) in moved:
            continue
        cands = [t for t in window(g)
                 if t.no_kyc == g.no_kyc
                 and _structurally_possible(g, t) == LinkKind.LIEFERUNG]
        exact = [t for t in cands if t.btc_amount in (g.btc_amount, transferable(g))]
        near = [t for t in cands if t.btc_amount > 0
                and abs(t.btc_amount - g.btc_amount) / g.btc_amount <= NEAR_MISS]
        pick = exact if exact else near
        if len(pick) == 1:
            t = pick[0]
            link(LinkKind.LIEFERUNG, g, t, "betrag")
            if not exact:
                result.warnings.append(make_warning_fmt(
                    "Kauf vom {tag} über {menge} BTC (manual_buys.csv, Wallet {ziel}): der Eingang am "
                    "{tag2} über {menge2} BTC weicht im Betrag ab und wurde als seine Lieferung "
                    "zugeordnet. Bitte btc_amount prüfen — maßgeblich ist die angekommene Menge.",
                    internal=g.no_kyc, year=de_date(g.date).year, tag=de_date(g.date),
                    menge=f"{g.btc_amount:.8f}", ziel=wallet_label(g.wallet),
                    tag2=de_date(t.date), menge2=f"{t.btc_amount:.8f}",
                ))

    # ── Stufe 2: Betrag im Zeitfenster ──
    open_givers = [g for g in givers if id(g) not in moved]
    open_takers = [t for t in takers if id(t) not in taken]
    edges: dict[int, list[Transaction]] = {id(g): [] for g in open_givers}
    back: dict[int, list[Transaction]] = {id(t): [] for t in open_takers}
    kinds: dict[tuple[int, int], LinkKind] = {}
    for g in open_givers:
        for t in window(g):
            kind = _structurally_possible(g, t)
            if kind and g.no_kyc == t.no_kyc and _amount_fits(g, t.btc_amount):
                edges[id(g)].append(t)
                back[id(t)].append(g)
                kinds[(id(g), id(t))] = kind

    # 2a: gegenseitig eindeutige Paare, solange sich etwas löst
    pending = list(open_givers)
    while pending:
        nxt = []
        for g in pending:
            if id(g) in moved:
                continue
            cands = [t for t in edges[id(g)] if id(t) not in taken]
            if len(cands) == 1 and len([x for x in back[id(cands[0])] if id(x) not in moved]) == 1:
                t = cands[0]
                link(kinds[(id(g), id(t))], g, t, "betrag")
                # Nachbarn des verbundenen Eingangs können jetzt eindeutig sein
                nxt += [x for t2 in edges[id(g)] for x in back[id(t2)] if id(x) not in moved]
        pending = nxt

    # 2b: verbleibende Konflikt-Gruppen (Zusammenhangskomponenten)
    seen: set[int] = set()
    by_id = {id(x): x for x in open_givers + open_takers}
    for g0 in open_givers:
        if id(g0) in moved or id(g0) in seen or not edges[id(g0)]:
            continue
        comp_g, comp_t, stack = [], [], [g0]
        seen.add(id(g0))
        while stack:
            node = stack.pop()
            is_giver = id(node) in edges
            (comp_g if is_giver else comp_t).append(node)
            for nb in (edges[id(node)] if is_giver else back[id(node)]):
                if id(nb) in moved or id(nb) in taken or id(nb) in seen:
                    continue
                seen.add(id(nb))
                stack.append(by_id[id(nb)])
        comp_t_ids = {id(t) for t in comp_t}
        comp_kinds = {kinds[(id(g), id(t))] for g in comp_g for t in edges[id(g)] if id(t) in comp_t_ids}
        same_pair = (len(comp_kinds) == 1 and len({g.wallet for g in comp_g}) == 1
                     and len({t.wallet for t in comp_t}) == 1)
        if same_pair and comp_kinds != {LinkKind.LIEFERUNG}:
            # Alle zwischen denselben beiden Wallets: welche Einheiten wandern,
            # entscheidet FiFo der Quelle — steuerlich gleichwertig. Chronologisch
            # paaren, exakte Beträge vor gebührenbereinigten (Audit F9).
            for g in sorted(comp_g, key=_sort_key):
                cands = sorted((t for t in edges[id(g)] if id(t) not in taken),
                               key=lambda t: (t.btc_amount != g.btc_amount, _sort_key(t)))
                if cands:
                    link(kinds[(id(g), id(cands[0]))], g, cands[0], "betrag")
            continue
        if same_pair:
            # Lieferungen: es wandert das Lot des gelieferten KAUFS — welcher
            # Kauf es war, bestimmt die Anschaffung (Audit F6). Je Eingang der
            # zeitlich nächste Kauf; gleich nahe Käufe → mehrdeutig.
            plan, clash = [], False
            used: set[int] = set()
            for t in sorted(comp_t, key=_sort_key):
                cands = [g for g in back[id(t)] if id(g) not in moved and id(g) not in used]
                if not cands:
                    continue
                dist = sorted(cands, key=lambda g: abs((t.date - g.date).total_seconds()))
                if len(dist) > 1 and abs((t.date - dist[0].date).total_seconds()) == \
                        abs((t.date - dist[1].date).total_seconds()):
                    clash = True
                    break
                plan.append((dist[0], t))
                used.add(id(dist[0]))
            if not clash:
                for g, t in plan:
                    link(LinkKind.LIEFERUNG, g, t, "betrag")
                continue
        for g in comp_g:
            ambiguous.add(id(g))
        first = min(x.date for x in comp_g + comp_t)
        last = max(x.date for x in comp_g + comp_t)
        result.warnings.append(make_warning_fmt(
            "Überträge zwischen {von} und {bis} nicht eindeutig zuordenbar: {n} Abgänge/Lieferungen "
            "und {m} Eingänge/Direktverkäufe mit passenden Beträgen. Nicht verbunden — die Lots "
            "bleiben in der abgebenden Wallet. Bitte die Zuordnung in transfer_zuordnung.csv festlegen.",
            internal=comp_g[0].no_kyc, year=de_date(first).year,
            von=de_date(first), bis=de_date(last), n=len(comp_g), m=len(comp_t),
        ))

    # ── Offene Vorgänge einsammeln und melden ──
    rest_takers = [t for t in takers if id(t) not in taken]

    def fits_any(g, t):
        return t.btc_amount in (g.btc_amount, transferable(g)) or _amount_fits(g, t.btc_amount)

    # Kreuzfälle KYC ↔ noKYC (nie verbunden). Richtung noKYC → KYC würde den
    # noKYC-Vorgang in den Finanzamt-Dokumenten sichtbar machen: der Eingang in
    # der KYC-Wallet stünde dort mit Datum und genauem Betrag als „nicht
    # eingelesen“ (Datenschutz-Audit Fund 1). Deshalb harter Abbruch mit
    # Anleitung — der Bestand lässt sich so nicht vorzeigbar dokumentieren.
    # (1) Gleiche On-Chain-TX-ID ist ein sicherer Kreuzfall — für JEDEN noKYC-Abgang (auch Schenkung,
    # reine Gebühr, schon teilweise verbunden), unabhängig von Betrag und Wallet-Name. Audit v1.4:
    # eine Batch-TX mit einem Output in eine zweite noKYC-Wallet (Stufe 1 verbunden) und einem in
    # die KYC-Wallet umging die Prüfung, ebenso GIFT_OUT und Abgänge mit unbekannter Gebühr.
    kyc_in = {}
    for t in takers:
        if not t.no_kyc and t.type == TxType.TRANSFER_IN and t.tx_id:
            kyc_in.setdefault(t.tx_id.lower(), t)
    nokyc_out = [t for t in transactions if t.no_kyc and t.tx_id
                 and t.type in (TxType.TRANSFER_OUT, TxType.GIFT_OUT)]
    nk_cross = [(g, kyc_in[g.tx_id.lower()]) for g in nokyc_out if g.tx_id.lower() in kyc_in]
    # (2) Ohne gemeinsame TX-ID: Betrag im Zeitfenster — exakt, oder bis NEAR_MISS kleiner, wenn die
    # Gebühr des Abgangs unbekannt ist bzw. ein noKYC-Direktkauf mit Liefergebühr ankommt
    for g in givers:
        if nk_cross:
            break
        if not g.no_kyc or id(g) in moved:
            continue
        loose = g.type == TxType.BUY or g.fee_btc == 0
        hit = [t for t in window(g)
               if not t.no_kyc and _structurally_possible(g, t)
               and (fits_any(g, t) or (loose and 0 < t.btc_amount <= transferable(g)
                                       and (transferable(g) - t.btc_amount) / transferable(g) <= NEAR_MISS))]
        if hit:
            nk_cross.append((g, hit[0]))
    if nk_cross:
        g, t = nk_cross[0]
        raise PrivateError(
            f"Der Vorgang vom {de_date(g.date)} über {g.btc_amount:.8f} BTC aus dem noKYC-Bestand "
            f"ist offenbar am {de_date(t.date)} ({t.btc_amount:.8f} BTC) in einer KYC-Wallet "
            f"angekommen. KYC- und noKYC-Bestände bleiben strikt getrennt; die Steuerdokumente "
            f"würden den Eingang sonst mit Datum und Betrag zeigen. Bitte den Export der "
            f"empfangenden Wallet nach bitbox/nokyc/ bzw. wallets/nokyc/ verschieben (in der App als "
            f"„noKYC“ einstufen) oder die Einstufung des Kaufs prüfen. Berechnung abgebrochen."
        )

    for g in givers:
        if g.type == TxType.BUY:
            if id(g) not in moved:
                result.unmatched_buys.append(g)
            continue
        residual = giver_residual(g, moved.get(id(g), Decimal("0")))
        if residual <= 0:
            continue
        result.unmatched_out.append(g)
        cross = [t for t in window(g)
                 if t.no_kyc != g.no_kyc and _structurally_possible(g, t)
                 and _amount_fits(g, t.btc_amount)]
        if cross:
            # Richtung KYC → noKYC: der KYC-Abgang erscheint in den offiziellen
            # Dokumenten als Übertrag in eine „nicht eingelesene“ Wallet — sachlich
            # richtig (die Coins verlassen den KYC-Bestand). Nur intern melden,
            # aber ausdrücklich sagen, was die Dokumente zeigen (Fund 2).
            result.warnings.append(make_warning_fmt(
                "Abgang am {tag} über {menge} BTC aus {quelle} passt zu einem Eingang in {ziel} — "
                "Übertrag vom KYC- in den noKYC-Bestand. Nicht verbunden (die Bestände bleiben "
                "strikt getrennt). Steuerreport und Steuernachweis zeigen diesen Abgang mit Datum "
                "und Betrag als Übertrag in eine nicht eingelesene eigene Wallet.",
                internal=True, year=de_date(g.date).year, tag=de_date(g.date),
                menge=f"{g.btc_amount:.8f}", quelle=wallet_label(g.wallet),
                ziel=wallet_label(cross[0].wallet),
            ))
        if id(g) in ambiguous:
            continue
        near = [t for t in window(g)
                if t.no_kyc == g.no_kyc and _structurally_possible(g, t)
                and t.btc_amount > 0
                and abs(t.btc_amount - g.btc_amount) / g.btc_amount <= NEAR_MISS]
        values = dict(tag=de_date(g.date), menge=f"{residual:.8f}", quelle=wallet_label(g.wallet))
        template = (
            "Abgang am {tag} über {menge} BTC aus {quelle}: kein passender Eingang in einer "
            "eingelesenen Wallet. Der Bestand wird als Übertrag in eine nicht eingelesene eigene "
            "Wallet behandelt (keine Veräußerung). War es eine Zahlung, ein Verkauf oder eine "
            "Schenkung, bitte erfassen."
        )
        if near:
            t = near[0]
            template += (" Möglicher Eingang: {tag2} über {menge2} BTC in {ziel} (Betrag weicht ab) — "
                         "bei Bedarf in transfer_zuordnung.csv bestätigen.")
            values.update(tag2=de_date(t.date), menge2=f"{t.btc_amount:.8f}", ziel=wallet_label(t.wallet))
        result.warnings.append(make_warning_fmt(
            template, internal=g.no_kyc, year=de_date(g.date).year, **values))

    for t in rest_takers:
        (result.unmatched_in if t.type == TxType.TRANSFER_IN else result.unmatched_sells).append(t)
    return result
