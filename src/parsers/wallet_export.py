"""Exporte weiterer Wallet-Software (v1.4): Sparrow, Electrum, Trezor Suite, Ledger Wallet (früher Ledger Live).

Alle Dateien liegen in `wallets/` (KYC) bzw. `wallets/nokyc/` (noKYC, wie `bitbox/nokyc/`).
Welches Programm die Datei geschrieben hat, erkennt `detect()` an der Kopfzeile — der
Dateiname ist nur das private Label der Wallet (Quelle `sparrow:<Dateiname>` usw., in
offiziellen Dokumenten neutral „Sparrow-Wallet 1“, siehe models.WALLET_KINDS).

**Status: Formate aus dem Quellcode der Programme abgeleitet, noch nicht an einem echten
Export eines Nutzers bestätigt.** Jede Datei erzeugt deshalb eine sichtbare Warnung im
Report (wie beim Sammelimport). Grundsatz: lieber laut melden als still rechnen.

Gemeinsames Modell der Netto-Exporte (Sparrow, Electrum): eine Zeile je Transaktion, der
Betrag ist die Netto-Änderung der Wallet mit Vorzeichen — bei Ausgängen ist die Gebühr
ENTHALTEN. `delta_tx` bildet daraus dasselbe wie der BitBox-Parser:
    Betrag > 0                → TRANSFER_IN
    Betrag < 0, Gebühr bekannt → TRANSFER_OUT mit btc_amount = |Betrag| − Gebühr, fee_btc = Gebühr
                                (GIFT_OUT bei Schenkungswort im Label, bitbox.is_gift_note)
    |Betrag| = Gebühr          → an sich selbst: Menge 0, nur Gebühr (wie BitBox sent_to_yourself)
    Gebühr unbekannt           → ganzer Betrag als Übertrag, laute Warnung (Gebühr fehlt)
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Transaction, TxType, TZ_DE, de_date
from . import warn_fmt, FileRef
from .bitbox import is_gift_note

ZERO = Decimal("0")
_MAX_BTC = Decimal("21000000")


def local_time(value: str, fmt: str, *, label: str, filename: str, line, field: str,
               after: datetime | None = None) -> datetime:
    """Zeit ohne Zeitzone als deutsche Ortszeit lesen (Electrum, alte Sparrow-Versionen).

    In der doppelten Stunde der Umstellung auf Winterzeit (02:00–03:00 gibt es zweimal) ist die
    Ortszeit mehrdeutig. Beide Programme schreiben chronologisch: `after` ist der UTC-Zeitpunkt
    der vorigen Zeile — läge die erste Lesart davor, gilt die zweite (Audit v1.4, fold=1)."""
    try:
        naive = datetime.strptime(value.strip(), fmt)
    except ValueError:
        raise ValueError(f"{label} {filename} Zeile {line}, Spalte '{field}': '{value}' — erwartet {fmt}.") from None
    first = naive.replace(tzinfo=TZ_DE).astimezone(timezone.utc)
    if after is not None and first < after:
        second = naive.replace(tzinfo=TZ_DE, fold=1).astimezone(timezone.utc)
        if second >= after:
            return second
    return first


def dst_alternative(date: datetime) -> datetime | None:
    """Andere UTC-Lesart einer als Ortszeit gelesenen Zeit, falls sie in der doppelten Stunde liegt."""
    local = date.astimezone(TZ_DE).replace(tzinfo=None)
    a = local.replace(tzinfo=TZ_DE, fold=0).astimezone(timezone.utc)
    b = local.replace(tzinfo=TZ_DE, fold=1).astimezone(timezone.utc)
    if a == b:
        return None
    return b if date == a else a


class Stats:
    """Zähler je Datei für gesammelte Warnungen (eine Meldung je Art und Jahr, nicht je Zeile)."""

    def __init__(self) -> None:
        self.counts: dict[tuple[str, int | None], int] = {}

    def add(self, kind: str, year: int | None) -> None:
        self.counts[(kind, year)] = self.counts.get((kind, year), 0) + 1

    def items(self):
        return sorted(self.counts.items(), key=lambda kv: (kv[0][1] or 0, kv[0][0]))


def delta_tx(*, date: datetime, delta: Decimal, fee: Decimal | None, label: str, tx_id: str,
             source: str, no_kyc: bool, where: str, stats: Stats) -> Transaction | None:
    """Eine Zeile eines Netto-Exports (Betrag = Netto-Änderung inkl. Gebühr) → Transaction.

    `fee` None = unbekannt. Eine Gebühr 0 bei einem Ausgang gilt ebenfalls als unbekannt:
    Electrum schreibt „0.“, wenn nicht alle Inputs der Wallet gehören."""
    year = de_date(date).year
    if abs(delta) > _MAX_BTC or (fee is not None and fee > _MAX_BTC):
        raise ValueError(f"{where}: Betrag {delta} BTC ist unplausibel (mehr als 21 Mio. BTC) — Einheit falsch oder Datei beschädigt?")
    if delta == 0:
        stats.add("null", year)
        return None
    if delta > 0:
        return _tx(date, TxType.TRANSFER_IN, delta, ZERO, label, tx_id, source, no_kyc)
    out = -delta
    if fee is None or fee <= 0:
        stats.add("fee_unknown", year)
        typ = TxType.GIFT_OUT if is_gift_note(label) else TxType.TRANSFER_OUT
        return _tx(date, typ, out, ZERO, label, tx_id, source, no_kyc)
    if fee > out:
        raise ValueError(f"{where}: Gebühr {fee} BTC ist größer als der Abgang {out} BTC — Datei beschädigt?")
    amount = out - fee
    if amount == 0:
        note = f"wallet-intern (kein Bestandsabgang, nur Gebühr){' | ' + label if label else ''}"
        return _tx(date, TxType.TRANSFER_OUT, ZERO, fee, note, tx_id, source, no_kyc)
    typ = TxType.GIFT_OUT if is_gift_note(label) else TxType.TRANSFER_OUT
    return _tx(date, typ, amount, fee, label, tx_id, source, no_kyc)


def _tx(date, typ, amount, fee_btc, note, tx_id, source, no_kyc) -> Transaction:
    return Transaction(
        date=date, type=typ, btc_amount=amount, eur_amount=ZERO, eur_price_per_btc=ZERO,
        fee_eur=ZERO, fee_btc=fee_btc, source=source, tx_id=tx_id, note=note, no_kyc=no_kyc,
    )


_STAT_TEXT = {
    "fee_unknown": "{n} Ausgang/Ausgänge im Jahr {year} ohne bekannte Gebühr (fremde Inputs, z. B. CoinJoin/Payjoin, "
                   "oder älteres Exportformat) — als Übertrag ohne getrennte Gebühr gebucht; die Gebühr als Veräußerung fehlt. "
                   "Bitte prüfen.",
    "unconfirmed": "{n} unbestätigte Transaktion(en) nicht gebucht — nach der Bestätigung neu exportieren.",
    "lightning": "{n} Lightning-Vorgang/-Vorgänge im Jahr {year} nicht erfasst — Lightning-Guthaben unterstützt das Tool "
                 "nicht. Kanal-Öffnungen und -Schließungen erscheinen als Abgang bzw. Eingang ohne Gegenstück.",
    "other_coin": "{n} Zeile(n) anderer Kryptowährungen übersprungen (nur BTC relevant).",
    "failed": "{n} fehlgeschlagene Transaktion(en) im Jahr {year}: nur die Gebühr gebucht.",
}


def emit_stats(stats: Stats, *, label: str, filename: str, no_kyc: bool) -> None:
    for (kind, year), n in stats.items():
        if kind == "null":
            continue
        warn_fmt("{file}: " + _STAT_TEXT[kind].replace("{n}", str(n)).replace("{year}", str(year)),
                 internal=no_kyc or kind == "other_coin", year=year if kind != "unconfirmed" else None,
                 file=FileRef(filename, f"ein {label}-Export"))


def warn_unconfirmed_format(filename: str, origin: str, txs: list[Transaction], *, no_kyc: bool,
                            extra: str = "") -> None:
    """Sichtbar im Steuerreport (wie beim Sammelimport): Format nicht an einem echten Export bestätigt."""
    if not txs:
        return
    warn_fmt(
        "{file} ({origin}): Format aus dem Quellcode abgeleitet, noch nicht an einem echten Export bestätigt — "
        "Ergebnis prüfen (Beträge, Gebühren, Zeiten), Abweichungen melden." + extra,
        internal=no_kyc, file=FileRef(filename, "ein Wallet-Export"), origin=origin,
    )


# ───────────────────────── Erkennung und Einstieg ─────────────────────────

def detect(header: list[str]) -> str | None:
    """Art der Wallet-Software aus der Kopfzeile (Schlüssel aus models.WALLET_KINDS)."""
    from . import wallet_sparrow, wallet_electrum, wallet_trezor, wallet_ledger
    for kind, mod in (("sparrow", wallet_sparrow), ("electrum", wallet_electrum),
                      ("trezor", wallet_trezor), ("ledger", wallet_ledger)):
        if mod.matches(header):
            return kind
    return None


def first_line(filepath: Path) -> list[str]:
    import csv
    import io
    data = Path(filepath).read_bytes()[:4096]
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = data.decode("utf-8", errors="replace").splitlines()
    if not text:
        return []
    delim = ";" if text[0].count(";") > text[0].count(",") else ","
    return [h.strip() for h in next(csv.reader(io.StringIO(text[0]), delimiter=delim), [])]


def parse(filepath: Path) -> list[Transaction]:
    """Einstieg für den Loader: Programm erkennen, passenden Parser aufrufen.
    noKYC, wenn die Datei in einem Ordner „nokyc“ liegt (Groß-/Kleinschreibung egal, SA2-04)."""
    from . import wallet_sparrow, wallet_electrum, wallet_trezor, wallet_ledger
    filepath = Path(filepath)
    no_kyc = filepath.parent.name.lower() == "nokyc"
    kind = detect(first_line(filepath))
    if kind is None:
        raise ValueError(
            f"Wallet-Export {filepath.name}: Kopfzeile passt zu keinem unterstützten Programm (Sparrow, Electrum, "
            f"Trezor Suite, Ledger Wallet/Live). Gelesen: {', '.join(first_line(filepath)[:12])}. "
            f"BitBox-Exporte gehören nach bitbox/, Broker-Exporte nach Broker/."
        )
    mod = {"sparrow": wallet_sparrow, "electrum": wallet_electrum,
           "trezor": wallet_trezor, "ledger": wallet_ledger}[kind]
    return mod.parse(filepath, no_kyc=no_kyc)
