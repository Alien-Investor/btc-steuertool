"""Historische EUR-Wechselkurse via frankfurter.app API mit lokalem Cache."""
from __future__ import annotations
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import requests

CACHE_FILE = Path(__file__).parent.parent / "fx_cache.json"
_cache: dict[str, Decimal] = {}


def init(data_dir: Path) -> None:
    """Cache-Pfad auf ein anderes Datenverzeichnis umlenken (z.B. --data-dir)."""
    global CACHE_FILE, _cache
    CACHE_FILE = data_dir / "fx_cache.json"
    _cache = {}  # Cache leeren, damit beim nächsten Zugriff neu geladen wird


def _load_cache() -> None:
    global _cache
    if CACHE_FILE.exists():
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        _cache = {k: Decimal(str(v)) for k, v in raw.items()}


def _save_cache() -> None:
    CACHE_FILE.write_text(
        json.dumps({k: str(v) for k, v in _cache.items()}, indent=2),
        encoding="utf-8",
    )


def eur_rate_for_date(d: date, from_currency: str) -> Decimal:
    """
    Gibt den EUR-Kurs für eine Währung an einem bestimmten Datum zurück.
    Z.B. eur_rate_for_date(date(2025, 8, 12), "USD") → Decimal("0.9123")
    Bedeutet: 1 USD = 0.9123 EUR

    Bei Wochenenden/Feiertagen gibt die API den letzten verfügbaren Kurs zurück.
    """
    from_currency = from_currency.upper()
    if from_currency == "EUR":
        return Decimal("1")

    if not _cache:
        _load_cache()

    cache_key = f"{d.isoformat()}:{from_currency}"
    if cache_key in _cache:
        return _cache[cache_key]

    url = f"https://api.frankfurter.app/{d.isoformat()}?from={from_currency}&to=EUR"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        rate = Decimal(str(data["rates"]["EUR"]))
    except Exception as e:
        raise RuntimeError(
            f"Wechselkurs-API-Fehler für {from_currency} am {d.isoformat()}: {e}\n"
            f"URL: {url}\n"
            f"Bitte manuell in fx_cache.json eintragen: "
            f'"{cache_key}": "<kurs>"'
        ) from e

    _cache[cache_key] = rate
    _save_cache()
    return rate
