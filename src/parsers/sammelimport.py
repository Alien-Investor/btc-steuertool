"""Sammelimport: Exporte aus CoinTracking und Blockpit (viele Börsen in einer Datei).

Wer seine Börsen schon in CoinTracking oder Blockpit pflegt, exportiert dort EINE
Datei mit allen Konten. Jedes Konto (Spalte „Exchange" bzw. „Source Name") wird eine
eigene Wallet im walletbezogenen FiFo (BMF 06.03.2025 Rn. 61 f.); Ein-/Auszahlungen
werden wie bei jedem Broker mit den BitBox-Exporten verbunden (TX-ID, sonst Betrag/Zeit).

**Status: aus der Dokumentation und veröffentlichten Beispieldateien abgeleitet, noch
nicht an einem echten Export eines Nutzers bestätigt.** Jede Datei erzeugt deshalb eine
sichtbare Warnung im Report („Format noch nicht bestätigt, Ergebnis prüfen"). Grundsatz:
lieber laut melden als still rechnen.

Erkannte Kopfzeilen (Erkennung am Inhalt, Dateiname egal):
  CT_IMPORT  CoinTracking-Importformat (viele Börsen bieten es als Export an):
             "Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency",
             "Exchange","Trade-Group","Comment","Date"[,"Liquidity pool (optional)","Tx-ID (optional)",
             "Buy Value in Account Currency (optional)","Sell Value in Account Currency (optional)"]
             Quelle: cointracking.info/import/import_csv/
  CT_EXPORT  CoinTracking „Trade List"/„Enter Coins" → Export CSV:
             "Type","Buy","Cur.","Sell","Cur.","Fee","Cur.","Exchange","Group","Comment","Date"
             (leere Beträge als „-"; Quelle: veröffentlichte Beispieldatei, rotki-Testdaten)
  CT_FULL    CoinTracking Trade List, Vollansicht:
             Type,Buy,Cur.,Value in BTC,Value in EUR,Sell,Cur.,Value in BTC,Value in EUR,Spread,Exchange,Group,Date
             (Quelle: Formatwissen aus BittyTax; Kontowährung kann statt EUR auch USD/CHF sein)
  BP_NEW     Blockpit „Transaktionen → CSV exportieren" (Hilfecenter 2025):
             Date (UTC),Integration Name,Label,Outgoing Asset,Outgoing Amount,Incoming Asset,Incoming Amount,
             Fee Asset,Fee Amount,Trx. ID,Comments,Source Type,Source Name
             (auch die Excel-Vorlage mit „… (optional)"-Spalten)
  BP_OLD     Blockpit-Export bis ca. 2023 (Semikolon):
             Blockpit ID;Timestamp;Source Type;Source Name;Integration;Transaction Type;Outgoing Asset;
             Outgoing Amount;Incoming Asset;Incoming Amount;Fee Asset;Fee Amount;Transaction ID;Note;Merge ID
             (Quelle: veröffentlichte Beispieldatei, rotki-Testdaten)

Zeit: CoinTracking schreibt die Zeit der Kontoeinstellung ohne Zeitzone → als Europe/Berlin
gelesen (deutsche Nutzer). Blockpit „Date (UTC)"/„Timestamp" → UTC. ISO-Zeiten mit Offset
werden so übernommen. Formen mit Schrägstrich (5/9/2017) sind mehrdeutig → harter Fehler.

Abbildung auf das Transaktionsmodell (nur BTC; Zeilen ohne BTC-Bezug werden übersprungen):
  Trade  BTC←Fiat (EUR/USD/CHF)   BUY   Gebühr in Fiat → fee_eur; in BTC → fee_btc (+ Einstand, wie Bisq)
  Trade  Fiat←BTC                 SELL  Erlös = Fiat vor Gebühr, Gebühr in Fiat → fee_eur, in BTC → fee_btc
  Trade  BTC↔Krypto (auch USDT)   nur mit EUR-Wert der BTC-Seite (CT_FULL „Value in EUR"), sonst Warnung
  Deposit BTC                     TRANSFER_IN  (Gebühr in BTC → fee_btc)
  Withdrawal BTC                  TRANSFER_OUT (Betrag OHNE Gebühr, Gebühr in BTC → fee_btc — Annahme!)
  Fee / Other Fee (BTC)           Gebührenabgang (Menge 0, fee_btc)
  Income/Mining/Staking/Airdrop/  mit EUR-Wert → BUY („Zufluss, Wert laut Export"), sonst Warnung;
  Reward/Lending …                die steuerliche Einordnung des Zuflusses (Einkünfte) prüft der Nutzer
  Spend/Payment (BTC)             mit EUR-Wert → SELL, sonst Warnung (Bezahlung = Veräußerung zum Marktwert)
  Gift(out)/Donation (BTC)        GIFT_OUT
  Gift(in)/Gift/Tip (BTC)         Warnung: Anschaffungsdaten des Schenkers gelten (§ 23 Abs. 1 S. 3 EStG)
  Lost/Stolen/Margin … (BTC)      Warnung, nicht verarbeitet (Bestand bleibt rechnerisch bestehen)

noKYC: Konten, deren Name eine noKYC-Plattform nennt (Bisq, RoboSats, Hodl Hodl, Peach,
AgoraDesk), oder eine Datei mit „nokyc" im Namen → no_kyc=True (nur interner Report).
Der Kontoname erscheint als „Quelle" in den Reports — in CoinTracking/Blockpit vergebene
Namen also neutral halten.
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from ..models import Transaction, TxType, TZ_DE, de_date
from ..fx_rates import eur_rate_for_date
from . import (warn_both, warn_fmt, FileRef, read_rows, parse_amount, parse_iso_datetime, LINE_KEY,
               _sanitize, aggregate_sources)

LABEL = "Sammelimport"
FIAT = ("EUR", "USD", "CHF")                      # umrechenbar (EZB-Tabelle)
OTHER_FIAT = ("GBP", "JPY", "CAD", "AUD", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "NZD", "SGD", "HKD")
NOKYC_NAMES = ("bisq", "robosats", "hodlhodl", "hodl hodl", "peach", "agoradesk", "lnp2pbot")

# Formate: Name → (Pflichtspalten, Herkunftstext für den Nachweis)
FORMATS = {
    "CT_IMPORT": (("Type", "Buy Amount", "Buy Currency", "Sell Amount", "Sell Currency", "Fee",
                   "Fee Currency", "Exchange", "Date"), "CoinTracking-Importformat"),
    "CT_FULL":   (("Type", "Buy", "Cur.", "Value in BTC", "Sell", "Cur.#2", "Value in BTC#2", "Exchange", "Date"),
                  "CoinTracking-Export (Vollansicht)"),
    "CT_EXPORT": (("Type", "Buy", "Cur.", "Sell", "Cur.#2", "Fee", "Cur.#3", "Exchange", "Date"),
                  "CoinTracking-Export"),
    "BP_NEW":    (("Date (UTC)", "Label", "Outgoing Asset", "Outgoing Amount", "Incoming Asset", "Incoming Amount"),
                  "Blockpit-Export"),
    "BP_OLD":    (("Timestamp", "Transaction Type", "Outgoing Asset", "Outgoing Amount", "Incoming Asset",
                   "Incoming Amount", "Fee Asset", "Fee Amount"), "Blockpit-Export"),
}

_CT_INCOME = {"income", "mining", "reward/bonus", "reward / bonus", "airdrop", "staking",
              "masternode", "lending income", "interest income", "margin profit", "derivatives / futures profit",
              "income (non taxable)", "other income", "dividends income", "bounties", "lending", "interest",
              "reward", "cashback"}
_CT_SPEND = {"spend", "payment", "expense (non taxable)", "other expense"}
_CT_GIFT_OUT = {"gift", "donation", "spende", "schenkung"}
_CT_FEE = {"fee", "other fee"}
_CT_LOST = {"stolen", "lost", "margin loss", "margin fee", "derivatives / futures loss", "borrowing fee",
            "settlement fee", "margin_trading_loss", "margin_trading_fee", "withholdingtax", "withholding tax",
            "autobalancing"}


def detect_format(header: list[str]) -> str | None:
    present = set(header)
    for fmt, (required, _) in FORMATS.items():
        if all(c in present for c in required):
            return fmt
    return None


def _delimiter(filepath: Path) -> str:
    first = filepath.read_bytes().split(b"\n", 1)[0]
    return ";" if first.count(b";") > first.count(b",") else ","


def parse(filepath: Path) -> list[Transaction]:
    filename = filepath.name
    rows, header = read_rows(filepath, label=LABEL, delimiter=_delimiter(filepath))
    fmt = detect_format(header)
    if fmt is None:
        raise ValueError(
            f"{LABEL} {filename}: Kopfzeile ist weder ein CoinTracking- noch ein Blockpit-Export. "
            f"Gelesen: {', '.join(header[:16])}"
        )
    file_nokyc = "nokyc" in filename.lower()
    origin = FORMATS[fmt][1]

    transactions: list[Transaction] = []
    skipped_no_btc = 0
    for row in rows:
        rec = _normalize(row, fmt, filename)
        if rec is None:
            skipped_no_btc += 1
            continue
        rec["no_kyc"] = file_nokyc or any(n in rec["account"].lower() for n in NOKYC_NAMES)
        tx = _to_transaction(rec, filename)
        if tx is not None:
            if not tx.no_kyc:
                aggregate_sources.setdefault(tx.source, origin)
            transactions.append(tx)

    if transactions:
        # Sichtbar im Steuerreport (internal=False): das Format ist aus der Dokumentation
        # abgeleitet, nicht an einem echten Export bestätigt. Der Dateiname kann ein
        # privates Label sein → im offiziellen Kanal redigiert.
        warn_fmt(
            "{file} ({origin}): Format aus der Dokumentation abgeleitet, noch nicht an einem echten Export "
            "bestätigt — Ergebnis bitte prüfen (Beträge, Gebühren, Zeitzone) und Abweichungen melden.",
            internal=all(t.no_kyc for t in transactions), file=FileRef(filename, "eine Sammelimport-Datei"),
            origin=origin,
        )
    return transactions


# ───────────────────────── Normalisierung je Format ─────────────────────────

def _num(row: dict, field: str, filename: str) -> Decimal:
    return parse_amount(row.get(field), label=LABEL, filename=filename, line=row.get(LINE_KEY, "?"), field=field)


def _account(name: str, fallback: str) -> str:
    text = _sanitize(name or "").strip()
    if not text or text.lower() in ("no exchange", "-"):
        text = fallback
    from . import seen_names
    seen_names.add(text[:24].strip())    # für die Diagnose-Schwärzung, auch bei Abbruch (R5-B1)
    seen_names.add(_sanitize(name or "").strip())
    return text[:24].strip()


def _normalize(row: dict, fmt: str, filename: str) -> dict | None:
    """Zeile → gemeinsames Schema. None, wenn weder Haupt- noch Gebührenseite BTC betrifft."""
    line = row[LINE_KEY]
    eur_in = eur_out = None
    tx_id = ""
    comment = ""
    if fmt == "CT_IMPORT":
        kind_raw = row["Type"]
        in_asset, in_amt = row["Buy Currency"].upper(), _num(row, "Buy Amount", filename)
        out_asset, out_amt = row["Sell Currency"].upper(), _num(row, "Sell Amount", filename)
        fee_asset, fee_amt = row["Fee Currency"].upper(), _num(row, "Fee", filename)
        account = _account(row.get("Exchange", ""), "CoinTracking")
        tx_id = row.get("Tx-ID (optional)", "") or row.get("Tx-ID", "")
        comment = row.get("Comment", "")
        date = _parse_ct_date(row["Date"], filename, line)
    elif fmt == "CT_EXPORT":
        kind_raw = row["Type"]
        in_asset, in_amt = row["Cur."].upper(), _num(row, "Buy", filename)
        out_asset, out_amt = row["Cur.#2"].upper(), _num(row, "Sell", filename)
        fee_asset, fee_amt = row["Cur.#3"].upper(), _num(row, "Fee", filename)
        account = _account(row.get("Exchange", ""), "CoinTracking")
        comment = row.get("Comment", "")
        date = _parse_ct_date(row["Date"], filename, line)
    elif fmt == "CT_FULL":
        kind_raw = row["Type"]
        in_asset, in_amt = row["Cur."].upper(), _num(row, "Buy", filename)
        out_asset, out_amt = row["Cur.#2"].upper(), _num(row, "Sell", filename)
        fee_asset, fee_amt = "", Decimal("0")          # die Vollansicht führt keine Gebühr
        account = _account(row.get("Exchange", ""), "CoinTracking")
        date = _parse_ct_date(row["Date"], filename, line)
        eur_in = _value_eur(row, 1, date, filename)
        eur_out = _value_eur(row, 2, date, filename)
    elif fmt == "BP_NEW":
        kind_raw = row["Label"]
        out_asset, out_amt = row["Outgoing Asset"].upper(), _num(row, "Outgoing Amount", filename)
        in_asset, in_amt = row["Incoming Asset"].upper(), _num(row, "Incoming Amount", filename)
        fee_asset = (row.get("Fee Asset") or row.get("Fee Asset (optional)") or "").upper()
        fee_col = "Fee Amount" if "Fee Amount" in row else "Fee Amount (optional)"
        fee_amt = _num(row, fee_col, filename) if fee_asset else Decimal("0")
        account = _account(row.get("Source Name") or row.get("Integration Name", ""), "Blockpit")
        tx_id = row.get("Trx. ID", "") or row.get("Trx. ID (optional)", "")
        comment = row.get("Comments", "") or row.get("Comment (optional)", "")
        date = _parse_bp_date(row["Date (UTC)"], filename, line)
    else:  # BP_OLD
        kind_raw = row["Transaction Type"]
        out_asset, out_amt = row["Outgoing Asset"].upper(), _num(row, "Outgoing Amount", filename)
        in_asset, in_amt = row["Incoming Asset"].upper(), _num(row, "Incoming Amount", filename)
        fee_asset, fee_amt = row["Fee Asset"].upper(), _num(row, "Fee Amount", filename)
        # Source Name ist Blockpits interner Integrationsname („Kraken"), Integration der
        # selbst vergebene („Kraken Depot") — der neutrale Name erscheint in den Reports
        account = _account(row.get("Source Name") or row.get("Integration", ""), "Blockpit")
        tx_id = row.get("Transaction ID", "")
        comment = row.get("Note", "")
        date = _parse_bp_date(row["Timestamp"], filename, line)

    if "BTC" not in (in_asset, out_asset) and not (fee_asset == "BTC" and fee_amt > 0):
        return None
    return dict(date=date, kind=_kind(kind_raw, in_asset, out_asset, fee_asset), kind_raw=kind_raw,
                in_asset=in_asset, in_amt=in_amt, out_asset=out_asset, out_amt=out_amt,
                fee_asset=fee_asset, fee_amt=fee_amt, account=account, tx_id=tx_id.strip(),
                comment=comment, eur_in=eur_in, eur_out=eur_out, line=line, fmt=fmt)


def _kind(raw: str, in_asset: str, out_asset: str, fee_asset: str) -> str:
    k = re.sub(r"[\s_\-()/]+", "", raw.strip().lower())
    k_sp = raw.strip().lower()
    if k == "trade":
        return "trade"
    if k in ("deposit", "nontaxablein", "nontaxable(in)") or (k == "nontaxable" and in_asset):
        return "deposit"
    if k in ("withdrawal", "nontaxableout", "nontaxable(out)") or (k == "nontaxable" and out_asset):
        return "withdrawal"
    if k == "transfer":
        return "transfer"
    if k_sp in _CT_FEE or k == "fee":
        return "fee"
    if k == "gift" or k == "gifttip":
        return "gift_in" if in_asset and not out_asset else "gift_out"
    if k_sp in _CT_GIFT_OUT or k in ("donation", "spende", "schenkung"):
        return "gift_out"
    if k_sp in _CT_INCOME or k in ("income", "mining", "staking", "airdrop", "lending", "bounties", "interest",
                                   "reward", "cashback", "margintradingprofit", "gifttip", "rewardbonus"):
        return "income"
    if k_sp in _CT_SPEND or k in ("spend", "payment"):
        return "spend"
    if k_sp in _CT_LOST or k in ("lost", "stolen", "margintradingloss", "margintradingfee", "withholdingtax",
                                 "autobalancing", "marginfee", "marginloss"):
        return "lost"
    return "unknown"


_VALUE_RE = re.compile(r"^Value in ([A-Z]{3})(#2)?$")


def _value_eur(row: dict, side: int, date: datetime, filename: str) -> Decimal | None:
    """CT_FULL: „Value in EUR" (bzw. USD/CHF der Kontowährung) der Kauf- (1) oder Verkaufsseite (2)."""
    suffix = "" if side == 1 else "#2"
    for col in row:
        m = _VALUE_RE.match(col)
        if not m or m.group(1) == "BTC" or (m.group(2) or "") != suffix:
            continue
        cur = m.group(1)
        raw = row.get(col, "")
        if raw in ("", "-"):
            return None
        val = _num(row, col, filename)
        if cur == "EUR":
            return val
        if cur in FIAT:
            return val * eur_rate_for_date(de_date(date), cur)
        return None
    return None


