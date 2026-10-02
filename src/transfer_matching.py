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

Stufen: (1) gleiche TX-ID, (2) Betrag passt im Zeitfenster. Grundsatz: lieber
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

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from enum import Enum

from .models import Transaction, TxType, ANY_WALLET, de_date, wallet_label
from .parsers import ParserWarning, make_warning_fmt

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
        if not (-WINDOW <= delta <= DELIVERY_AFTER) or taker.wallet == giver.wallet:
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


def match_transfers(transactions: list[Transaction]) -> MatchResult:
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

    def link(kind, g, t, method):
        result.links.append(TransferLink(kind, g, t, t.btc_amount, method))
        moved[id(g)] = moved.get(id(g), Decimal("0")) + t.btc_amount
        taken.add(id(t))

    # ── Stufe 1: gleiche TX-ID (On-Chain zwischen zwei BitBox-Wallets, Strike-Hash) ──
    by_txid: dict[str, tuple[list, list]] = {}
    for g in givers:
        if g.type == TxType.TRANSFER_OUT and g.tx_id:
            by_txid.setdefault(g.tx_id, ([], []))[0].append(g)
    for t in takers:
        if t.type == TxType.TRANSFER_IN and t.tx_id in by_txid:
            by_txid[t.tx_id][1].append(t)
    for outs, ins in by_txid.values():
        if len(outs) != 1 or not ins:
            continue
        g = outs[0]
        ins = [t for t in ins if t.wallet != g.wallet and t.no_kyc == g.no_kyc]
        # Eine Transaktion kann mehrere eigene Wallets bedienen — dann muss die
        # Summe der Eingänge in den Abgang passen, sonst lieber Stufe 2.
        if ins and sum((t.btc_amount for t in ins), Decimal("0")) <= g.btc_amount:
            for t in ins:
                link(LinkKind.TRANSFER, g, t, "tx-id")

    # ── Stufe 2: Betrag im Zeitfenster ──
    open_givers = [g for g in givers if id(g) not in moved]
    open_takers = [t for t in takers if id(t) not in taken]
    edges: dict[int, list[Transaction]] = {id(g): [] for g in open_givers}
    back: dict[int, list[Transaction]] = {id(t): [] for t in open_takers}
    kinds: dict[tuple[int, int], LinkKind] = {}
    for g in open_givers:
        for t in open_takers:
            kind = _structurally_possible(g, t)
            if kind and g.no_kyc == t.no_kyc and _amount_fits(g, t.btc_amount):
                edges[id(g)].append(t)
                back[id(t)].append(g)
                kinds[(id(g), id(t))] = kind

    # 2a: gegenseitig eindeutige Paare, solange sich etwas löst
    changed = True
    while changed:
        changed = False
        for g in open_givers:
            if id(g) in moved:
                continue
            cands = [t for t in edges[id(g)] if id(t) not in taken]
            if len(cands) != 1:
                continue
            t = cands[0]
            if len([x for x in back[id(t)] if id(x) not in moved]) == 1:
                link(kinds[(id(g), id(t))], g, t, "betrag")
                changed = True

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
        comp_kinds = {kinds[(id(g), id(t))] for g in comp_g for t in edges[id(g)] if t in comp_t}
        if (len(comp_kinds) == 1 and len({g.wallet for g in comp_g}) == 1
                and len({t.wallet for t in comp_t}) == 1):
            # Alle zwischen denselben beiden Wallets: steuerlich gleichwertig,
            # chronologisch paaren (jeder Abgang nimmt den frühesten Kandidaten).
            for g in sorted(comp_g, key=_sort_key):
                cands = sorted((t for t in edges[id(g)] if id(t) not in taken), key=_sort_key)
                if cands:
                    link(kinds[(id(g), id(cands[0]))], g, cands[0], "betrag")
            continue
        for g in comp_g:
            ambiguous.add(id(g))
        first = min(x.date for x in comp_g + comp_t)
        last = max(x.date for x in comp_g + comp_t)
        result.warnings.append(make_warning_fmt(
            "Überträge zwischen {von} und {bis} nicht eindeutig zuordenbar: {n} Abgänge/Lieferungen "
            "und {m} Eingänge/Direktverkäufe mit passenden Beträgen in verschiedenen Wallets. "
            "Nicht verbunden — die Lots bleiben in der abgebenden Wallet. Bitte die Zuordnung "
            "in transfer_zuordnung.csv festlegen.",
            internal=comp_g[0].no_kyc, year=de_date(first).year,
            von=de_date(first), bis=de_date(last), n=len(comp_g), m=len(comp_t),
        ))

    # ── Offene Vorgänge einsammeln und melden ──
    rest_takers = [t for t in takers if id(t) not in taken]
    for g in givers:
        if g.type == TxType.BUY:
            if id(g) not in moved:
                result.unmatched_buys.append(g)
            continue
        residual = giver_residual(g, moved.get(id(g), Decimal("0")))
        if residual <= 0:
            continue
        result.unmatched_out.append(g)
        cross = [t for t in rest_takers
                 if t.no_kyc != g.no_kyc and _structurally_possible(g, t)
                 and _amount_fits(g, t.btc_amount)]
        if cross:
            # Nur intern: schon das Wort noKYC verriete dem Finanzamt den Bestand.
            result.warnings.append(make_warning_fmt(
                "Abgang am {tag} über {menge} BTC aus {quelle} passt zu einem Eingang in {ziel}, "
                "aber zwischen KYC- und noKYC-Bestand — nicht verbunden (die Bestände bleiben "
                "strikt getrennt). Bitte prüfen, ob die Wallet im richtigen Ordner liegt.",
                internal=True, year=de_date(g.date).year, tag=de_date(g.date),
                menge=f"{g.btc_amount:.8f}", quelle=wallet_label(g.wallet),
                ziel=wallet_label(cross[0].wallet),
            ))
        if id(g) in ambiguous:
            continue
        near = [t for t in rest_takers
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
