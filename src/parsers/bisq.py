"""Parser für Bisq-CSV-Exporte (Bisq Classic, deutsche oder englische Oberfläche).

Export: Portfolio → Verlauf → „Als CSV exportieren" (DE) bzw. Portfolio → History →
„Export to CSV" (EN). Bisq speichert als `tradeHistory.csv`. Die Spaltenköpfe und die
Werte in „Angebotstyp"/„Status" kommen aus Bisqs Sprachdatei, also je Oberflächensprache
anders; Zahlen formatiert Bisq sprachunabhängig (bitcoinj `MonetaryFormat`, Punkt als
Dezimaltrenner, keine Tausendergruppierung).

Format (DE / EN, Quelle: Bisq `ClosedTradesView.ColumnNames` + `displayStrings*.properties`):
    Handels-ID,Datum/Zeit,Markt,Preis,Abweichung,Betrag in BTC,Betrag,Währung,
    Transaktionsgebühr,Handelsgebühr BTC,Handelsgebühr BSQ,Käufer-Kaution,
    Verkäufer-Kaution,Angebotstyp,Status
    Trade ID,Date/Time,Market,Price,Deviation,Amount in BTC,Amount,Currency,
    Transaction Fee,Trade Fee BTC,Trade Fee BSQ,Buyer Deposit,Seller Deposit,
    Offer type,Status

Relevante Zeilen:
    Angebotstyp "BTC kaufen" / "Buy BTC" + Status "Abgeschlossen" / "Completed"
    → BUY, no_kyc=True. Andere Sprachen der Bisq-Oberfläche werden nicht gelesen
    (Warnung, nie stilles Verwerfen).

Gebühren:
    Transaktionsgebühr (BTC On-Chain-Fee) + Handelsgebühr BTC werden in EUR
    umgerechnet (Preis * Gebühr_BTC) und gehen als Anschaffungsnebenkosten in
    den Einstand ein (BMF 06.03.2025 Rn. 59). Zusätzlich reicht der Parser die
    Gebühr als fee_btc durch: die Sats sind aus dem Bestand abgeflossen, die
    Engine bucht dafür einen Gebühren-Abgang aus dem noKYC-Pool (H8).
    Handelsgebühr BSQ wird ignoriert.
    Sicherheitskautionen (Kaution) sind keine Gebühren — werden zurückgegeben.

Timestamps:
    Bisq exportiert lokale Systemzeit ohne Timezone-Angabe (`DateFormat.DEFAULT`
    der Bisq-Locale = Oberflächensprache + Land). Wird als Europe/Berlin behandelt —
    maßgeblich für Steuerjahr und Haltefrist ist das deutsche Kalenderdatum.
    Deutsch immer `15.03.2024 14:22:10`. Englisch je Land verschieden
    (`15 Mar 2024 14:22:10` bei Land DE/AT/CH/GB, `Mar 15, 2024 2:22:10 PM` bei US,
    `15-Mar-2024`, `15/03/2024`, „Sept", „pm", „p.m.", schmales Leerzeichen vor AM/PM
    ab Java 20) — der englische Datumsparser nimmt alle diese Varianten.

Altcoin-Märkte (XMR/BTC, BSQ/BTC …):
    „XMR kaufen" / „Buy XMR" heißt: BTC gegen XMR hergegeben = Veräußerung von BTC.
    „XMR verkaufen" / „Sell XMR" heißt: BTC erhalten = Anschaffung gegen Altcoin.
    Beides steuerlich relevant, beides kann der Parser nicht bewerten (kein EUR-Preis)
    → laute Warnung mit Handlungsanweisung, kein stilles Mitzählen.
"""
from __future__ import annotations
import csv
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, TZ_DE
from . import warn, parser_warnings

