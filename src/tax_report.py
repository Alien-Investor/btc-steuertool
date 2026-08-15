"""Generierung des Steuerreports (Text + CSV) aus FiFo-Ergebnissen."""
from __future__ import annotations
import csv
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .models import Transaction, TxType, SellResult, Lot, de_date

CENT = Decimal("0.01")
SATOSHI_8 = Decimal("0.00000001")

# Freigrenze private Veräußerungsgeschäfte (§ 23 EStG)
FREIGRENZE = {2023: Decimal("600"), 2024: Decimal("1000")}
FREIGRENZE_DEFAULT_AB_2024 = Decimal("1000")
FREIGRENZE_DEFAULT_BIS_2023 = Decimal("600")


def _r(val) -> Decimal:
    # Decimal(str(val)) statt val.quantize(): leere Summen liefern int 0,
    # das kein quantize() kennt (siehe SellResult-Aggregate in models.py).
    return Decimal(str(val)).quantize(CENT, rounding=ROUND_HALF_UP)


def _eur(val: Decimal) -> str:
    return f"{_r(val):,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")


def _btc(val: Decimal) -> str:
    return f"{val:.8f} BTC"


def _freigrenze(year: int) -> Decimal:
    if year >= 2024:
        return FREIGRENZE_DEFAULT_AB_2024
    return FREIGRENZE.get(year, FREIGRENZE_DEFAULT_BIS_2023)


