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
from .tax_report import _freigrenze

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
) -> None:
    """Erzeugt einen formalen Steuernachweis als Textdatei."""

    # Jahres-Zuordnung nach deutschem Kalenderdatum (Europe/Berlin), nicht UTC
    sells_in_year = [
        sr for sr in sell_results
        if de_date(sr.sell_tx.date).year == year and not sr.sell_tx.no_kyc
    ]
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

    total_taxable: Decimal = sum((sr.total_gain_taxable for sr in sells_in_year), Decimal("0"))
    total_free: Decimal = sum((sr.total_gain_tax_free for sr in sells_in_year), Decimal("0"))
    total_proceeds: Decimal = sum((_r(sr.sell_tx.eur_amount) for sr in sells_in_year), Decimal("0"))

    para(
        f"Im Steuerjahr {year} wurden {len(sells_in_year)} Bitcoin-Veräußerung(en) "
        f"mit einem Gesamterlös von {_eur(total_proceeds)} durchgeführt."
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
    all_matches_tax_free = (
        bool(sells_in_year)
        and not uncovered_sells
        and all(m.is_tax_free for sr in sells_in_year for m in sr.matches)
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

    if not sells_in_year:
        # Kein Verkauf im Jahr — die Aussage "alle steuerfrei" wäre inhaltsleer,
        # der Hinweis zur Anlage SO ist hier aber korrekt und nützlich.
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
            f"ALLE Veräußerungen sind gemäß § 23 Abs. 1 Satz 1 Nr. 2 EStG STEUERFREI, "
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
    lines.append(f"    Gesamt:             {len(kyc_transactions):>5}")
    blank()
    para(
        "Hinweis: Überträge zwischen eigenen Wallets und Konten (BitBox ↔ Broker) "
        "stellen keine steuerpflichtigen Vorgänge dar und fließen nicht in die "
        "Gewinnberechnung ein. Sie dienen lediglich der lückenlosen Dokumentation "
        "aller Bewegungen."
    )
    blank()
    sep()
    blank()

    # Datei schreiben
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
