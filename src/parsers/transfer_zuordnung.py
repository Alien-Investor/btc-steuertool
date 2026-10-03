"""Parser für transfer_zuordnung.csv — manuelle Zuordnung von Überträgen (BMF Rn. 90).

Die walletbezogene FiFo-Rechnung ordnet jeden Abgang seinem Eingang automatisch
zu (transfer_matching). Wo das nicht eindeutig geht, legt der Nutzer es hier fest:

    datum_abgang,von,menge_abgang,datum_eingang,nach,menge_eingang,notiz
    2024-11-05,bisq,0.00250000,2024-11-25,nokyc_wallet,0.00394500,Sammelauszahlung
    2024-11-20,manual,0.00150000,2024-11-25,nokyc_wallet,0.00394500,Sammelauszahlung

- Eine Zeile = eine Verbindung. Abgebend ist ein Abgang (BitBox „sent“,
  Broker-Auszahlung) oder ein Direktkauf (Pocket, Bisq, manual_buys),
  aufnehmend ein Eingang oder ein Direktverkauf (manual_sales, Pocket).
- Datum = deutsches Kalenderdatum, Menge in BTC, wie in den Warnungen und im
  internen Wallet-Abgleich angegeben.
- Wallet: Dateiname des BitBox-Exports ohne .csv (z.B. wallet1), sonst der
  Broker (21bitcoin, bison, swissquote, strike, pocket, bisq) oder manual.
- Mehrere Zeilen mit demselben Eingang: mehrere Abgänge/Käufe landen in einer
  Auszahlung (typisch Bisq). Ebenso ein Abgang auf mehrere Eingänge.

Fehler sind hart (ValueError): die Datei ist ausdrückliche Absicht des Nutzers,
eine nicht auffindbare Zeile still zu überspringen hieße, seine Zuordnung zu
ignorieren.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from ..models import WALLET_KINDS

FILENAME = "transfer_zuordnung.csv"
_REQUIRED = ("datum_abgang", "von", "menge_abgang", "datum_eingang", "nach", "menge_eingang")
_KNOWN = set(_REQUIRED) | {"notiz"}

# Bezeichnungen, unter denen Pseudo-Wallets in Reports/Log erscheinen
_ALIASES = {"manuell": "manual", "manuell erfasst": "manual"}


@dataclass
class ManualLinkRow:
    line: int
    giver_date: date
    giver_wallet: str       # wie geschrieben — aufgelöst wird gegen die Transaktionen
    giver_amount: Decimal
    taker_date: date
    taker_wallet: str
    taker_amount: Decimal


def parse(filepath: Path) -> list[ManualLinkRow]:
    """Liest über parsers.read_rows (Encoding, BOM, Feldanzahl, Datei und Zeile in jeder Meldung —
    Audit v1.4, R3-B6: Windows-1252 aus Excel ergab sonst einen rohen UnicodeDecodeError ohne
    Dateibezug). Alle Fehler als PrivateError: die Datei kann noKYC-Wallets nennen."""
    from . import read_rows, parse_amount, LINE_KEY, PrivateError
    try:
        raw_rows, header = read_rows(filepath, label="Übertrags-Zuordnung", encodings=("utf-8-sig", "cp1252"))
    except ValueError as e:
        raise PrivateError(str(e)) from None
    seen = [h for h in header if h]
    missing = [c for c in _REQUIRED if c not in seen]
    unknown = [c for c in seen if c not in _KNOWN]
    if missing or unknown:
        raise PrivateError(
            f"{FILENAME}: Kopfzeile passt nicht"
            + (f" — fehlend: {', '.join(missing)}" if missing else "")
            + (f" — unbekannt: {', '.join(unknown)}" if unknown else "")
            + f". Erwartet: {','.join(_REQUIRED)}[,notiz]."
        )
    rows: list[ManualLinkRow] = []
    for row in raw_rows:
        i = row[LINE_KEY]
        if not any(row.get(c) for c in _REQUIRED):
            continue  # Leerzeile
        empty = [c for c in _REQUIRED if not row.get(c)]
        if empty:
            raise PrivateError(f"{FILENAME} Zeile {i}: Pflichtfeld leer ({', '.join(empty)}).")
        try:
            r = ManualLinkRow(
                line=i,
                giver_date=date.fromisoformat(row["datum_abgang"]),
                giver_wallet=row["von"],
                giver_amount=parse_amount(row["menge_abgang"], label="", filename=FILENAME, line=i, field="menge_abgang"),
                taker_date=date.fromisoformat(row["datum_eingang"]),
                taker_wallet=row["nach"],
                taker_amount=parse_amount(row["menge_eingang"], label="", filename=FILENAME, line=i, field="menge_eingang"),
            )
        except ValueError as e:
            raise PrivateError(f"{FILENAME} Zeile {i}: ungültiger Wert — {e}") from None
        if r.giver_amount <= 0 or r.taker_amount <= 0:
            raise PrivateError(f"{FILENAME} Zeile {i}: Mengen müssen endliche positive Zahlen sein.")
        rows.append(r)
    return rows


def resolve_wallet(raw: str, known: set[str]) -> str | None:
    """Ordnet einen geschriebenen Wallet-Namen einer bekannten Wallet zu:
    exakt, als Dateiname eines Wallet-Exports (ohne „bitbox:“, „sparrow:“ …) oder ohne Groß-/Kleinschreibung.
    None = nicht eindeutig auffindbar."""
    name = _ALIASES.get(raw.strip().lower(), raw.strip())
    if name in known:
        return name
    # Dateiname ohne Art-Präfix („wallet1“ → „bitbox:wallet1“, „cold“ → „sparrow:cold“) —
    # nur eindeutig: heißen eine BitBox- und eine Sparrow-Wallet gleich, gilt keine
    exact = [f"{k}:{name}" for k in WALLET_KINDS if f"{k}:{name}" in known]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    cands = {name.lower()} | {f"{k}:{name}".lower() for k in WALLET_KINDS}
    lower = [w for w in known if w.lower() in cands]
    return lower[0] if len(lower) == 1 else None