class TaxReport:
    def __init__(
        self,
        all_transactions: list[Transaction],
        sell_results: list[SellResult],
        remaining_lots: list[Lot],
        warnings: list,
        year: int | None = None,
        internal_warnings: list | None = None,
    ):
        self.all_transactions = all_transactions
        self.sell_results = sell_results
        self.remaining_lots = remaining_lots
        self.warnings = warnings                       # nur Finanzamt-taugliche
        self.internal_warnings = internal_warnings or []  # noKYC — nur intern
        self.year = year

        # Filterung auf gewünschtes Jahr (deutsches Kalenderjahr!) — noKYC immer separat halten
        if year:
            all_buys = [t for t in all_transactions if t.type == TxType.BUY and de_date(t.date).year == year]
            all_sells = [sr for sr in sell_results if de_date(sr.sell_tx.date).year == year]
        else:
            all_buys = [t for t in all_transactions if t.type == TxType.BUY]
            all_sells = sell_results

        self.buys = [t for t in all_buys if not t.no_kyc]
        self.no_kyc_buys = [t for t in all_buys if t.no_kyc]

        # Verkäufe trennen: KYC → offizieller Report, noKYC → nur intern
        self.sells = [sr for sr in all_sells if not sr.sell_tx.no_kyc]
        self.no_kyc_sells = [sr for sr in all_sells if sr.sell_tx.no_kyc]

        # Verbleibende Lots ebenfalls aufteilen
        self._all_remaining_lots = remaining_lots
        self.remaining_lots = [l for l in remaining_lots if not l.no_kyc]
        # noKYC-Bestände nur im Gesamt- oder aktuellen Jahresreport (wie KYC-Bestände)
        if not year or year == date.today().year:
            self.no_kyc_lots = [l for l in remaining_lots if l.no_kyc]
        else:
            self.no_kyc_lots = []

        # noKYC-Wallet-Transfers (TRANSFER_IN/OUT aus bitbox/nokyc/)
        transfer_types = (TxType.TRANSFER_IN, TxType.TRANSFER_OUT)
        if year:
            all_transfers = [t for t in all_transactions if t.type in transfer_types and de_date(t.date).year == year]
        else:
            all_transfers = [t for t in all_transactions if t.type in transfer_types]
        self.no_kyc_transfers = [t for t in all_transfers if t.no_kyc]

    def print_report(self) -> str:
        lines = []
        year_label = str(self.year) if self.year else "Gesamt (alle Jahre)"

        lines.append("=" * 72)
        lines.append(f"  Bitcoin Steuerreport Deutschland — {year_label}")
        lines.append(f"  Methode: FiFo  |  Haltefrist: 365 Tage  |  § 23 EStG")
        lines.append("=" * 72)

        if self.warnings:
            lines.append("")
            lines.append("!! WARNUNGEN !!")
            for w in self.warnings:
                lines.append(f"  {w}")

        # --- Käufe ---
        lines.append("")
        lines.append("KÄUFE")
        lines.append("-" * 72)
        lines.append(f"  {'Datum':<12} {'Quelle':<14} {'BTC-Menge':>14} {'Kurs EUR/BTC':>16} {'Gebühr':>12} {'Einstand':>14}")
        lines.append(f"  {'-'*12} {'-'*14} {'-'*14} {'-'*16} {'-'*12} {'-'*14}")

        total_buy_btc: Decimal = Decimal("0")
        total_buy_eur: Decimal = Decimal("0")
        total_buy_fee: Decimal = Decimal("0")

        for tx in sorted(self.buys, key=lambda t: t.date):
            einstand = _r(tx.eur_amount + tx.fee_eur)
            lines.append(
                f"  {de_date(tx.date)!s:<12} {tx.source:<14} {tx.btc_amount:>14.8f} "
                f"{_r(tx.eur_price_per_btc):>16,.2f} {_r(tx.fee_eur):>12,.2f} {einstand:>14,.2f}"
            )
            total_buy_btc += tx.btc_amount
            total_buy_eur += tx.eur_amount
            total_buy_fee += tx.fee_eur

        lines.append(f"  {'─'*72}")
        lines.append(f"  {'SUMME':<28} {total_buy_btc:>14.8f} {'':>16} {_r(total_buy_fee):>12,.2f} {_r(total_buy_eur + total_buy_fee):>14,.2f}")

        # --- Verkäufe ---
        taxable_sells = [sr for sr in self.sells if any(not m.is_tax_free for m in sr.matches)]
        tax_free_sells = [sr for sr in self.sells if any(m.is_tax_free for m in sr.matches)]
        # Deckungstest, kein Leere-Test: Verkäufe ohne JEDE Lot-Zuordnung fallen
        # durch BEIDE any()-Filter und würden spurlos verschwinden; nur TEILWEISE
        # gedeckte Verkäufe stehen zwar oben, aber die ungedeckte Menge bliebe
        # sonst unerwähnt und würde als steuerfrei mitgezählt.
        uncovered_sells = [sr for sr in self.sells if not sr.is_fully_covered]

        if uncovered_sells:
            lines.append("")
            lines.append("VERÄUSSERUNGEN OHNE VOLLSTÄNDIGE ANSCHAFFUNGS-ZUORDNUNG")
            lines.append("-" * 72)
            for sr in uncovered_sells:
                tx = sr.sell_tx
                lines.append(
                    f"  Verkauf: {de_date(tx.date)}  {tx.source}  "
                    f"{tx.btc_amount:.8f} BTC  =  {_r(tx.eur_amount):,.2f} EUR"
                )
                if sr.matches:
                    lines.append(
                        f"    ACHTUNG: nur {sr.total_btc_matched:.8f} BTC konnten zugeordnet werden."
                    )
                    lines.append(
                        f"    Für {sr.unmatched_btc:.8f} BTC sind Haltedauer und Steuerfreiheit "
                        "NICHT nachgewiesen."
                    )
                else:
                    lines.append(
                        "    ACHTUNG: kein Anschaffungsgeschäft zugeordnet — Haltedauer und "
                        "Steuerfreiheit NICHT nachgewiesen."
                    )
            lines.append("")

        if taxable_sells:
            lines.append("")
            lines.append("STEUERPFLICHTIGE VERÄUSSERUNGEN (Haltedauer ≤ 365 Tage)")
            lines.append("-" * 72)
            for sr in taxable_sells:
                lines.extend(_format_sell(sr, only_taxable=True))

        if tax_free_sells:
            lines.append("")
            lines.append("STEUERFREIE VERÄUSSERUNGEN (Haltedauer > 365 Tage)")
            lines.append("-" * 72)
            for sr in tax_free_sells:
                lines.extend(_format_sell(sr, only_taxable=False))

        # --- Jahres-Zusammenfassung ---
        lines.extend(self._summary_section())

        # --- Verbleibende Bestände (nur bei Gesamtreport oder letztem Jahr) ---
        if not self.year or self.year == date.today().year:
            lines.extend(self._remaining_lots_section())

        return "\n".join(lines)

    def nokyc_report(self) -> str | None:
        """Gibt den noKYC-Intern-Report zurück, oder None wenn keine noKYC-Daten vorhanden."""
        if (not self.no_kyc_buys and not self.no_kyc_lots
                and not self.no_kyc_transfers and not self.no_kyc_sells
                and not self.internal_warnings):
            return None
        year_label = str(self.year) if self.year else "Gesamt"
        lines = []
        lines.append("=" * 72)
        lines.append("  !! INTERN — NICHT FÜR FINANZAMT BESTIMMT !!")
        lines.append("")
        lines.append("  Diese Datei enthält noKYC-Käufe und -Verkäufe (Bisq / Robosats / P2P).")
        lines.append("  Sie dient ausschließlich der eigenen Buchführung.")
        lines.append("  NICHT an Steuerberater oder Finanzamt weitergeben.")
        lines.append("")
        lines.append(f"  Für das Finanzamt:  steuerreport_{year_label}.txt")
        lines.append(f"  Formaler Nachweis:  steuernachweis_{year_label}.txt")
        lines.append("=" * 72)
        # Warnungen, die noKYC-Vorgänge betreffen: stehen bewusst NUR hier,
        # nicht im Steuerreport und nicht im Nachweis.
        if self.internal_warnings:
            lines.append("")
            lines.append("!! HINWEISE ZU noKYC-VORGÄNGEN !!")
            for w in self.internal_warnings:
                lines.append(f"  {w}")
            lines.append("")
        lines.extend(self._no_kyc_section())
        return "\n".join(lines)

    def _summary_section(self) -> list[str]:
        lines = []
        year_label = str(self.year) if self.year else "Gesamt"
        freigrenze = _freigrenze(self.year) if self.year else None

        total_proceeds = sum((_r(sr.sell_tx.eur_amount) for sr in self.sells), Decimal("0"))
        total_fees_sell = sum((_r(sr.sell_tx.fee_eur) for sr in self.sells), Decimal("0"))
        total_gain_taxable = sum((sr.total_gain_taxable for sr in self.sells), Decimal("0"))
        total_gain_tax_free = sum((sr.total_gain_tax_free for sr in self.sells), Decimal("0"))

        lines.append("")
        lines.append(f"ZUSAMMENFASSUNG {year_label}")
        lines.append("=" * 72)
        lines.append(f"  Veräußerungserlöse (gesamt):      {_r(total_proceeds):>14,.2f} EUR")
        lines.append(f"  Verkaufsgebühren:                 {_r(total_fees_sell):>14,.2f} EUR")

        if freigrenze is not None:
            if total_gain_taxable > 0:
                # § 23 Abs. 3 EStG: steuerfrei nur, wenn der Gesamtgewinn WENIGER als
                # die Freigrenze beträgt — exakt 1.000,00 EUR ist bereits voll steuerpflichtig
                if total_gain_taxable >= freigrenze:
                    status = f"ERREICHT/ÜBERSCHRITTEN (Grenze: {_r(freigrenze):,.2f} EUR) → voller Betrag steuerpflichtig"
                else:
                    status = f"NICHT ERREICHT (steuerfrei bleibt nur ein Gesamtgewinn unter {_r(freigrenze):,.2f} EUR) → steuerfrei"
            else:
                status = "kein steuerpflichtiger Gewinn"

            lines.append(f"  ─────────────────────────────────────────────────────────────────")
            lines.append(f"  Gewinn steuerpflichtig (≤ 365 Tage): {_r(total_gain_taxable):>10,.2f} EUR")
            lines.append(f"  Gewinn steuerfrei (> 365 Tage):      {_r(total_gain_tax_free):>10,.2f} EUR")
            lines.append(f"  Freigrenze {self.year} ({_r(freigrenze):,.0f} EUR): {status}")
            lines.append(f"  Hinweis: Die Freigrenze gilt für ALLE privaten Veräußerungsgeschäfte")
            lines.append(f"  des Jahres zusammen (§ 23 EStG) — nicht nur für Bitcoin.")
        else:
            lines.append(f"  ─────────────────────────────────────────────────────────────────")
            lines.append(f"  Gewinn steuerpflichtig (≤ 365 Tage): {_r(total_gain_taxable):>10,.2f} EUR")
            lines.append(f"  Gewinn steuerfrei (> 365 Tage):      {_r(total_gain_tax_free):>10,.2f} EUR")

        lines.append(f"  Gesamtgewinn/-verlust:            {_r(total_gain_taxable + total_gain_tax_free):>14,.2f} EUR")

        # Ohne diesen Hinweis liest sich die Summe als vollständig — sie enthält
        # aber nur die Mengen, für die überhaupt ein Einstandspreis existiert.
        uncovered_btc = sum((sr.unmatched_btc for sr in self.sells), Decimal("0"))
        if uncovered_btc > 0:
            lines.append(f"  {'─'*65}")
            lines.append(f"  ACHTUNG: {uncovered_btc:.8f} BTC ohne Anschaffungs-Zuordnung.")
            lines.append(f"  Für diese Menge sind Haltedauer und Steuerfreiheit NICHT")
            lines.append(f"  nachgewiesen; sie sind in den Gewinnsummen NICHT enthalten.")

        lines.append("=" * 72)
        return lines

    def _remaining_lots_section(self) -> list[str]:
        if not self.remaining_lots:
            return []
        lines = []
        lines.append("")
        lines.append("VERBLEIBENDE BTC-BESTÄNDE (noch nicht veräußert)")
        lines.append("-" * 72)
        lines.append(f"  {'Kaufdatum':<12} {'Quelle':<14} {'BTC-Bestand':>14} {'Einstand EUR/BTC':>18} {'Wert EUR':>12}")
        lines.append(f"  {'-'*12} {'-'*14} {'-'*14} {'-'*18} {'-'*12}")
        total_btc = Decimal("0")
        for lot in sorted(self.remaining_lots, key=lambda l: l.purchase_date):
            wert = _r(lot.btc_amount * lot.cost_per_btc)
            lines.append(
                f"  {de_date(lot.purchase_date)!s:<12} {lot.source:<14} {lot.btc_amount:>14.8f} "
                f"{lot.cost_per_btc:>18,.2f} {wert:>12,.2f}"
            )
            total_btc += lot.btc_amount
        lines.append(f"  {'─'*72}")
        lines.append(f"  {'GESAMT':<28} {total_btc:>14.8f}")
        return lines

    def _no_kyc_section(self) -> list[str]:
        lines = []
        lines.append("")
        lines.append("~" * 72)
        lines.append("  INTERNE ÜBERSICHT — noKYC (Bisq/Robosats/P2P)")
        lines.append("  Nicht für Finanzamt — nur für interne Kalkulation und Rückfragen")
        lines.append("~" * 72)

        if self.no_kyc_buys:
            lines.append("")
            lines.append(f"  {'Datum':<12} {'Quelle':<10} {'BTC-Menge':>14} {'Kurs EUR/BTC':>16} {'Gebühr':>12} {'Einstand':>14}")
            lines.append(f"  {'-'*12} {'-'*10} {'-'*14} {'-'*16} {'-'*12} {'-'*14}")

            total_btc = Decimal("0")
            total_eur = Decimal("0")
            total_fee = Decimal("0")

            for tx in sorted(self.no_kyc_buys, key=lambda t: t.date):
                einstand = _r(tx.eur_amount + tx.fee_eur)
                lines.append(
                    f"  {de_date(tx.date)!s:<12} {tx.source:<10} {tx.btc_amount:>14.8f} "
                    f"{_r(tx.eur_price_per_btc):>16,.2f} {_r(tx.fee_eur):>12,.2f} {einstand:>14,.2f}"
                )
                total_btc += tx.btc_amount
                total_eur += tx.eur_amount
                total_fee += tx.fee_eur

            lines.append(f"  {'─'*72}")
            lines.append(f"  {'SUMME':<24} {total_btc:>14.8f} {'':>16} {_r(total_fee):>12,.2f} {_r(total_eur + total_fee):>14,.2f}")

        if self.no_kyc_sells:
            lines.append("")
            lines.append("  noKYC-VERKÄUFE (aus noKYC-FiFo-Pool)")
            lines.append("  Hinweis: Haltefrist/Gewinn zur eigenen steuerlichen Einordnung.")
            for sr in self.no_kyc_sells:
                tx = sr.sell_tx
                lines.append("")
                lines.append(
                    f"  Verkauf: {de_date(tx.date)}  {tx.btc_amount:.8f} BTC  "
                    f"@  {_r(tx.eur_price_per_btc):,.2f} EUR/BTC  =  {_r(tx.eur_amount):,.2f} EUR  ({tx.note})"
                )
                for m in sr.matches:
                    status = "haltefrist abgelaufen" if m.is_tax_free else f"{m.holding_days} Tage — innerhalb Haltefrist"
                    lines.append(
                        f"    Lot: Kauf {de_date(m.lot_purchase_date)}  ({m.lot_source})  "
                        f"{m.btc_used:.8f} BTC  @  {m.cost_per_btc:,.2f} EUR/BTC"
                        f"  →  {'+' if m.gain_eur >= 0 else ''}{_r(m.gain_eur):,.2f} EUR  [{status}]"
                    )
                lines.append(f"    Gewinn gesamt: {_r(sr.total_gain):+,.2f} EUR")

        if self.no_kyc_lots:
            lines.append("")
            lines.append("  VERBLEIBENDE noKYC-BESTÄNDE")
            lines.append(f"  {'Kaufdatum':<12} {'Quelle':<10} {'BTC-Bestand':>14} {'Einstand EUR/BTC':>18}")
            lines.append(f"  {'-'*12} {'-'*10} {'-'*14} {'-'*18}")
            total_btc = Decimal("0")
            for lot in sorted(self.no_kyc_lots, key=lambda l: l.purchase_date):
                lines.append(
                    f"  {de_date(lot.purchase_date)!s:<12} {lot.source:<10} {lot.btc_amount:>14.8f} "
                    f"{lot.cost_per_btc:>18,.2f}"
                )
                total_btc += lot.btc_amount
            lines.append(f"  {'─'*72}")
            lines.append(f"  {'GESAMT':<24} {total_btc:>14.8f}")

        if self.no_kyc_transfers:
            lines.append("")
            lines.append("  noKYC-WALLET-AKTIVITÄT (bitbox/nokyc/)")
            lines.append(f"  {'Datum':<12} {'Wallet':<20} {'Typ':<12} {'BTC-Betrag':>14} {'Note'}")
            lines.append(f"  {'-'*12} {'-'*20} {'-'*12} {'-'*14} {'-'*20}")
            total_in = Decimal("0")
            total_out = Decimal("0")
            for tx in sorted(self.no_kyc_transfers, key=lambda t: t.date):
                typ = "empfangen" if tx.type == TxType.TRANSFER_IN else "gesendet "
                wallet = tx.source.replace("bitbox:", "")
                lines.append(
                    f"  {de_date(tx.date)!s:<12} {wallet:<20} {typ:<12} {tx.btc_amount:>14.8f}  {tx.note}"
                )
                if tx.type == TxType.TRANSFER_IN:
                    total_in += tx.btc_amount
                else:
                    total_out += tx.btc_amount
            lines.append(f"  {'─'*72}")
            lines.append(f"  Gesamt empfangen: {total_in:>14.8f} BTC")
            lines.append(f"  Gesamt gesendet:  {total_out:>14.8f} BTC")
            lines.append(f"  Netto (Saldo):    {total_in - total_out:>14.8f} BTC")

        lines.append("~" * 72)
        return lines

    def save_csv(self, output_dir: Path) -> list[Path]:
        """Speichert Käufe und Verkäufe als separate CSV-Dateien."""
        output_dir.mkdir(parents=True, exist_ok=True)
        year_label = str(self.year) if self.year else "gesamt"
        saved = []

        # Käufe CSV
        buys_path = output_dir / f"kaeufe_{year_label}.csv"
        with open(buys_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Datum", "Quelle", "BTC-Menge", "Kurs_EUR_per_BTC", "Gebuehr_EUR", "Einstand_EUR"])
            for tx in sorted(self.buys, key=lambda t: t.date):
                w.writerow([
                    de_date(tx.date),
                    tx.source,
                    f"{tx.btc_amount:.8f}",
                    f"{_r(tx.eur_price_per_btc):.2f}",
                    f"{_r(tx.fee_eur):.2f}",
                    f"{_r(tx.eur_amount + tx.fee_eur):.2f}",
                ])
        saved.append(buys_path)

        # Verkäufe CSV (aufgeschlüsselt nach Lots)
        sells_path = output_dir / f"verkaeufe_{year_label}.csv"
        with open(sells_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "Verkauf_Datum", "Verkauf_Quelle", "Verkauf_BTC", "Verkauf_EUR",
                "Kauf_Datum", "Kauf_Quelle", "BTC_Menge", "Einstand_EUR_per_BTC",
                "Verkaufspreis_EUR_per_BTC", "Gewinn_EUR", "Haltedauer_Tage", "Steuerfrei",
                # Pro Verkauf konstant (wie Verkauf_BTC/Verkauf_EUR): die Menge
                # dieses Verkaufs, der kein Anschaffungsgeschäft zugeordnet werden
                # konnte. Ohne die Spalte steht in einer Zeile Verkauf_BTC=2.0
                # neben BTC_Menge=0.5 und Steuerfrei=Ja — die Lücke wäre unsichtbar.
                "Nicht_zugeordnet_BTC",
            ])
            for sr in self.sells:
                unmatched = f"{sr.unmatched_btc:.8f}"
                for m in sr.matches:
                    w.writerow([
                        de_date(sr.sell_tx.date),
                        sr.sell_tx.source,
                        f"{sr.sell_tx.btc_amount:.8f}",
                        f"{_r(sr.sell_tx.eur_amount):.2f}",
                        de_date(m.lot_purchase_date),
                        m.lot_source,
                        f"{m.btc_used:.8f}",
                        f"{m.cost_per_btc:.2f}",
                        f"{m.net_sell_price_per_btc:.2f}",
                        f"{_r(m.gain_eur):.2f}",
                        m.holding_days,
                        "Ja" if m.is_tax_free else "Nein",
                        unmatched,
                    ])
                # Restzeile für die ungedeckte Menge. Ohne sie erscheint ein
                # komplett unzugeordneter Verkauf GAR NICHT in der Datei (die
                # Schleife über matches läuft leer) und BTC_Menge summiert sich
                # bei Teildeckung nicht auf Verkauf_BTC.
                if sr.unmatched_btc > 0:
                    w.writerow([
                        de_date(sr.sell_tx.date),
                        sr.sell_tx.source,
                        f"{sr.sell_tx.btc_amount:.8f}",
                        f"{_r(sr.sell_tx.eur_amount):.2f}",
                        "", "",
                        unmatched,
                        "", "", "", "",
                        "NICHT NACHGEWIESEN",
                        unmatched,
                    ])
        saved.append(sells_path)

        return saved


