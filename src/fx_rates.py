"""Historische EUR-Wechselkurse aus den Euro-Referenzkursen der EZB — offline.

Wozu: Pocket und Swissquote buchen Käufe teils in CHF oder USD; Anschaffungskosten
müssen in EUR angesetzt werden.

Quelle: `data/ecb_eur_daily.csv` — Euro-Referenzkurse der Europäischen Zentralbank
(USD, CHF; Einheiten Fremdwährung je 1 EUR, wie veröffentlicht), seit 2010. Die
Tabelle wird mit dem Tool ausgeliefert und liegt bewusst NICHT hinter einer
Live-Abfrage: Steuerdokumente müssen aus den Daten allein reproduzierbar sein, und
die Transaktionsdaten des Nutzers gehen keinen Drittanbieter etwas an.
Aktualisieren: `python tools/update_fx_rates.py`.

Regeln (steuerrelevant, deshalb hier festgehalten):
- Die EZB veröffentlicht nur an TARGET-Arbeitstagen. Für Wochenenden und Feiertage
  gilt der letzte veröffentlichte Kurs VOR dem Datum.
- Liegt das Datum nach dem letzten Tabellentag, gibt es KEINEN Kurs — ob die EZB
  inzwischen einen neueren veröffentlicht hat, kann das Tool nicht wissen. Dann
  bricht die Berechnung mit einer Erklärung ab, statt still einen alten Kurs zu nehmen.
- Umrechnung: EUR je Einheit = 1 / Referenzkurs, gerundet auf 5 signifikante
  Stellen. Das entspricht exakt den Werten, die das Tool bis 10/2026 über die
  frankfurter-API (selbst nur ein Spiegel der EZB-Kurse) bezogen hat — ältere
  Reports bleiben damit byte-gleich.
- `fx_cache.json` im Datenverzeichnis überschreibt die Tabelle (Schlüssel
  "JJJJ-MM-TT:WÄHRUNG", Wert EUR je Einheit). Für Kurse nach dem Tabellenende
  oder für andere Währungen.
"""
from __future__ import annotations
import csv
import json
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

TABLE_PATH = Path(__file__).parent / "data" / "ecb_eur_daily.csv"
SOURCE_LABEL = "Euro-Referenzkurse der Europäischen Zentralbank"

CACHE_FILE = Path(__file__).parent.parent / "fx_cache.json"
_cache: dict[str, Decimal] = {}
_table: dict[str, dict[date, Decimal]] | None = None
# Wurde in diesem Lauf ein Tabellenkurs verwendet? (für die Quellenangabe im Nachweis)
used_table = False


def init(data_dir: Path) -> None:
    """Override-Datei auf ein anderes Datenverzeichnis umlenken (z.B. --data-dir)."""
    global CACHE_FILE, _cache, used_table
    CACHE_FILE = data_dir / "fx_cache.json"
    _cache = {}  # leeren, damit beim nächsten Zugriff neu geladen wird
    used_table = False


def _load_cache() -> None:
    global _cache
    if CACHE_FILE.exists():
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        _cache = {k: Decimal(str(v)) for k, v in raw.items()}


def _load_table() -> dict[str, dict[date, Decimal]]:
    global _table
    if _table is None:
        table: dict[str, dict[date, Decimal]] = {}
        with open(TABLE_PATH, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            currencies = [c for c in reader.fieldnames if c != "date"]
            for c in currencies:
                table[c] = {}
            for row in reader:
                d = date.fromisoformat(row["date"].strip())
                for c in currencies:
                    table[c][d] = Decimal(row[c].strip())
        _table = table
    return _table


def table_range() -> tuple[date, date]:
    """(erster, letzter) Tag der Tabelle — für Quellenangabe und Fehlermeldungen."""
    days = next(iter(_load_table().values()))
    return min(days), max(days)


def _to_eur(reference: Decimal) -> Decimal:
    """EZB-Referenzkurs (Fremdwährung je EUR) → EUR je Einheit, 5 signifikante Stellen."""
    inverse = Decimal(1) / reference
    # normalize(): 1.0240 → 1.024, wie die API es lieferte (Wert gleich, Darstellung auch)
    return inverse.quantize(Decimal(1).scaleb(inverse.adjusted() - 4), rounding=ROUND_HALF_UP).normalize()


def eur_rate_for_date(d: date, from_currency: str) -> Decimal:
    """
    Gibt den EUR-Kurs für eine Währung an einem bestimmten Datum zurück.
    Z.B. eur_rate_for_date(date(2023, 8, 15), "USD") → Decimal("0.91525")
    Bedeutet: 1 USD = 0.91525 EUR
    """
    global used_table
    from_currency = from_currency.upper()
    if from_currency == "EUR":
        return Decimal("1")

    if not _cache:
        _load_cache()
    cache_key = f"{d.isoformat()}:{from_currency}"
    if cache_key in _cache:
        return _cache[cache_key]

    hint = (f"Kurs bitte selbst nachschlagen und in fx_cache.json im Datenverzeichnis "
            f'eintragen: "{cache_key}": "<EUR je {from_currency}>"')
    series = _load_table().get(from_currency)
    if series is None:
        raise RuntimeError(f"Kein Wechselkurs für {from_currency} hinterlegt (Tabelle kennt "
                           f"{', '.join(_load_table())}). {hint}")
    first, last = min(series), max(series)
    if d > last:
        raise RuntimeError(f"Wechselkurs {from_currency} am {d.isoformat()} fehlt: die "
                           f"mitgelieferten EZB-Kurse reichen bis {last.isoformat()}. "
                           f"Neuere Tool-Version verwenden oder: {hint}")
    if d < first:
        raise RuntimeError(f"Wechselkurs {from_currency} am {d.isoformat()} fehlt: die "
                           f"mitgelieferten EZB-Kurse beginnen am {first.isoformat()}. {hint}")
    day = max(k for k in series if k <= d) if d not in series else d
    used_table = True
    return _to_eur(series[day])
