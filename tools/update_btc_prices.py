#!/usr/bin/env python3
"""Aktualisiert src/data/btc_eur_daily.csv (BTC/EUR-Tagesschlusskurse, Bitstamp).

Die Tabelle bewertet in BTC entrichtete Gebühren (Netzwerk-/Auszahlungsgebühren),
siehe src/btc_prices.py. Sie wird mit dem Tool ausgeliefert, damit Reports offline
und reproduzierbar bleiben — dieses Skript ist der EINZIGE Weg, auf dem Kursdaten
ins Tool kommen. Es hängt fehlende Tage an und lässt vorhandene Zeilen unverändert
(ein einmal verwendeter Kurs ändert sich nicht mehr, sonst wären zwei Läufe
desselben Jahresreports nicht mehr identisch).

Quelle: https://www.bitstamp.net/api/v2/ohlc/btceur/?step=86400 (öffentlich, ohne
Schlüssel; Tageskerzen in UTC). Der aktuelle Tag wird nicht übernommen — seine
Kerze ist noch nicht geschlossen.

Aufruf:  python tools/update_btc_prices.py
"""
from __future__ import annotations
import csv
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "src" / "data" / "btc_eur_daily.csv"
API = "https://www.bitstamp.net/api/v2/ohlc/btceur/"
FIRST_DAY = date(2017, 1, 1)
DAY = 86400


def load() -> dict[date, str]:
    table: dict[date, str] = {}
    if TABLE.exists():
        with open(TABLE, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                table[date.fromisoformat(row["date"])] = row["close_eur"]
    return table


def fetch(start_ts: int) -> list[dict]:
    resp = requests.get(API, params={"step": DAY, "limit": 1000, "start": start_ts}, timeout=30)
    resp.raise_for_status()
    return resp.json()["data"]["ohlc"]


def main() -> int:
    table = load()
    last = max(table) if table else FIRST_DAY - timedelta(days=1)
    today = datetime.now(timezone.utc).date()
    start = last + timedelta(days=1)
    added = 0
    while start < today:
        candles = fetch(int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()))
        if not candles:
            break
        for c in candles:
            d = datetime.fromtimestamp(int(c["timestamp"]), tz=timezone.utc).date()
            if d >= today:
                continue           # laufender Tag: Kerze noch offen
            if d not in table:     # vorhandene Werte bleiben, wie sie sind
                table[d] = c["close"]
                added += 1
        newest = datetime.fromtimestamp(int(candles[-1]["timestamp"]), tz=timezone.utc).date()
        if newest < start:
            break
        start = newest + timedelta(days=1)

    with open(TABLE, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "close_eur"])
        for d in sorted(table):
            w.writerow([d.isoformat(), table[d]])

    # Lückenprüfung — eine fehlende Zeile hieße: eine Gebühr an dem Tag bleibt unbewertet
    days = sorted(table)
    gaps = [(a, b) for a, b in zip(days, days[1:]) if (b - a).days != 1]
    print(f"{added} Tag(e) ergänzt, Tabelle {days[0]} – {days[-1]} ({len(days)} Zeilen)")
    if gaps:
        print("ACHTUNG, Lücken:", ", ".join(f"{a}→{b}" for a, b in gaps))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
