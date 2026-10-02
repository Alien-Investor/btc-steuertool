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

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

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
    rows: list[ManualLinkRow] = []
    with open(filepath, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"{FILENAME}: Datei hat keine Kopfzeile.")
        seen = [h.strip() for h in reader.fieldnames if h and h.strip()]
        missing = [c for c in _REQUIRED if c not in seen]
        unknown = [c for c in seen if c not in _KNOWN]
        if missing or unknown:
            raise ValueError(
                f"{FILENAME}: Kopfzeile passt nicht"
                + (f" — fehlend: {', '.join(missing)}" if missing else "")
                + (f" — unbekannt: {', '.join(unknown)}" if unknown else "")
                + f". Erwartet: {','.join(_REQUIRED)}[,notiz]."
            )
        for i, raw in enumerate(reader, start=2):
            row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
            if not any(row.get(c) for c in _REQUIRED):
                continue  # Leerzeile
            empty = [c for c in _REQUIRED if not row.get(c)]
            if empty:
                raise ValueError(f"{FILENAME} Zeile {i}: Pflichtfeld leer ({', '.join(empty)}).")
            try:
                rows.append(ManualLinkRow(
                    line=i,
                    giver_date=date.fromisoformat(row["datum_abgang"]),
                    giver_wallet=row["von"],
                    giver_amount=Decimal(row["menge_abgang"].replace(",", ".")),
                    taker_date=date.fromisoformat(row["datum_eingang"]),
                    taker_wallet=row["nach"],
                    taker_amount=Decimal(row["menge_eingang"].replace(",", ".")),
                ))
            except (ValueError, InvalidOperation) as e:
                raise ValueError(f"{FILENAME} Zeile {i}: ungültiger Wert — {e}") from e
            r = rows[-1]
            if r.giver_amount <= 0 or r.taker_amount <= 0 or not r.giver_amount.is_finite():
                raise ValueError(f"{FILENAME} Zeile {i}: Mengen müssen positiv sein.")
    return rows


def resolve_wallet(raw: str, known: set[str]) -> str | None:
    """Ordnet einen geschriebenen Wallet-Namen einer bekannten Wallet zu:
    exakt, als BitBox-Dateiname (ohne „bitbox:“) oder ohne Groß-/Kleinschreibung.
    None = nicht eindeutig auffindbar."""
    name = _ALIASES.get(raw.strip().lower(), raw.strip())
    for cand in (name, f"bitbox:{name}"):
        if cand in known:
            return cand
    lower = [w for w in known if w.lower() in (name.lower(), f"bitbox:{name}".lower())]
    return lower[0] if len(lower) == 1 else None
