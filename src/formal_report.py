"""
Formaler Steuernachweis für Steuerberater und Finanzamt.
Erzeugt ein selbsterklärendes Dokument das ohne Kenntnis des Tools lesbar ist.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .models import Transaction, TxType, SellResult, Lot
from .tax_report import _freigrenze

CENT = Decimal("0.01")


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
) -> None:
    """Erzeugt einen formalen Steuernachweis als Textdatei."""

    sells_in_year = [
        sr for sr in sell_results
        if sr.sell_tx.date.year == year and not sr.sell_tx.no_kyc
    ]
    buys_in_year = sorted(
        [t for t in all_transactions if t.type == TxType.BUY and t.date.year == year and not t.no_kyc],
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
    lines.append(f"  Erstellt am:        {date.today().strftime('%d.%m.%Y')}")
    lines.append(f"  Berechnungsmethode: First In, First Out (FiFo)")
    lines.append(f"  Haltefrist:         365 Tage (§ 23 Abs. 1 Satz 1 Nr. 2 EStG)")
    lines.append(f"  Freigrenze {year}:    {_eur(_freigrenze(year))}")
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

    if total_taxable == Decimal("0"):
        para(
            f"ALLE Veräußerungen sind gemäß § 23 Abs. 1 Satz 1 Nr. 2 EStG STEUERFREI, "
            f"da die veräußerten Bitcoin-Einheiten jeweils länger als 365 Tage gehalten "
            f"wurden (Haltedauer > 1 Jahr)."
        )
        blank()
        lines.append(f"  Steuerpflichtiger Gewinn {year}:    {_eur(total_taxable)}")
        lines.append(f"  Steuerfreier Gewinn {year}:         {_eur(total_free)}")
        lines.append(f"  In Anlage SO anzugeben:           NEIN (kein steuerpflichtiger Vorgang)")
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
        lines.append(f"  Datum:              {tx.date.astimezone().strftime('%d.%m.%Y %H:%M Uhr')} (UTC: {tx.date.strftime('%d.%m.%Y %H:%M')})")
        lines.append(f"  Handelsplattform:   {tx.source.upper()}")
        lines.append(f"  Veräußerte Menge:   {_btc(tx.btc_amount)}")
        lines.append(f"  Veräußerungserlös:  {_eur(tx.eur_amount)}")
        lines.append(f"  Kurs zum Verkauf:   {_eur(tx.eur_price_per_btc)} / BTC")
        if tx.fee_eur > 0:
            lines.append(f"  Verkaufsgebühr:     {_eur(tx.fee_eur)}")
            lines.append(f"  Nettoerlös:         {_eur(tx.eur_amount - tx.fee_eur)}")
        blank()
        lines.append("  FiFo-Zuordnung (Anschaffungsgeschäfte):")
        lines.append(f"  {'Nr.':<4} {'Anschaffung':<12} {'Quelle':<14} {'Menge BTC':>14} {'Kurs EUR/BTC':>14} {'Tage':>6} {'Status':<12}")
        lines.append(f"  {'─'*4} {'─'*12} {'─'*14} {'─'*14} {'─'*14} {'─'*6} {'─'*12}")

        for j, m in enumerate(sr.matches, 1):
            status = "STEUERFREI" if m.is_tax_free else f"PFLICHTIG"
            lines.append(
                f"  {j:<4} {m.lot_purchase_date.strftime('%d.%m.%Y'):<12} "
                f"{m.lot_source:<14} {m.btc_used:>14.8f} "
                f"{m.cost_per_btc:>14,.2f} {m.holding_days:>6} {status:<12}"
            )

        blank()
        gain_total = sr.total_gain
        gain_tax_free = sr.total_gain_tax_free
        gain_taxable = sr.total_gain_taxable

        lines.append(f"  Gewinn gesamt:            {_eur(gain_total):>20}")
        lines.append(f"  davon steuerfrei (>365d): {_eur(gain_tax_free):>20}")
        lines.append(f"  davon steuerpflichtig:    {_eur(gain_taxable):>20}")

        if gain_taxable == Decimal("0"):
            blank()
            lines.append("  → Diese Veräußerung ist vollständig STEUERFREI.")
            lines.append("    Alle veräußerten Einheiten wurden vor mehr als 365 Tagen erworben.")

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
        f"Sie begründen neue Haltefristen und sind erst nach Ablauf von 365 Tagen "
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
            f"  {tx.date.strftime('%d.%m.%Y'):<12} {tx.source:<14} "
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
        "zuerst als veräußert betrachtet. Maßgeblich für die Haltefrist ist "
        "§ 23 Abs. 1 Satz 1 Nr. 2 EStG: Gewinne aus der Veräußerung von "
        "Kryptowährungen sind steuerfrei, wenn zwischen Anschaffung und "
        "Veräußerung mehr als ein Jahr liegt."
    )
    blank()
    lines.append("  Datenquellen:")
    sources = set(t.source for t in kyc_transactions)
    bitbox_wallets = sorted(s.replace("bitbox:", "") for s in sources if s.startswith("bitbox:"))
    if bitbox_wallets:
        count = len(bitbox_wallets)
        names = ", ".join(bitbox_wallets)
        lines.append(f"    - BitBox Hardware Wallet CSV-Exporte ({count} {'Wallet' if count == 1 else 'Wallets'}: {names})")
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