# ───────────────────────── Datum ─────────────────────────

_CT_FORMS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def _parse_local(raw: str, tz, filename: str, line, what: str) -> datetime:
    text = raw.strip()
    if "/" in text:
        raise ValueError(
            f"{LABEL} {filename} Zeile {line}: Datum '{raw}' ist mehrdeutig (Monat/Tag?). Bitte das "
            f"Datumsformat in {what} auf TT.MM.JJJJ stellen und neu exportieren."
        )
    if "T" in text or text.endswith(("Z", "z")) or re.search(r"[+-]\d{2}:\d{2}$", text):
        return parse_iso_datetime(text, label=LABEL, filename=filename, line=line, field="Date")
    for form in _CT_FORMS:
        try:
            return datetime.strptime(text, form).replace(tzinfo=tz).astimezone(timezone.utc)
        except ValueError:
            continue
    raise ValueError(
        f"{LABEL} {filename} Zeile {line}: Datum '{raw}' nicht lesbar (erwartet TT.MM.JJJJ HH:MM[:SS] "
        f"oder JJJJ-MM-TT HH:MM[:SS])."
    )


def _parse_ct_date(raw: str, filename: str, line) -> datetime:
    # CoinTracking: Zeit der Kontoeinstellung ohne Zeitzone → Europe/Berlin (deutsche Nutzer)
    return _parse_local(raw, TZ_DE, filename, line, "CoinTracking")


