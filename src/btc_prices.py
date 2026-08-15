"""BTC/EUR-Tagesschlusskurse für die Bewertung von in BTC entrichteten Gebühren.

Wozu: Eine Netzwerk- oder Auszahlungsgebühr, die in Bitcoin bezahlt wird, ist
ein Tausch gegen eine Dienstleistung und damit eine Veräußerung des
Gebührenanteils (BMF-Schreiben vom 06.03.2025, Rn. 33, 54, 60). Der
Veräußerungserlös ist der Marktkurs der hingegebenen Einheiten. Als Marktkurs
darf der Kurs einer Handelsplattform dienen (Rn. 43); ein nach dokumentierten
Vorgaben ermittelter Tageskurs — hier der Tagesschlusskurs — wird nicht
beanstandet, solange die Wertermittlung gleichmäßig ist (Rn. 91).

Quelle: `data/btc_eur_daily.csv` — Tagesschlusskurse BTC/EUR der Handelsplattform
Bitstamp (öffentliche OHLC-API, Tageskerzen in UTC), eine Zeile pro Kalendertag,
seit 2017-01-01. Die Tabelle wird mit dem Tool ausgeliefert und liegt bewusst
NICHT hinter einer Live-Abfrage: Steuerdokumente müssen aus den Daten allein
reproduzierbar sein, und die Transaktionsdaten des Nutzers gehen keinen
Drittanbieter etwas an. Aktualisieren: `python tools/update_btc_prices.py`.

Nachschlagen erfolgt über das deutsche Kalenderdatum (`de_date`) — dasselbe
Datum, das auch Steuerjahr und Haltefrist bestimmt. Fehlt ein Datum (Tabelle
endet davor), liefert `price_for_date` None; die Engine bucht den Bestandsabgang
dann trotzdem, weist Erlös und Gewinn aber als „nicht ermittelt" aus und warnt.
"""
from __future__ import annotations
import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

TABLE_PATH = Path(__file__).parent / "data" / "btc_eur_daily.csv"
SOURCE_LABEL = "Tagesschlusskurs BTC/EUR der Handelsplattform Bitstamp"

_table: dict[date, Decimal] | None = None


def _load() -> dict[date, Decimal]:
    global _table
    if _table is None:
        table: dict[date, Decimal] = {}
        if TABLE_PATH.exists():
            with open(TABLE_PATH, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    table[date.fromisoformat(row["date"].strip())] = Decimal(row["close_eur"].strip())
        _table = table
    return _table


def price_for_date(d: date) -> Decimal | None:
    """Tagesschlusskurs EUR je BTC am Kalendertag d, None wenn nicht in der Tabelle."""
    return _load().get(d)


def table_range() -> tuple[date, date] | None:
    """(erster, letzter) Tag der Tabelle — für Methodik-Angaben und Warnungen."""
    table = _load()
    if not table:
        return None
    return min(table), max(table)