def _format_sell(sr: SellResult, only_taxable: bool) -> list[str]:
    lines = []
    tx = sr.sell_tx
    lines.append(
        f"  Verkauf: {de_date(tx.date)}  {tx.source}  "
        f"{tx.btc_amount:.8f} BTC  @  {_r(tx.eur_price_per_btc):,.2f} EUR/BTC  =  {_r(tx.eur_amount):,.2f} EUR"
    )
    if tx.fee_eur > 0:
        lines.append(f"           Gebühr: {_r(tx.fee_eur):,.2f} EUR")

    relevant_matches = [m for m in sr.matches if m.is_tax_free != only_taxable]
    for m in relevant_matches:
        status = "STEUERFREI" if m.is_tax_free else f"{m.holding_days} Tage"
        gain_str = f"{'+' if m.gain_eur >= 0 else ''}{_r(m.gain_eur):,.2f} EUR"
        lines.append(
            f"    Lot: Kauf {de_date(m.lot_purchase_date)}  ({m.lot_source})  "
            f"{m.btc_used:.8f} BTC  @  {m.cost_per_btc:,.2f} EUR/BTC"
            f"  →  {gain_str}  [{status}]"
        )

    sell_gain = sum(
        (m.gain_eur for m in sr.matches if m.is_tax_free != only_taxable),
        start=Decimal("0"),
    )
    lines.append(f"    Gewinn: {_r(sell_gain):+,.2f} EUR")
    lines.append("")
    return lines