def _parse_bp_date(raw: str, filename: str, line) -> datetime:
    # Blockpit: „Date (UTC)" bzw. „Timestamp" → UTC
    return _parse_local(raw, timezone.utc, filename, line, "Blockpit")


# ───────────────────────── Abbildung ─────────────────────────

def _r2(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _to_eur(amt: Decimal, cur: str, date: datetime) -> Decimal:
    return amt if cur == "EUR" else amt * eur_rate_for_date(de_date(date), cur)


def _to_transaction(rec: dict, filename: str) -> Transaction | None:
    date, kind, account, no_kyc = rec["date"], rec["kind"], rec["account"], rec["no_kyc"]
    ia, iq, oa, oq, fa, fq = (rec["in_asset"], rec["in_amt"], rec["out_asset"], rec["out_amt"],
                              rec["fee_asset"], rec["fee_amt"])
    year = de_date(date).year
    tag = de_date(date)
    where = f"{filename} Zeile {rec['line']}"
    base = dict(date=date, source=account, no_kyc=no_kyc)
    fee_btc = fq if (fa == "BTC" and fq > 0) else Decimal("0")

    def wrn(msg: str) -> None:
        # Dateiname nur im internen Kanal (kann ein privates Label sein)
        warn_both(f"{where}: {msg}", f"Sammelimport-Datei, Zeile {rec['line']}: {msg}", internal=no_kyc, year=year)

    def tx_id(prefix: str) -> str:
        return rec["tx_id"] or f"{prefix}-{account}-{date.strftime('%Y%m%dT%H%M%S')}-{iq or oq}"

    # Gebühr in BTC an einer Zeile ohne BTC-Hauptseite (z.B. ETH-Trade mit BTC-Gebühr)
    if "BTC" not in (ia, oa):
        if fee_btc > 0:
            return Transaction(type=TxType.TRANSFER_OUT, btc_amount=Decimal("0"), eur_amount=Decimal("0"),
                               eur_price_per_btc=Decimal("0"), fee_eur=Decimal("0"), fee_btc=fee_btc,
                               tx_id=tx_id("fee"), note=f"Gebühr in BTC ({rec['kind_raw']})", **base)
        return None

    if kind == "trade":
        if ia == "BTC" and oa in FIAT and iq > 0:
            eur_amount = _to_eur(oq, oa, date)
            price = eur_amount / iq
            fee_eur = Decimal("0")
            if fa in FIAT and fq > 0:
                fee_eur = _to_eur(fq, fa, date)
            elif fee_btc > 0:
                fee_eur = _r2(fee_btc * price)        # Anschaffungsnebenkosten (BMF Rn. 59) + Gebührenabgang (H8)
            elif fa and fq > 0:
                wrn(f"Gebühr {fq} {fa} beim BTC-Kauf nicht verarbeitet (weder Fiat noch BTC).")
            return Transaction(type=TxType.BUY, btc_amount=iq, eur_amount=eur_amount, eur_price_per_btc=price,
                               fee_eur=fee_eur, fee_btc=fee_btc, tx_id=tx_id("buy"),
                               note=f"Kauf über {account}" + (f" [Original: {oa}]" if oa != "EUR" else ""), **base)
        if oa == "BTC" and ia in FIAT and oq > 0:
            eur_amount = _to_eur(iq, ia, date)
            fee_eur = _to_eur(fq, fa, date) if (fa in FIAT and fq > 0) else Decimal("0")
            if fa and fq > 0 and fa not in FIAT and fa != "BTC":
                wrn(f"Gebühr {fq} {fa} beim BTC-Verkauf nicht verarbeitet (weder Fiat noch BTC).")
            return Transaction(type=TxType.SELL, btc_amount=oq, eur_amount=eur_amount,
                               eur_price_per_btc=eur_amount / oq, fee_eur=fee_eur, fee_btc=fee_btc,
                               tx_id=tx_id("sell"),
                               note=f"Verkauf über {account}" + (f" [Original: {ia}]" if ia != "EUR" else ""), **base)
        # BTC gegen andere Kryptowährung (auch Stablecoins) oder nicht umrechenbares Fiat
        other = oa if ia == "BTC" else ia
        value = rec["eur_in"] if ia == "BTC" else rec["eur_out"]
        if value is not None and value > 0 and (iq if ia == "BTC" else oq) > 0:
            if ia == "BTC":
                return Transaction(type=TxType.BUY, btc_amount=iq, eur_amount=value, eur_price_per_btc=value / iq,
                                   fee_eur=Decimal("0"), fee_btc=fee_btc, tx_id=tx_id("buy"),
                                   note=f"Tausch {other}→BTC über {account}, EUR-Wert laut Export", **base)
            return Transaction(type=TxType.SELL, btc_amount=oq, eur_amount=value, eur_price_per_btc=value / oq,
                               fee_eur=Decimal("0"), fee_btc=fee_btc, tx_id=tx_id("sell"),
                               note=f"Tausch BTC→{other} über {account}, EUR-Wert laut Export", **base)
        richtung = "ANSCHAFFUNG" if ia == "BTC" else "VERÄUSSERUNG"
        datei = "manual_buys.csv" if ia == "BTC" else "manual_sales.csv"
        wrn(f"Tausch {oa}→{ia} ({account}) am {tag} ist eine {richtung} von BTC ohne EUR-Wert im Export — "
            f"nicht verarbeitet. Bitte als {datei} mit dem EUR-Wert zum Handelstag erfassen"
            f"{' (no_kyc=ja)' if no_kyc and ia != 'BTC' else ''}.")
        return None

    if kind == "deposit" and ia == "BTC" and iq > 0:
        return Transaction(type=TxType.TRANSFER_IN, btc_amount=iq, eur_amount=Decimal("0"),
                           eur_price_per_btc=Decimal("0"), fee_eur=Decimal("0"), fee_btc=fee_btc,
                           tx_id=tx_id("in"), note=f"Eingang bei {account}", **base)
    if kind == "withdrawal" and oa == "BTC" and oq > 0:
        return Transaction(type=TxType.TRANSFER_OUT, btc_amount=oq, eur_amount=Decimal("0"),
                           eur_price_per_btc=Decimal("0"), fee_eur=Decimal("0"), fee_btc=fee_btc,
                           tx_id=tx_id("out"), note=f"Auszahlung von {account}", **base)
    if kind == "fee" and oa == "BTC" and oq > 0:
        return Transaction(type=TxType.TRANSFER_OUT, btc_amount=Decimal("0"), eur_amount=Decimal("0"),
                           eur_price_per_btc=Decimal("0"), fee_eur=Decimal("0"), fee_btc=oq + fee_btc,
                           tx_id=tx_id("fee"), note=f"Gebühr in BTC bei {account} ({rec['kind_raw']})", **base)
    if kind == "gift_in" and ia == "BTC" and iq > 0:
        # Unentgeltlicher Erwerb: Anschaffungsdatum und -kosten des Schenkers gelten
        # (§ 23 Abs. 1 S. 3 EStG) — ein Kauf zum Exportwert wäre falsch (Faktencheck 03.10.2026)
        wrn(f"Geschenk erhalten: {iq:.8f} BTC ({rec['kind_raw']}, {account}) am {tag} — nicht verarbeitet. Für die "
            f"Haltefrist gelten Anschaffungsdatum und -kosten des Schenkers (§ 23 Abs. 1 Satz 3 EStG); bitte als "
            f"manual_buys.csv mit dessen Datum und Betrag erfassen.")
        return None
    if kind == "income" and ia == "BTC" and iq > 0:
        value = rec["eur_in"]
        if value is not None and value > 0:
            return Transaction(type=TxType.BUY, btc_amount=iq, eur_amount=value, eur_price_per_btc=value / iq,
                               fee_eur=Decimal("0"), fee_btc=fee_btc, tx_id=tx_id("in"),
                               note=f"Zufluss ({rec['kind_raw']}) bei {account}, EUR-Wert laut Export — "
                                    f"steuerliche Einordnung des Zuflusses selbst prüfen", **base)
        wrn(f"Zufluss {iq:.8f} BTC ({rec['kind_raw']}, {account}) am {tag} ohne EUR-Wert — Anschaffung ohne Kaufpreis, "
            f"nicht verarbeitet. Bitte als manual_buys.csv mit dem EUR-Wert zum Zuflusstag erfassen; "
            f"ob der Zufluss selbst Einkünfte ist, bitte prüfen.")
        return None
    if kind == "spend" and oa == "BTC" and oq > 0:
        value = rec["eur_out"]
        if value is not None and value > 0:
            return Transaction(type=TxType.SELL, btc_amount=oq, eur_amount=value, eur_price_per_btc=value / oq,
                               fee_eur=Decimal("0"), fee_btc=fee_btc, tx_id=tx_id("sell"),
                               note=f"Bezahlung mit BTC ({rec['kind_raw']}) bei {account}, EUR-Wert laut Export", **base)
        wrn(f"Bezahlung mit {oq:.8f} BTC ({rec['kind_raw']}, {account}) am {tag} ist eine VERÄUSSERUNG zum Marktwert — "
            f"ohne EUR-Wert im Export nicht verarbeitet. Bitte als manual_sales.csv mit dem EUR-Wert zum Zahltag erfassen"
            f"{' (no_kyc=ja)' if no_kyc else ''}.")
        return None
    if kind == "gift_out" and oa == "BTC" and oq > 0:
        return Transaction(type=TxType.GIFT_OUT, btc_amount=oq, eur_amount=Decimal("0"), eur_price_per_btc=Decimal("0"),
                           fee_eur=Decimal("0"), fee_btc=fee_btc, tx_id=tx_id("gift"),
                           note=f"Unentgeltliche Übertragung ({rec['kind_raw']}) von {account}", **base)
    if kind == "lost":
        wrn(f"Zeile '{rec['kind_raw']}' über {(oq or iq):.8f} BTC ({account}) am {tag} nicht verarbeitet — der Bestand "
            f"bleibt rechnerisch bestehen, bitte prüfen (Verlust/Diebstahl ist kein Veräußerungsgeschäft).")
        return None
    wrn(f"Typ '{rec['kind_raw']}' mit {(oq or iq):.8f} BTC ({account}) am {tag} nicht verarbeitet — Zeile bitte prüfen "
        f"und ggf. als manual_buys.csv/manual_sales.csv erfassen.")
    return None
