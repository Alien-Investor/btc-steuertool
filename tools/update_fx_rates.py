#!/usr/bin/env python3
"""Aktualisiert src/data/ecb_eur_daily.csv (EZB-Referenzkurse USD und CHF).

Die Tabelle rechnet Käufe in Fremdwährung (Pocket, Swissquote) in EUR um, siehe
src/fx_rates.py. Sie wird mit dem Tool ausgeliefert, damit Reports offline und
reproduzierbar bleiben — dieses Skript ist der EINZIGE Weg, auf dem Wechselkurse
ins Tool kommen. Es hängt fehlende Tage an und lässt vorhandene Zeilen unverändert
(ein einmal verwendeter Kurs ändert sich nicht mehr).

Quelle: Euro-Referenzkurse der Europäischen Zentralbank, Gesamthistorie
https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip (öffentlich, ohne
Schlüssel). Die Werte stehen so in der Tabelle, wie die EZB sie veröffentlicht:
Einheiten Fremdwährung je 1 EUR. Die EZB veröffentlicht nur an TARGET-Arbeitstagen;
die Lücken (Wochenenden, Feiertage) sind gewollt, fx_rates.py nimmt dann den
letzten veröffentlichten Kurs.

Aufruf:  python tools/update_fx_rates.py               (lädt von der EZB)
         python tools/update_fx_rates.py <datei.zip|.csv>  (vorher selbst geladen)
"""
from __future__ import annotations
import csv
import io
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "src" / "data" / "ecb_eur_daily.csv"
URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
CURRENCIES = ("USD", "CHF")
FIRST_DAY = date(2010, 1, 1)


def load() -> dict[date, dict[str, str]]:
    table: dict[date, dict[str, str]] = {}
    if TABLE.exists():
        with open(TABLE, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                table[date.fromisoformat(row["date"])] = {c: row[c] for c in CURRENCIES}
    return table


def read_source(arg: str | None) -> str:
    if arg is None:
        import requests  # nur hier — die App selbst hat keinen Netzcode
        resp = requests.get(URL, timeout=60)
        resp.raise_for_status()
        raw = resp.content
    else:
        raw = Path(arg).read_bytes()
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            raw = z.read("eurofxref-hist.csv")
    return raw.decode("utf-8")


def main() -> int:
    table = load()
    added = 0
    for row in csv.DictReader(io.StringIO(read_source(sys.argv[1] if len(sys.argv) > 1 else None))):
        d = date.fromisoformat(row["Date"].strip())
        if d < FIRST_DAY or d in table:     # vorhandene Werte bleiben, wie sie sind
            continue
        values = {c: row[c].strip() for c in CURRENCIES}
        if any(v in ("", "N/A") for v in values.values()):
            print(f"ACHTUNG: {d} unvollständig ({values}) — übersprungen")
            continue
        table[d] = values
        added += 1

    with open(TABLE, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", *CURRENCIES])
        for d in sorted(table):
            w.writerow([d.isoformat(), *(table[d][c] for c in CURRENCIES)])

    # Plausibilität: mehr als 5 Kalendertage ohne Kurs gibt es bei der EZB nicht
    # (längste Pause: Ostern bzw. Weihnachten/Neujahr)
    days = sorted(table)
    gaps = [(a, b) for a, b in zip(days, days[1:]) if (b - a).days > 5]
    print(f"{added} Tag(e) ergänzt, Tabelle {days[0]} – {days[-1]} ({len(days)} Zeilen)")
    if gaps:
        print("ACHTUNG, Lücken:", ", ".join(f"{a}→{b}" for a, b in gaps))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
