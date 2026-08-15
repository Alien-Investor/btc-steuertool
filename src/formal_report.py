"""
Formaler Steuernachweis für Steuerberater und Finanzamt.
Erzeugt ein selbsterklärendes Dokument das ohne Kenntnis des Tools lesbar ist.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Transaction, TxType, SellResult, Lot, de_date
from .tax_report import _freigrenze, _src_label
from . import btc_prices

CENT = Decimal("0.01")

# Deutsche Zeit explizit (Steuerdokument!) — unabhängig von der System-Zeitzone,
# damit CLI und Browser-Version (läuft in UTC) identische Nachweise erzeugen
_TZ_DE = ZoneInfo("Europe/Berlin")


def _r(val) -> Decimal:
    return Decimal(str(val)).quantize(CENT, rounding=ROUND_HALF_UP)


def _eur(val: Decimal) -> str:
    s = f"{_r(val):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " EUR"


def _btc(val: Decimal) -> str:
    return f"{val:.8f} BTC"


def generate_tax_free_proof(
    all_transactions: list[Transaction],
    sell_results: list[SellResult],
    remaining_lots: list[Lot],
    year: int,
    output_path: Path,
    warnings: list[str] | None = None,
    fee_results: list[SellResult] | None = None,
    gift_results: list[SellResult] | None = None,
) -> None:
    """Erzeugt einen formalen Steuernachweis als Textdatei."""

    # Jahres-Zuordnung nach deutschem Kalenderdatum (Europe/Berlin), nicht UTC
    sells_in_year = [
        sr for sr in sell_results
        if de_date(sr.sell_tx.date).year == year and not sr.sell_tx.no_kyc
    ]
    # Gebühren-Abgänge (Veräußerung des Gebührenanteils, H8) und unentgeltliche
    # Übertragungen — nur KYC, wie die Verkäufe
    fees_in_year = sorted(
        [sr for sr in (fee_results or [])
         if de_date(sr.sell_tx.date).year == year and not sr.sell_tx.no_kyc],
        key=lambda sr: sr.sell_tx.date,
    )
    gifts_in_year = sorted(
        [sr for sr in (gift_results or [])
         if de_date(sr.sell_tx.date).year == year and not sr.sell_tx.no_kyc],
        key=lambda sr: sr.sell_tx.date,
    )
    unpriced_fees = [sr for sr in fees_in_year if not sr.is_priced]
    buys_in_year = sorted(
        [t for t in all_transactions if t.type == TxType.BUY and de_date(t.date).year == year and not t.no_kyc],
        key=lambda t: t.date,
    )
    kyc_transactions = [t for t in all_transactions if not t.no_kyc]

    lines = []
    W = 76

    def sep(char="="):
        lines.append(char * W)

    def title(text):
        lines.append(text.center(W))

    def blank():
        lines.append("")

    def para(text):
        # Einfacher Zeilenumbruch bei > 76 Zeichen
        words = text.split()
        line = ""
        for word in words:
            if len(line) + len(word) + 1 > W:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            lines.append(line)

    # =========================================================
    # DECKBLATT
    # =========================================================
    sep()
    blank()
    title("NACHWEIS STEUERFREIER BITCOIN-VERÄUSSERUNGEN")
    blank()
    title(f"Steuerjahr {year}")
    blank()
    title("Privatveräußerungsgeschäfte gemäß § 23 Abs. 1 Satz 1 Nr. 2 EStG")
    blank()
    sep()
    blank()
    # Explizit Europe/Berlin, nicht die System-Zeitzone: die Browser-Version läuft
    # in UTC, und am Jahreswechsel stünde sonst ein anderes Erstellungsdatum im
    # Dokument als in der CLI-Fassung derselben Daten (SA2-14).
    lines.append(f"  Erstellt am:        {datetime.now(_TZ_DE).strftime('%d.%m.%Y')}")
    lines.append(f"  Berechnungsmethode: First In, First Out (FiFo)")
    lines.append(f"  Veräußerungsfrist:  ein Jahr (§ 23 Abs. 1 Satz 1 Nr. 2 EStG i.V.m.")
    lines.append(f"                      §§ 187 Abs. 1, 188 Abs. 2 BGB)")
    lines.append(f"  Freigrenze {year}:    {_eur(_freigrenze(year))}")
    blank()

    # =========================================================
    # WICHTIGE HINWEISE (Warnungen aus Einlesen/Berechnung)
    # =========================================================
    if warnings:
        sep()
        lines.append("  WICHTIGE HINWEISE — BITTE VOR VERWENDUNG PRÜFEN")
        sep()
        blank()
        para(
            "Beim Einlesen der Daten bzw. bei der Berechnung sind Hinweise "
            "aufgetreten. Dieser Nachweis ist möglicherweise unvollständig, "
            "solange die folgenden Punkte nicht geklärt sind:"
        )
        blank()
        for w in warnings:
            para(f"  - {w}")
        blank()

    # =========================================================
    # ERGEBNIS-ZUSAMMENFASSUNG
    # =========================================================
    sep()
    lines.append("  ERGEBNIS")
    sep()
    blank()

    fee_taxable: Decimal = sum((sr.total_gain_taxable for sr in fees_in_year), Decimal("0"))
    fee_free: Decimal = sum((sr.total_gain_tax_free for sr in fees_in_year), Decimal("0"))
    fee_proceeds: Decimal = sum((_r(sr.proceeds_eur) for sr in fees_in_year if sr.is_priced), Decimal("0"))
    fee_btc_total: Decimal = sum((sr.disposed_btc for sr in fees_in_year), Decimal("0"))
    # Gebühren-Abgänge sind Veräußerungen — ihre Gewinne zählen in die Summen
    # und damit in die Freigrenze (H8)
    total_taxable: Decimal = sum((sr.total_gain_taxable for sr in sells_in_year), Decimal("0")) + fee_taxable
    total_free: Decimal = sum((sr.total_gain_tax_free for sr in sells_in_year), Decimal("0")) + fee_free
    total_proceeds: Decimal = sum((_r(sr.sell_tx.eur_amount) for sr in sells_in_year), Decimal("0"))

    para(
        f"Im Steuerjahr {year} wurden {len(sells_in_year)} Bitcoin-Veräußerung(en) "
        f"mit einem Gesamterlös von {_eur(total_proceeds)} durchgeführt."
    )
    blank()
    if fees_in_year:
        para(
            f"Daneben wurden {len(fees_in_year)} in Bitcoin entrichtete Netzwerk- bzw. "
            f"Auszahlungsgebühren über insgesamt {_btc(fee_btc_total)} als Veräußerung "
            f"des jeweiligen Gebührenanteils erfasst (Tausch gegen eine Dienstleistung, "
            f"BMF-Schreiben vom 06.03.2025, Rn. 54, 60); Veräußerungserlös zum Tageskurs "
            f"insgesamt {_eur(fee_proceeds)}. Die daraus resultierenden Gewinne bzw. "
            f"Verluste sind in den nachfolgenden Summen enthalten."
        )
        blank()
    if unpriced_fees:
        u_btc = sum((sr.disposed_btc for sr in unpriced_fees), Decimal("0"))
        para(
            f"ACHTUNG: Für {len(unpriced_fees)} dieser Gebühren über {_btc(u_btc)} lag "
            f"kein Tageskurs vor. Der Bestandsabgang ist erfasst, Veräußerungserlös und "
            f"Gewinn daraus sind NICHT ermittelt und in den Summen NICHT enthalten."
        )
        blank()
    if gifts_in_year:
        gift_btc = sum((sr.disposed_btc for sr in gifts_in_year), Decimal("0"))
        para(
            f"Ferner wurden {len(gifts_in_year)} unentgeltliche Übertragung(en) über "
            f"insgesamt {_btc(gift_btc)} (Schenkung/Spende) erfasst. Sie sind keine "
            f"Veräußerung im Sinne des § 23 EStG und in den Gewinnsummen nicht enthalten; "
            f"sie vermindern den Bestand (Einzelheiten unten)."
        )
        blank()

    # "Alle steuerfrei" nur behaupten, wenn wirklich JEDES Lot außerhalb der
    # Haltefrist lag — nicht wenn steuerbare Vorgänge sich zufällig auf 0 saldieren
    # und NICHT, wenn die veräußerte Menge nicht vollständig zugeordnet werden
    # konnte. Deckungstest, kein Leere-Test: läuft der FiFo-Pool MITTEN im Verkauf
    # leer, ist matches nicht leer, aber zu kurz — all() über die vorhandenen Lots
    # bescheinigt dann eine Haltedauer, die für die fehlende Menge nie berechnet
    # wurde (und all() über eine leere Liste ist ohnehin True).
    uncovered_sells = [sr for sr in sells_in_year if not sr.is_fully_covered]
    uncovered_btc: Decimal = sum((sr.unmatched_btc for sr in uncovered_sells), Decimal("0"))
    # Gebühren zählen mit: eine Gebühr aus einem jungen Lot ist eine steuerbare
    # Veräußerung, auch wenn alle "richtigen" Verkäufe steuerfrei waren.
    uncovered_fees = [sr for sr in fees_in_year if not sr.is_fully_covered]
    all_disposals = sells_in_year + fees_in_year
    all_matches_tax_free = (
        bool(all_disposals)
        and not uncovered_sells
        and not uncovered_fees
        and all(m.is_tax_free for sr in all_disposals for m in sr.matches)
    )

    if uncovered_sells:
        para(
            f"ACHTUNG: Bei {len(uncovered_sells)} Veräußerung(en) konnte die veräußerte "
            f"Menge nicht (vollständig) einem Anschaffungsgeschäft zugeordnet werden. "
            f"Ohne Zuordnung bleiben insgesamt {_btc(uncovered_btc)}. Haltedauer und "
            f"Steuerfreiheit sind für diese Menge NICHT nachgewiesen. Dieser Nachweis "
            f"ist insoweit unvollständig — bitte fehlende Anschaffungsdaten ergänzen."
        )
        blank()

    if not all_disposals:
        # Kein Verkauf und keine Gebühr im Jahr — die Aussage "alle steuerfrei"
        # wäre inhaltsleer, der Hinweis zur Anlage SO ist hier aber korrekt und nützlich.
        para(
            f"Im Steuerjahr {year} wurden keine Bitcoin-Veräußerungen getätigt. "
            f"Es liegt kein privates Veräußerungsgeschäft gemäß § 23 EStG vor."
        )
        blank()
        lines.append(f"  Steuerpflichtiger Gewinn {year}:    {_eur(total_taxable)}")
        lines.append(f"  Steuerfreier Gewinn {year}:         {_eur(total_free)}")
        lines.append(f"  In Anlage SO anzugeben:           NEIN (keine Veräußerung,")
        lines.append(f"                                    sofern keine weiteren privaten")
        lines.append(f"                                    Veräußerungsgeschäfte vorliegen)")
    elif all_matches_tax_free:
        para(
            f"ALLE Veräußerungen{' (einschließlich der Gebührenanteile)' if fees_in_year else ''} "
            f"sind gemäß § 23 Abs. 1 Satz 1 Nr. 2 EStG STEUERFREI, "
            f"da die veräußerten Bitcoin-Einheiten jeweils länger als ein Jahr gehalten "
            f"wurden (Haltedauer > 1 Jahr)."
        )
        blank()
        lines.append(f"  Steuerpflichtiger Gewinn {year}:    {_eur(total_taxable)}")
        lines.append(f"  Steuerfreier Gewinn {year}:         {_eur(total_free)}")
        lines.append(f"  In Anlage SO anzugeben:           NEIN (kein steuerpflichtiger Vorgang,")
        lines.append(f"                                    sofern keine weiteren privaten")
        lines.append(f"                                    Veräußerungsgeschäfte vorliegen)")
    else:
        lines.append(f"  Steuerpflichtiger Gewinn {year}:    {_eur(total_taxable)}")
        lines.append(f"  Steuerfreier Gewinn {year}:         {_eur(total_free)}")

    blank()

    # =========================================================
    # DETAILNACHWEIS JEDER VERÄUSSERUNG
    # =========================================================
    sep()
    lines.append("  DETAILNACHWEIS DER VERÄUSSERUNGEN")
    sep()

    for i, sr in enumerate(sells_in_year, 1):
        tx = sr.sell_tx
        blank()
        lines.append(f"  Veräußerung {i} von {len(sells_in_year)}")
        sep("-")
        lines.append(f"  Datum:              {tx.date.astimezone(_TZ_DE).strftime('%d.%m.%Y %H:%M Uhr')} (UTC: {tx.date.astimezone(timezone.utc).strftime('%d.%m.%Y %H:%M')})")
        lines.append(f"  Handelsplattform:   {tx.source.upper()}")
        lines.append(f"  Veräußerte Menge:   {_btc(tx.btc_amount)}")
        lines.append(f"  Veräußerungserlös:  {_eur(tx.eur_amount)}")
        lines.append(f"  Kurs zum Verkauf:   {_eur(tx.eur_price_per_btc)} / BTC")
        if tx.fee_eur > 0:
            lines.append(f"  Verkaufsgebühr:     {_eur(tx.fee_eur)}")
            lines.append(f"  Nettoerlös:         {_eur(tx.eur_amount - tx.fee_eur)}")
        blank()
        lines.append("  FiFo-Zuordnung (Anschaffungsgeschäfte):")
        lines.append(f"  {'Nr.':<4} {'Anschaffung':<12} {'Quelle':<14} {'Menge BTC':>14} {'Kurs EUR/BTC':>14} {'Tage*':>6} {'Status':<12}")
        lines.append(f"  {'─'*4} {'─'*12} {'─'*14} {'─'*14} {'─'*14} {'─'*6} {'─'*12}")

        for j, m in enumerate(sr.matches, 1):
            status = "STEUERFREI" if m.is_tax_free else f"PFLICHTIG"
            lines.append(
                f"  {j:<4} {de_date(m.lot_purchase_date).strftime('%d.%m.%Y'):<12} "
                f"{m.lot_source:<14} {m.btc_used:>14.8f} "
                f"{m.cost_per_btc:>14,.2f} {m.holding_days:>6} {status:<12}"
            )

        # Nicht zugeordnete Restmenge als eigene Zeile — sonst summiert sich die
        # Mengenspalte nicht auf die veräußerte Menge und die Lücke bliebe unsichtbar
        if sr.unmatched_btc > 0:
            lines.append(
                f"  {'—':<4} {'unbekannt':<12} {'NICHT ZUGEORD':<14} {sr.unmatched_btc:>14.8f} "
                f"{'—':>14} {'—':>6} {'UNGEKLÄRT':<12}"
            )

        blank()
        gain_total = sr.total_gain
        gain_tax_free = sr.total_gain_tax_free
        gain_taxable = sr.total_gain_taxable

        lines.append(f"  Gewinn gesamt:            {_eur(gain_total):>20}")
        lines.append(f"  davon steuerfrei (>1 Jahr): {_eur(gain_tax_free):>18}")
        lines.append(f"  davon steuerpflichtig:    {_eur(gain_taxable):>20}")

        # Nur behaupten, wenn wirklich jedes Lot außerhalb der Haltefrist lag —
        # nicht wenn ein steuerbarer Vorgang zufällig Gewinn 0,00 hat, und nicht
        # bei unvollständiger Zuordnung (all() über [] ist True, und über eine
        # zu kurze matches-Liste sagt es nichts über die fehlende Menge aus).
        if not sr.is_fully_covered:
            blank()
            if sr.matches:
                lines.append(f"  ACHTUNG: Für {_btc(sr.unmatched_btc)} dieser Veräußerung konnte KEIN")
                lines.append("           Anschaffungsgeschäft zugeordnet werden. Haltedauer und")
                lines.append("           Steuerfreiheit sind für diese Teilmenge NICHT nachgewiesen.")
                lines.append("           Die Veräußerung ist daher NICHT vollständig als steuerfrei")
                lines.append("           nachgewiesen.")
            else:
                lines.append("  ACHTUNG: Für diese Veräußerung konnte KEIN Anschaffungsgeschäft")
                lines.append("           zugeordnet werden. Haltedauer und Steuerfreiheit sind")
                lines.append("           NICHT nachgewiesen.")
        elif all(m.is_tax_free for m in sr.matches):
            blank()
            lines.append("  → Diese Veräußerung ist vollständig STEUERFREI.")
            lines.append("    Alle veräußerten Einheiten wurden vor mehr als einem Jahr erworben.")

        blank()
        sep("-")

    # =========================================================
    # GEBÜHREN IN BITCOIN (Veräußerung des Gebührenanteils, H8)
    # =========================================================
    if fees_in_year:
        blank()
        sep()
        lines.append("  VERÄUSSERUNGEN DURCH GEBÜHRENZAHLUNG IN BITCOIN")
        sep()
        blank()
        para(
            "Bei Überträgen zwischen eigenen Wallets sowie bei Auszahlungen vom "
            "Handelsplatz in die eigene Wallet wurden Netzwerk- bzw. Auszahlungsgebühren "
            "in Bitcoin entrichtet. Der übertragene Bestand selbst bleibt dabei "
            "steuerneutral (keine Veräußerung). Die Gebühr hingegen wird im Tausch für "
            "eine Dienstleistung hingegeben (Blockerstellung bzw. Auszahlung) und ist "
            "damit eine Veräußerung des Gebührenanteils; als Veräußerungserlös gilt der "
            "Marktkurs der hingegebenen Einheiten (BMF-Schreiben vom 06.03.2025, "
            "Rn. 33, 54, 60). Bewertet wurde zum Tagesschlusskurs BTC/EUR der "
            "Handelsplattform Bitstamp am jeweiligen Kalendertag (Rn. 43, 91). Die "
            "FiFo-Zuordnung folgt derselben Methode wie bei den Verkäufen."
        )
        blank()
        lines.append(f"  {'Datum':<12} {'Quelle':<14} {'Gebühr BTC':>12} {'Kurs EUR/BTC':>13} {'Anschaffung':<12} {'Einst./BTC':>11} {'Tage*':>6} {'Gewinn EUR':>11} {'Status':<10}")
        lines.append(f"  {'─'*12} {'─'*14} {'─'*12} {'─'*13} {'─'*12} {'─'*11} {'─'*6} {'─'*11} {'─'*10}")
        for sr in fees_in_year:
            tx = sr.sell_tx
            kurs = f"{_r(sr.price_per_btc):,.2f}" if sr.is_priced else "—"
            for m in sr.matches:
                if not sr.is_priced:
                    gewinn, status = "—", "OHNE KURS"
                else:
                    gewinn = f"{_r(m.gain_eur):+,.2f}"
                    status = "STEUERFREI" if m.is_tax_free else "PFLICHTIG"
                lines.append(
                    f"  {de_date(tx.date).strftime('%d.%m.%Y'):<12} {_src_label(tx.source):<14} "
                    f"{m.btc_used:>12.8f} {kurs:>13} {de_date(m.lot_purchase_date).strftime('%d.%m.%Y'):<12} "
                    f"{m.cost_per_btc:>11,.2f} {m.holding_days:>6} {gewinn:>11} {status:<10}"
                )
            if sr.unmatched_btc > 0:
                lines.append(
                    f"  {de_date(tx.date).strftime('%d.%m.%Y'):<12} {_src_label(tx.source):<14} "
                    f"{sr.unmatched_btc:>12.8f} {kurs:>13} {'unbekannt':<12} {'—':>11} {'—':>6} {'—':>11} {'UNGEKLÄRT':<10}"
                )
        blank()
        lines.append(f"  Gebühren gesamt:            {_btc(fee_btc_total):>20}")
        lines.append(f"  Veräußerungserlös gesamt:   {_eur(fee_proceeds):>20}")
        lines.append(f"  davon Gewinn steuerfrei:    {_eur(fee_free):>20}")
        lines.append(f"  davon Gewinn steuerpflichtig: {_eur(fee_taxable):>18}")
        if unpriced_fees:
            blank()
            lines.append("  ACHTUNG: Zeilen mit Status OHNE KURS sind im Bestand abgezogen, ihr")
            lines.append("           Veräußerungsgewinn ist NICHT ermittelt (kein Tageskurs verfügbar).")
        blank()
        sep("-")

    # =========================================================
    # UNENTGELTLICHE ÜBERTRAGUNGEN (Schenkung/Spende)
    # =========================================================
    if gifts_in_year:
        blank()
        sep()
        lines.append("  UNENTGELTLICHE ÜBERTRAGUNGEN (Schenkung / Spende)")
        sep()
        blank()
        para(
            "Die folgenden Übertragungen an Dritte erfolgten ohne Gegenleistung. Sie "
            "sind keine Veräußerung im Sinne des § 23 Abs. 1 Satz 1 Nr. 2 EStG, da es "
            "an einer entgeltlichen Übertragung fehlt (vgl. BMF-Schreiben vom 06.03.2025, "
            "Rn. 54), und lösen beim Übertragenden keinen Veräußerungsgewinn aus. Sie "
            "vermindern den Bestand. Für den Empfänger sind Anschaffungszeitpunkt und "
            "Anschaffungskosten des Übertragenden maßgeblich (§ 23 Abs. 1 Satz 3 EStG); "
            "beides ist deshalb je übertragener Einheit ausgewiesen. Der Wert zum "
            "Tageskurs ist eine nachrichtliche Angabe."
        )
        blank()
        lines.append(f"  {'Datum':<12} {'Quelle':<14} {'Menge BTC':>12} {'Anschaffung':<12} {'Einst./BTC':>11} {'Einstand':>10} {'Wert Tagesk.':>13}")
        lines.append(f"  {'─'*12} {'─'*14} {'─'*12} {'─'*12} {'─'*11} {'─'*10} {'─'*13}")
        g_btc = Decimal("0"); g_ak = Decimal("0")
        for sr in gifts_in_year:
            tx = sr.sell_tx
            price = btc_prices.price_for_date(de_date(tx.date))
            for m in sr.matches:
                ak = _r(m.cost_per_btc * m.btc_used)
                val = f"{_r(m.btc_used * price):,.2f}" if price is not None else "—"
                lines.append(
                    f"  {de_date(tx.date).strftime('%d.%m.%Y'):<12} {_src_label(tx.source):<14} "
                    f"{m.btc_used:>12.8f} {de_date(m.lot_purchase_date).strftime('%d.%m.%Y'):<12} "
                    f"{m.cost_per_btc:>11,.2f} {ak:>10,.2f} {val:>13}"
                )
                g_btc += m.btc_used; g_ak += ak
            if sr.unmatched_btc > 0:
                lines.append(
                    f"  {de_date(tx.date).strftime('%d.%m.%Y'):<12} {_src_label(tx.source):<14} "
                    f"{sr.unmatched_btc:>12.8f} {'unbekannt':<12} {'—':>11} {'—':>10} {'—':>13}  UNGEKLÄRT"
                )
                g_btc += sr.unmatched_btc
        blank()
        lines.append(f"  Übertragen gesamt:          {_btc(g_btc):>20}")
        lines.append(f"  Anschaffungskosten gesamt:  {_eur(g_ak):>20}")
        blank()
        sep("-")

    # =========================================================
    # ALLE KÄUFE IM BERICHTSJAHR (Vollständigkeitsnachweis)
    # =========================================================
    blank()
    sep()
    lines.append(f"  ANSCHAFFUNGEN {year} (nicht steuerpflichtig — zur Vollständigkeit)")
    sep()
    blank()
    para(
        f"Die folgenden Anschaffungen wurden im Jahr {year} getätigt. "
        f"Sie begründen neue Veräußerungsfristen und sind erst nach Ablauf eines Jahres "
        f"steuerfrei veräußerbar."
    )
    blank()
    lines.append(f"  {'Datum':<12} {'Plattform':<14} {'Menge BTC':>14} {'Kurs EUR/BTC':>14} {'Gebühr':>10} {'Einstand':>12}")
    lines.append(f"  {'─'*12} {'─'*14} {'─'*14} {'─'*14} {'─'*10} {'─'*12}")

    total_btc_bought: Decimal = Decimal("0")
    total_eur_spent: Decimal = Decimal("0")

    for tx in buys_in_year:
        einstand = _r(tx.eur_amount + tx.fee_eur)
        lines.append(
            f"  {de_date(tx.date).strftime('%d.%m.%Y'):<12} {tx.source:<14} "
            f"{tx.btc_amount:>14.8f} {_r(tx.eur_price_per_btc):>14,.2f} "
            f"{_r(tx.fee_eur):>10,.2f} {einstand:>12,.2f}"
        )
        total_btc_bought += tx.btc_amount
        total_eur_spent += einstand

    blank()
    lines.append(f"  {'SUMME':<28} {total_btc_bought:>14.8f} {'':>14} {'':>10} {_r(total_eur_spent):>12,.2f}")

    # =========================================================
    # METHODIK & DATENQUELLEN
    # =========================================================
    blank()
    sep()
    lines.append("  METHODIK UND DATENQUELLEN")
    sep()
    blank()
    lines.append("  Berechnungsmethode:")
    para(
        "    Die Berechnung erfolgt nach der FiFo-Methode (First In, First Out). "
        "Die zuerst erworbenen Bitcoin-Einheiten werden bei einer Veräußerung "
        "zuerst als veräußert betrachtet. Maßgeblich für die Veräußerungsfrist "
        "ist § 23 Abs. 1 Satz 1 Nr. 2 EStG: Gewinne aus der Veräußerung von "
        "Kryptowährungen sind steuerfrei, wenn zwischen Anschaffung und "
        "Veräußerung mehr als ein Jahr liegt."
    )
    blank()
    para(
        "    Die Jahresfrist wird nach §§ 187 Abs. 1, 188 Abs. 2 BGB berechnet: der "
        "Tag der Anschaffung zählt nicht mit, die Frist endet mit Ablauf des Tages "
        "des Folgejahres, der dem Anschaffungstag durch seine Zahl entspricht. "
        "Steuerfrei ist erst eine Veräußerung nach diesem Tag."
    )
    blank()
    para(
        "    * Die Spalte \"Tage\" in der FiFo-Zuordnung ist eine nachrichtliche "
        "Angabe zur Orientierung. Rechtlich maßgeblich ist der Kalendervergleich "
        "nach den vorgenannten Vorschriften, nicht eine Anzahl von Tagen."
    )
    blank()
    lines.append("  Gebühren in Bitcoin:")
    para(
        "    In Bitcoin entrichtete Netzwerk- und Auszahlungsgebühren werden als "
        "Veräußerung des Gebührenanteils behandelt (Tausch gegen eine Dienstleistung, "
        "BMF-Schreiben vom 06.03.2025, Rn. 33, 54, 60). Veräußerungserlös ist der "
        "Marktkurs der hingegebenen Einheiten; angesetzt wird einheitlich der "
        f"{btc_prices.SOURCE_LABEL} am Kalendertag der Transaktion (Rn. 43, 91). "
        "In Euro entrichtete Handelsgebühren sind Anschaffungsnebenkosten bzw. "
        "Werbungskosten der jeweiligen Transaktion (Rn. 59)."
    )
    blank()
    lines.append("  Unentgeltliche Übertragungen:")
    para(
        "    Übertragungen ohne Gegenleistung (Schenkung, Spende) sind keine "
        "Veräußerung (§ 23 Abs. 1 Satz 1 Nr. 2 EStG setzt eine entgeltliche "
        "Übertragung voraus). Die übertragenen Einheiten scheiden nach FiFo aus dem "
        "Bestand aus; ihre Anschaffungsdaten sind ausgewiesen (§ 23 Abs. 1 Satz 3 "
        "EStG). Die Einstufung erfolgt anhand der Notiz in der Wallet-Software "
        "(Stichwort Schenkung/Spende)."
    )
    blank()
    lines.append("  Datenquellen:")
    sources = set(t.source for t in kyc_transactions)
    bitbox_wallets = sorted(s.replace("bitbox:", "") for s in sources if s.startswith("bitbox:"))
    if bitbox_wallets:
        # Nur die ANZAHL, nie die Wallet-Namen: die Namen sind private Labels aus
        # der lokalen Dateiablage des Nutzers und haben in einem Dokument, das
        # unter Klarnamen ans Finanzamt geht, nichts zu suchen. Die Anzahl ist
        # die prüfbare Angabe; welche Wallets eingelesen wurden, steht im Log
        # bzw. in der Dateitabelle der GUI — dort, wo Vollständigkeit
        # tatsächlich kontrolliert wird (ein nie exportiertes Wallet kann
        # ohnehin in keinem erzeugten Dokument auftauchen).
        count = len(bitbox_wallets)
        lines.append(f"    - BitBox Hardware Wallet CSV-Exporte ({count} {'Wallet' if count == 1 else 'Wallets'})")
    _BROKER_DISPLAY = {
        "21bitcoin": "21bitcoin", "bison": "Bison", "swissquote": "Swissquote",
        "strike": "Strike", "pocket": "Pocket", "manual": "Manuell (P2P)",
    }
    for key, label in _BROKER_DISPLAY.items():
        if key in sources:
            lines.append(f"    - {label} Broker CSV-Export")
    blank()
    # Label bewusst neutral — das Dokument erwähnt nicht, was es nicht enthält
    lines.append("  Verarbeitete Transaktionen gesamt:")
    type_counts = {}
    for tx in kyc_transactions:
        type_counts[tx.type] = type_counts.get(tx.type, 0) + 1
    lines.append(f"    Käufe:              {type_counts.get(TxType.BUY, 0):>5}")
    lines.append(f"    Verkäufe:           {type_counts.get(TxType.SELL, 0):>5}")
    lines.append(f"    Überträge (eigene): {type_counts.get(TxType.TRANSFER_IN, 0) + type_counts.get(TxType.TRANSFER_OUT, 0):>5}")
    if type_counts.get(TxType.GIFT_OUT):
        lines.append(f"    Unentgeltl. Übertr.:{type_counts.get(TxType.GIFT_OUT, 0):>5}")
    lines.append(f"    Gesamt:             {len(kyc_transactions):>5}")
    blank()
    para(
        "Hinweis: Überträge zwischen eigenen Wallets und Konten (BitBox ↔ Broker) "
        "stellen hinsichtlich des übertragenen Bestands keine steuerpflichtigen "
        "Vorgänge dar und fließen insoweit nicht in die Gewinnberechnung ein. "
        "Lediglich eine dabei in Bitcoin entrichtete Gebühr wird als Veräußerung "
        "des Gebührenanteils erfasst (siehe oben). Die Überträge dienen im Übrigen "
        "der lückenlosen Dokumentation aller Bewegungen."
    )
    blank()
    sep()
    blank()

    # Datei schreiben
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
