"""Wallet-Angaben für die Reports der walletbezogenen FiFo-Rechnung (BMF Rn. 62, 103).

Rn. 103 verlangt, die Methode je Wallet und die Umschichtungen zu dokumentieren.
Wallet-Namen sind aber private Labels aus der Dateiablage (SA-016) und gehen
nicht ans Finanzamt. Offizielle Dokumente nennen BitBox-Wallets deshalb neutral
durchnummeriert („BitBox-Wallet 1“), gezählt werden nur KYC-Wallets — die Zahl
verrät keine noKYC-Wallet. Echte Namen stehen nur in der internen Datei
wallet_abgleich_intern_JJJJ.txt, zusammen mit dem Vergleich zur früheren
gemeinsamen FiFo-Rechnung und allen offenen Zuordnungen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .models import Transaction, TxType, Lot, ANY_WALLET, EXTERN_WALLET, de_date
from .transfer_matching import LinkKind

ZERO = Decimal("0")

_PSEUDO = {
    EXTERN_WALLET: "nicht eingelesen",
    ANY_WALLET: "ohne Wallet-Angabe",
    "manual": "manuell erfasst",
}
_METHOD = {"tx-id": "TX-ID", "betrag": "Betrag/Zeit", "manuell": "manuell", "": "kein Eingang"}
_KIND = {LinkKind.TRANSFER: "Übertrag", LinkKind.LIEFERUNG: "Lieferung", None: "Abgang"}


def official_labels(transactions: list[Transaction]) -> dict[str, str]:
    """Neutrale Bezeichnungen der KYC-BitBox-Wallets, stabil über alle Jahre."""
    names = sorted({t.wallet for t in transactions
                    if t.wallet.startswith("bitbox:") and not t.no_kyc})
    if len(names) == 1:
        return {names[0]: "BitBox-Wallet"}
    return {w: f"BitBox-Wallet {i}" for i, w in enumerate(names, 1)}


def label(wallet: str, labels: dict[str, str] | None) -> str:
    """Bezeichnung fürs offizielle Dokument (labels=None: echter Name, intern)."""
    if labels is None:
        if wallet.startswith("bitbox:"):
            return wallet[len("bitbox:"):]
        return _PSEUDO.get(wallet, wallet)
    if wallet in labels:
        return labels[wallet]
    if wallet.startswith("bitbox:"):
        return "BitBox-Wallet"      # fail closed: nie den Namen
    return _PSEUDO.get(wallet, wallet)


@dataclass
class MoveRow:
    """Eine Umbuchung zwischen eigenen Wallets (oder in eine nicht eingelesene)."""
    date: datetime          # Zeitpunkt der Umbuchung (Zugang, nie vor dem Abgang)
    src: str
    dst: str
    btc_amount: Decimal
    lots: list[Lot]
    method: str             # "tx-id" | "betrag" | "manuell" | "" (kein Eingang)
    kind: LinkKind | None   # None = Abgang ohne Eingang
    no_kyc: bool

    @property
    def covered(self) -> Decimal:
        return sum((l.btc_amount for l in self.lots), ZERO)


def move_rows(engine, year: int | None = None) -> list[MoveRow]:
    rows = []
    for link, lots in engine.moves:
        when = max(link.giver.date, link.taker.date)
        rows.append(MoveRow(when, link.giver.wallet, link.taker.wallet, link.btc_amount,
                            lots, link.method, link.kind, link.giver.no_kyc))
    for tx, lots in engine.parked:
        rows.append(MoveRow(tx.date, tx.wallet, EXTERN_WALLET,
                            sum((l.btc_amount for l in lots), ZERO) if lots else tx.btc_amount,
                            lots, "", None, tx.no_kyc))
    if year:
        rows = [r for r in rows if de_date(r.date).year == year]
    return sorted(rows, key=lambda r: (r.date, r.src, r.dst))


def _lot_range(lots: list[Lot]) -> str:
    if not lots:
        return "—"
    dates = sorted(de_date(l.purchase_date) for l in lots)
    return f"{dates[0]}" if dates[0] == dates[-1] else f"{dates[0]}–{dates[-1]}"


def move_table(rows: list[MoveRow], labels: dict[str, str] | None) -> list[str]:
    """Tabelle der Umbuchungen; Anschaffungsdaten der mitgewanderten Lots."""
    lines = [
        f"  {'Datum':<10} {'Von':<17} {'Nach':<17} {'Menge BTC':>11} {'Anschaffung':<21} {'Zuordnung'}",
        f"  {'-'*10} {'-'*17} {'-'*17} {'-'*11} {'-'*21} {'-'*11}",
    ]
    for r in rows:
        lines.append(
            f"  {de_date(r.date)!s:<10} {label(r.src, labels)[:17]:<17} {label(r.dst, labels)[:17]:<17} "
            f"{r.btc_amount:>11.8f} {_lot_range(r.lots):<21} {_METHOD.get(r.method, r.method)}"
        )
        if r.covered < r.btc_amount:
            lines.append(f"  {'':<10} ACHTUNG: {r.btc_amount - r.covered:.8f} BTC davon ohne Anschaffungsdaten")
    return lines


def lots_by_wallet(lots: list[Lot]) -> list[tuple[str, list[Lot]]]:
    groups: dict[str, list[Lot]] = {}
    for lot in lots:
        groups.setdefault(lot.wallet, []).append(lot)
    order = lambda w: (w == EXTERN_WALLET, w)
    return [(w, sorted(groups[w], key=lambda l: l.purchase_date)) for w in sorted(groups, key=order)]


# ── Interne Datei ──

def _year_totals(engine, year: int, no_kyc: bool) -> tuple[Decimal, Decimal, Decimal]:
    def in_year(sr):
        return de_date(sr.sell_tx.date).year == year and sr.sell_tx.no_kyc == no_kyc
    disposals = [sr for sr in engine.sell_results + engine.fee_results if in_year(sr)]
    taxable = sum((sr.total_gain_taxable for sr in disposals), ZERO)
    free = sum((sr.total_gain_tax_free for sr in disposals), ZERO)
    open_btc = sum((sr.unmatched_btc for sr in disposals), ZERO)
    return taxable, free, open_btc


def internal_report(engine, compare, transactions: list[Transaction], year: int) -> str:
    """wallet_abgleich_intern_JJJJ.txt — NICHT für Finanzamt/Steuerberater."""
    from .tax_report import _freigrenze   # spät, kein Zyklus
    lines = ["=" * 72,
             "  !! INTERN — NICHT FÜR FINANZAMT BESTIMMT !!",
             "",
             f"  Wallet-Abgleich {year}: walletbezogene FiFo-Rechnung (BMF 06.03.2025",
             "  Rn. 62) mit echten Wallet-Namen, Vergleich zur früheren gemeinsamen",
             "  Rechnung über alle Wallets und alle offenen Zuordnungen.",
             "  Enthält Wallet-Namen und ggf. noKYC-Angaben — NICHT weitergeben.",
             "=" * 72]

    lines += ["", "VERGLEICH: WALLETBEZOGEN (Reports) ↔ GEMEINSAM (bis Oktober 2026)", "-" * 72,
              f"  {'':<26} {'walletbezogen':>15} {'gemeinsam':>15} {'Differenz':>12}"]
    grenze = _freigrenze(year)
    for no_kyc, name in ((False, "KYC (Finanzamt)"), (True, "noKYC (intern)")):
        w = _year_totals(engine, year, no_kyc)
        g = _year_totals(compare, year, no_kyc)
        if not any(w) and not any(g):
            continue
        lines.append(f"  {name}")
        for i, what in enumerate(("Gewinn steuerpflichtig", "Gewinn steuerfrei", "BTC ohne Zuordnung")):
            if i == 2:
                lines.append(f"    {what:<24} {w[i]:>15.8f} {g[i]:>15.8f} {w[i]-g[i]:>+12.8f}")
            else:
                lines.append(f"    {what:<24} {w[i]:>15,.2f} {g[i]:>15,.2f} {w[i]-g[i]:>+12,.2f}")
        if not no_kyc:
            def status(x):
                return "steuerpflichtig" if x >= grenze else "unter Freigrenze" if x > 0 else "—"
            lines.append(f"    {'Freigrenze ' + format(grenze, ',.0f') + ' EUR':<24} "
                         f"{status(w[0]):>15} {status(g[0]):>15}")
    lines.append("  (steuerpflichtig inkl. Gebühren in BTC; ohne Freigrenzen-Kürzung)")

    rows = move_rows(engine, year)
    if rows:
        lines += ["", f"UMBUCHUNGEN {year} (echte Namen)", "-" * 72]
        for no_kyc, name in ((False, "KYC"), (True, "noKYC")):
            part = [r for r in rows if r.no_kyc == no_kyc]
            if part:
                lines.append(f"  {name}:")
                lines += move_table(part, None)

    m = engine.matching
    if m:
        def yr(t):
            return de_date(t.date).year == year
        def fmt(t):
            cls = " [noKYC]" if t.no_kyc else ""
            return (f"    {de_date(t.date)}  {label(t.wallet, None):<20} {t.btc_amount:>12.8f} BTC"
                    f"  ({t.source}){cls}")
        groups = [
            ("Eingänge ohne zugeordneten Abgang (Bestand ohne Anschaffungsdaten)", m.unmatched_in),
            ("Direktkäufe ohne zugeordnete Lieferung (Lots bleiben beim Anbieter)", m.unmatched_buys),
            ("Direktverkäufe ohne zugeordneten Abgang", m.unmatched_sells),
        ]
        open_any = [(t, items) for t, items in groups if any(yr(x) for x in items)]
        if open_any:
            lines += ["", f"OFFENE ZUORDNUNGEN {year}", "-" * 72]
            for title, items in open_any:
                lines.append(f"  {title}:")
                lines += [fmt(x) for x in items if yr(x)]
            lines.append("  Abhilfe: fehlende Exporte ergänzen oder transfer_zuordnung.csv.")

    lots = engine.lots_at_year_end(year)
    if lots:
        lines += ["", f"BESTAND JE WALLET — Stand 31.12.{year} (echte Namen)", "-" * 72]
        for wallet, wl in lots_by_wallet(lots):
            for no_kyc in (False, True):
                part = [l for l in wl if l.no_kyc == no_kyc]
                if not part:
                    continue
                total = sum((l.btc_amount for l in part), ZERO)
                cls = " [noKYC]" if no_kyc else ""
                lines.append(f"  {label(wallet, None)}{cls}: {total:.8f} BTC in {len(part)} Lot(s)")
                for l in part:
                    lines.append(f"    Kauf {de_date(l.purchase_date)}  ({l.source})  {l.btc_amount:>12.8f}"
                                 f"  @ {l.cost_per_btc:,.2f} EUR/BTC")
    lines.append("=" * 72)
    return "\n".join(lines)