# Spaltenköpfe und feste Werte je Oberflächensprache. Quelle: Bisq-Quellcode
# (`desktop/.../closedtrades/ClosedTradesView.java`, `core/.../i18n/displayStrings.properties`
# bzw. `displayStrings_de.properties`, Stand 10/2026). "{0}" steht für den Währungscode:
# auf Fiat-Märkten BTC („BTC kaufen"), auf Altcoin-Märkten der Altcoin („XMR kaufen").
LANGUAGES: dict[str, dict[str, str]] = {
    "de": {
        "trade_id": "Handels-ID", "date": "Datum/Zeit", "market": "Markt", "price": "Preis",
        "amount_btc": "Betrag in BTC", "volume": "Betrag", "currency": "Währung",
        "tx_fee": "Transaktionsgebühr", "trade_fee_btc": "Handelsgebühr BTC",
        "offer_type": "Angebotstyp", "status": "Status",
        "completed": "Abgeschlossen", "buy": "{0} kaufen", "sell": "{0} verkaufen",
    },
    "en": {
        "trade_id": "Trade ID", "date": "Date/Time", "market": "Market", "price": "Price",
        "amount_btc": "Amount in BTC", "volume": "Amount", "currency": "Currency",
        "tx_fee": "Transaction Fee", "trade_fee_btc": "Trade Fee BTC",
        "offer_type": "Offer type", "status": "Status",
        "completed": "Completed", "buy": "Buy {0}", "sell": "Sell {0}",
    },
}
_COLUMNS = ("trade_id", "date", "market", "price", "amount_btc", "volume", "currency",
            "tx_fee", "trade_fee_btc", "offer_type", "status")


def detect_language(fieldnames: list[str] | None) -> str | None:
    """Sprache des Exports anhand der Kopfzeile; None, wenn keine bekannte passt.

    Verlangt alle gelesenen Spalten, nicht nur die erste — eine Kopfzeile, die nur mit
    „Trade ID" beginnt, kann von einer anderen Plattform stammen.
    """
    if not fieldnames:
        return None
    present = {f.strip().lstrip("﻿") for f in fieldnames if f}
    for lang, names in LANGUAGES.items():
        if all(names[c] in present for c in _COLUMNS):
            return lang
    return None


def parse(filepath: Path) -> list[Transaction]:
    transactions = []
    rows_seen = 0
    skipped: dict[tuple[str, int | None], int] = {}
    warned = 0  # Zeilen, die bereits eine eigene Warnung bekommen haben
    # utf-8-sig: Bisq schreibt UTF-8 ohne BOM, aber eine in Excel/LibreOffice erneut
    # gespeicherte Datei bekommt eine. Mit "utf-8" hieße die erste Spalte dann
    # "﻿Handels-ID", keine Zeile würde erkannt — und die Datei wäre still weg.
    with open(filepath, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        lang = detect_language(reader.fieldnames)
        if lang is None:
            header = ",".join(h.strip() for h in (reader.fieldnames or []))[:120]
            warn(
                f"{filepath.name}: Kopfzeile nicht als Bisq-Export erkannt (Deutsch oder Englisch). "
                f"Bisq-Oberfläche auf Deutsch oder Englisch stellen und neu exportieren. "
                f"Gelesene Kopfzeile: {header}",
                internal=True,
            )
            return []
        names = LANGUAGES[lang]
        # Kopfzeile ggf. mit Leerraum oder BOM → auf die bekannten Namen abbilden
        key_of = {names[c]: c for c in _COLUMNS}
        for raw_row in reader:
            rows_seen += 1
            row = {key_of[k.strip().lstrip("﻿")]: (v or "")
                   for k, v in raw_row.items()
                   if k is not None and k.strip().lstrip("﻿") in key_of}
            before = len(parser_warnings)
            tx = _parse_row(row, names, lang, filepath.name, skipped)
            if tx is not None:
                transactions.append(tx)
            warned += len(parser_warnings) - before
    for (reason, year), count in sorted(skipped.items(), key=lambda kv: (kv[0][1] or 0, kv[0][0])):
        # Jahr mitfuehren, sonst taucht eine abgebrochene Zeile aus 2021 im
        # 2024er-Report auf und erzeugt dort einen internen Report (SA2-09)
        warn(f"{filepath.name}: {count} Zeile(n) {reason}", internal=True, year=year)
    if rows_seen and not transactions and not skipped and not warned:
        # Jede Zeile hat bereits eine eigene Warnung oder einen Zähler bekommen —
        # dann keine zweite Sammelmeldung obendrauf.
        warn(
            f"{filepath.name}: keine Bisq-Transaktion erkannt ({rows_seen} Zeilen, Export in "
            f"Sprache '{lang}') — bitte prüfen, ob die Datei abgeschlossene BTC-Käufe enthält.",
            internal=True,
        )
    return transactions


# ───────────────────────── Datum ─────────────────────────

_MONTHS_EN = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
# NBSP (U+00A0) und NNBSP (U+202F): Java ab Version 20 (CLDR 42) setzt in en_US ein
# schmales geschütztes Leerzeichen vor AM/PM — Bisq läuft auf Java 21.
_WS = re.compile(r"[\s  ]+")
_TIME_TAIL = re.compile(r"^(.*?)[\s,]+(\d{1,2}):(\d{2}):(\d{2})(?:\s*([ap])\.?m\.?)?$", re.IGNORECASE)
_DATE_SPLIT = re.compile(r"[\s,/.\-]+")


def parse_datetime_en(raw: str) -> datetime:
    """Bisq-Zeitstempel eines englischen Exports → Europe/Berlin.

    Java `DateFormat.DEFAULT` (Datum + " " + Zeit) für die englischen Länder-Locales
    (CLDR, Java 21). Belegte Formen:
      en_GB, en_DE, en_AT, en_CH, en_IE, en_ZA:  15 Mar 2024 14:22:10   (September: „Sept")
      en_US, en_PH:                              Mar 15, 2024 2:22:10 PM (NNBSP vor PM)
      en_CA:                                     Mar 15, 2024 2:22:10 p.m.
      en_AU, en_SG:                              15 Mar 2024 2:22:10 pm
      en_IN:                                     15-Mar-2024 2:22:10 pm
      en_NZ:                                     15/03/2024 2:22:10 pm
    Rein numerische englische Formen sind Tag-zuerst; Monat-zuerst gibt es in den
    mittleren Formaten nur mit Monatsnamen.
    """
    text = _WS.sub(" ", raw.strip())
    m = _TIME_TAIL.match(text)
    if not m:
        raise ValueError(f"Datum/Zeit '{raw}' nicht lesbar")
    date_part, hh, mm, ss, ampm = m.groups()
    tokens = [t for t in _DATE_SPLIT.split(date_part) if t]
    if len(tokens) != 3:
        raise ValueError(f"Datum/Zeit '{raw}' nicht lesbar")
    a, b, c = tokens
    if a.isalpha():
        month, day, year = _month_en(a, raw), int(b), int(c)
    elif b.isalpha():
        day, month, year = int(a), _month_en(b, raw), int(c)
    else:
        day, month, year = int(a), int(b), int(c)
    if year < 1000:
        raise ValueError(f"Datum/Zeit '{raw}': Jahr muss vierstellig sein")
    hour = int(hh)
    if ampm:
        if not 1 <= hour <= 12:
            raise ValueError(f"Datum/Zeit '{raw}': Stunde {hour} passt nicht zu AM/PM")
        hour = hour % 12 + (12 if ampm.lower() == "p" else 0)
    try:
        return datetime(year, month, day, hour, int(mm), int(ss), tzinfo=TZ_DE)
    except ValueError as e:
        raise ValueError(f"Datum/Zeit '{raw}' ungültig: {e}") from None


def _month_en(token: str, raw: str) -> int:
    try:
        return _MONTHS_EN[token.lower()]
    except KeyError:
        raise ValueError(f"Datum/Zeit '{raw}': unbekannter Monat '{token}'") from None


def parse_datetime_de(raw: str) -> datetime:
    """Deutscher Export: `DateFormat.DEFAULT` für de_* ist immer `dd.MM.yyyy HH:mm:ss`."""
    return datetime.strptime(raw.strip(), "%d.%m.%Y %H:%M:%S").replace(tzinfo=TZ_DE)


_DATE_PARSERS = {"de": parse_datetime_de, "en": parse_datetime_en}


def _row_year(row: dict, lang: str) -> int | None:
    """Steuerjahr einer Bisq-Zeile, tolerant — nur fuer die Jahres-Zuordnung
    von Warnungen. Bisq stempelt lokale Zeit, die als Europe/Berlin gilt."""
    try:
        return _DATE_PARSERS[lang](row.get("date", "")).year
    except (ValueError, TypeError):
        return None


# ───────────────────────── Zeilen ─────────────────────────

def _parse_row(row: dict, names: dict[str, str], lang: str, filename: str,
               skipped: dict) -> Transaction | None:
    status = row.get("status", "").strip()
    if status != names["completed"]:
        # Nicht abgeschlossene Trades sind steuerlich irrelevant — aber mitzählen,
        # sonst greift der Sammel-Fallback bei teilweisem Verlust nicht.
        key = (f"mit Status '{status}' übersprungen", _row_year(row, lang))
        skipped[key] = skipped.get(key, 0) + 1
        return None

    offer_type = row.get("offer_type", "").strip()
    market = row.get("market", "").strip().upper()
    date_label = row.get("date", "?")
    trade_id = row.get("trade_id", "").strip()

    # Altcoin-Markt: Bisq schreibt „XMR/BTC" (Fiat: „BTC/EUR"); die Richtung im Angebotstyp
    # bezieht sich dann auf den Altcoin, nicht auf BTC.
    if market and not market.startswith("BTC/"):
        alt = market.split("/")[0]
        if offer_type == names["buy"].format(alt):
            warn(
                f"{filename}: Bisq-Trade {trade_id} am {date_label} — Kauf von {alt} gegen BTC ist eine "
                f"VERÄUSSERUNG von BTC und wird vom Parser nicht bewertet. Bitte als manual_sales.csv "
                f"(no_kyc=ja) mit dem EUR-Wert der hingegebenen BTC zum Handelstag erfassen.",
                internal=True, year=_row_year(row, lang),
            )
        elif offer_type == names["sell"].format(alt):
            warn(
                f"{filename}: Bisq-Trade {trade_id} am {date_label} — Verkauf von {alt} gegen BTC ist eine "
                f"ANSCHAFFUNG von BTC und wird vom Parser nicht bewertet. Bitte als manual_buys.csv "
                f"mit dem EUR-Wert der hingegebenen {alt} zum Handelstag erfassen.",
                internal=True, year=_row_year(row, lang),
            )
        else:
            key = (f"mit Angebotstyp '{offer_type}' auf Markt '{market}' nicht verarbeitet", _row_year(row, lang))
            skipped[key] = skipped.get(key, 0) + 1
        return None

    if offer_type != names["buy"].format("BTC"):
        # Nicht stillschweigend verwerfen — ein Verkauf wäre steuerlich relevant!
        if offer_type == names["sell"].format("BTC"):
            warn(
                f"{filename}: Bisq-Verkauf am {date_label} wird vom Parser "
                f"noch nicht unterstützt — bitte als manual_sales.csv (no_kyc=ja) erfassen, "
                f"sonst ist die noKYC-Übersicht unvollständig.",
                internal=True, year=_row_year(row, lang),
            )
        else:
            key = (f"mit Angebotstyp '{offer_type}' nicht verarbeitet", _row_year(row, lang))
            skipped[key] = skipped.get(key, 0) + 1
        return None

    try:
        date = _DATE_PARSERS[lang](row.get("date", ""))
    except ValueError as e:
        raise ValueError(
            f"{filename}: Bisq-Trade {trade_id}: {e}. Erwartet wird der Zeitstempel des "
            f"Bisq-Exports ({'deutsch, z.B. 15.03.2024 14:22:10' if lang == 'de' else 'englisch, z.B. 15 Mar 2024 14:22:10 oder Mar 15, 2024 2:22:10 PM'})."
        ) from None

    currency = row.get("currency", "").strip().upper()
    if currency and currency != "EUR":
        warn(
            f"{filename}: Bisq-Trade {trade_id} in {currency} statt EUR — nicht verarbeitet. "
            f"Bitte als manual_buys.csv mit EUR-Umrechnung zum Kaufdatum erfassen.",
            internal=True, year=date.year,
        )
        return None

    btc_amount = _decimal(row.get("amount_btc", "0"))
    eur_amount = _decimal(row.get("volume", "0"))
    eur_price_per_btc = _decimal(row.get("price", "0"))

    # Gebühren in BTC → EUR umrechnen (Kautionen sind keine Gebühren)
    fee_btc = _decimal(row.get("tx_fee", "0")) + _decimal(row.get("trade_fee_btc", "0"))
    fee_eur = _round(fee_btc * eur_price_per_btc) if eur_price_per_btc else Decimal("0")

    return Transaction(
        date=date,
        type=TxType.BUY,
        btc_amount=btc_amount,
        eur_amount=eur_amount,
        eur_price_per_btc=eur_price_per_btc,
        fee_eur=fee_eur,
        fee_btc=fee_btc,
        source="bisq",
        tx_id=trade_id,
        note="Bisq P2P Kauf",
        no_kyc=True,
        direct=True,  # Bisq-Kauf landet in der eigenen Wallet (keine Auszahlungszeile im Export)
    )


def _decimal(value: str) -> Decimal:
    val = value.strip().replace(",", ".")
    return Decimal(val) if val else Decimal("0")


def _round(val: Decimal) -> Decimal:
    from decimal import ROUND_HALF_UP
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
