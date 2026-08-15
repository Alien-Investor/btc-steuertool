from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import date, datetime
from enum import Enum
from zoneinfo import ZoneInfo

# Deutsche Zeitzone — maßgeblich für Steuerjahr und Haltefrist ist das
# Kalenderdatum in deutscher Zeit, nicht UTC (ein Verkauf am 31.12. um 23:30 UTC
# gehört steuerlich schon ins Folgejahr).
TZ_DE = ZoneInfo("Europe/Berlin")


def de_date(dt: datetime) -> date:
    """Kalenderdatum in deutscher Zeit — für Steuerjahr, Haltefrist und Anzeige."""
    return dt.astimezone(TZ_DE).date()


class TxType(Enum):
    BUY          = "buy"           # BTC-Kauf bei Broker (EUR → BTC)
    SELL         = "sell"          # BTC-Verkauf bei Broker (BTC → EUR)
    TRANSFER_OUT = "transfer_out"  # BTC von Broker/Wallet weggeschickt (eigene Wallet)
    TRANSFER_IN  = "transfer_in"   # BTC auf Broker/Wallet empfangen (eigene Wallet)
    # Unentgeltliche Übertragung an Dritte (Schenkung/Spende): keine Veräußerung
    # i.S.d. § 23 EStG (keine entgeltliche Übertragung, BMF 06.03.2025 Rn. 54),
    # aber ein Bestandsabgang — die FiFo-Lots verlassen den Pool ohne Gewinn.
    GIFT_OUT     = "gift_out"


class DisposalKind(Enum):
    """Warum ein FiFo-Lot (teilweise) verbraucht wurde."""
    SELL = "sell"   # Verkauf gegen EUR
    FEE  = "fee"    # in BTC entrichtete Gebühr (Netzwerk-/Auszahlungsgebühr):
                    # Tausch gegen Dienstleistung = Veräußerung (BMF 06.03.2025 Rn. 33, 54, 60)
    GIFT = "gift"   # unentgeltliche Übertragung: kein Veräußerungsgeschäft, nur Bestandsabgang


SATOSHI = Decimal("100000000")


def sat_to_btc(satoshi: int | str) -> Decimal:
    return Decimal(str(satoshi)) / SATOSHI


@dataclass
class Transaction:
    date: datetime          # timezone-aware (UTC; Swissquote/Bisq: Europe/Berlin) — Steuerjahr/Haltefrist via de_date()
    type: TxType
    btc_amount: Decimal     # immer positiv, in BTC
    eur_amount: Decimal     # Kaufpreis oder Verkaufserlös vor Gebühren; 0 bei Transfer
    eur_price_per_btc: Decimal  # 0 bei Transfer
    fee_eur: Decimal        # Gebühren in EUR; 0 wenn nicht bekannt
    source: str             # z.B. "21bitcoin", "bison", "bitbox:wallet1"
    tx_id: str
    note: str
    no_kyc: bool = False    # True = P2P-Kauf (Bisq/Robosats/manual) — nicht im Finanzamt-Report
    # In BTC entrichtete Gebühr (Miner-Fee bei Wallet-Transfers, Auszahlungsgebühr
    # des Brokers in BTC, Bisq-Handelsgebühr). Sie verlässt den Bestand ZUSÄTZLICH
    # zu btc_amount und wird von der FiFo-Engine als eigene Veräußerung des
    # Gebührenanteils zum Tageskurs verbucht (H8). 0 = keine oder unbekannt.
    fee_btc: Decimal = Decimal("0")

    _DECIMAL_FIELDS = ("btc_amount", "eur_amount", "eur_price_per_btc", "fee_eur", "fee_btc")

    def __post_init__(self):
        # Sicherstellen dass alle Decimal-Felder auch Decimal sind
        for f in self._DECIMAL_FIELDS:
            val = getattr(self, f)
            if not isinstance(val, Decimal):
                object.__setattr__(self, f, Decimal(str(val)))
        # Negative Beträge hart ablehnen — ein Vorzeichen-Tippfehler (z.B. in
        # manual_buys.csv) würde sonst die FiFo-Kette lautlos korrumpieren
        # Infinity und NaN passieren jeden Vorzeichentest (Infinity < 0 ist False)
        # und würden die FiFo-Kette verseuchen, statt laut zu scheitern (H9).
        for f in self._DECIMAL_FIELDS:
            val = getattr(self, f)
            if not val.is_finite():
                raise ValueError(
                    f"{self.source}: unendlicher oder undefinierter Wert bei {f} "
                    f"({val}) — bitte den Betrag in der CSV korrigieren."
                )
        if self.type in (TxType.BUY, TxType.SELL):
            if self.btc_amount < 0 or self.eur_amount < 0 or self.fee_eur < 0:
                raise ValueError(
                    f"{self.source} {de_date(self.date)}: negativer Betrag bei {self.type.value} "
                    f"(btc={self.btc_amount}, eur={self.eur_amount}, fee={self.fee_eur}) — "
                    f"Beträge immer positiv angeben."
                )
        # Eine negative Gebühr würde in der Engine Bestand ERZEUGEN statt verbrauchen.
        if self.fee_btc < 0:
            raise ValueError(
                f"{self.source} {de_date(self.date)}: negative Gebühr fee_btc={self.fee_btc} — "
                f"Beträge immer positiv angeben."
            )


@dataclass
class Lot:
    """Ein FiFo-Lot: ein Kauf mit verbleibender BTC-Menge und Einstandspreis."""
    purchase_date: datetime
    btc_amount: Decimal     # verbleibende BTC in diesem Lot
    cost_per_btc: Decimal   # (eur_amount + fee_eur) / original_btc_amount
    source: str
    tx_id: str
    no_kyc: bool = False


@dataclass
class DisposalMatch:
    """Ergebnis der FiFo-Zuordnung bei einem Verkauf."""
    lot_purchase_date: datetime
    lot_source: str
    btc_used: Decimal
    cost_per_btc: Decimal       # Einstandspreis
    net_sell_price_per_btc: Decimal  # Netto-Verkaufspreis (nach Gebühren)
    gain_eur: Decimal           # positiv = Gewinn, negativ = Verlust
    holding_days: int
    is_tax_free: bool           # Haltedauer > 365 Tage


@dataclass
class SellResult:
    """Komplettes Ergebnis eines Bestandsabgangs nach FiFo-Auflösung.

    Der Name stammt aus der Zeit, als nur Verkäufe Lots verbrauchten. Seit H8
    gilt dasselbe für in BTC entrichtete Gebühren (kind=FEE, Veräußerung des
    Gebührenanteils) und für unentgeltliche Übertragungen (kind=GIFT, kein
    Veräußerungsgeschäft, gain_eur je Match = 0). Reports lesen Menge, Erlös und
    Kurs über die Properties unten — nicht direkt aus sell_tx, denn bei einer
    Gebühr ist die abgegangene Menge sell_tx.fee_btc, nicht sell_tx.btc_amount.
    """
    sell_tx: Transaction
    matches: list[DisposalMatch] = field(default_factory=list)
    # Restmenge, der KEIN Anschaffungsgeschäft zugeordnet werden konnte (FiFo-Pool
    # lief mitten im Verkauf leer). > 0 heißt: für diesen Teil existiert weder
    # Anschaffungsdatum noch Einstandspreis — Haltedauer also unbekannt.
    unmatched_btc: Decimal = Decimal("0")
    kind: DisposalKind = DisposalKind.SELL
    # Nur bei kind=FEE: Tageskurs, zu dem der Gebührenanteil bewertet wurde.
    # None = kein Kurs verfügbar (Kurstabelle endet vor dem Datum) — dann ist der
    # Bestandsabgang gebucht, Erlös und Gewinn aber NICHT ermittelt.
    fee_price_per_btc: Decimal | None = None

    @property
    def disposed_btc(self) -> Decimal:
        """Menge, die den Bestand verlassen hat (bei Gebühren: die Gebühr selbst)."""
        return self.sell_tx.fee_btc if self.kind == DisposalKind.FEE else self.sell_tx.btc_amount

    @property
    def is_priced(self) -> bool:
        """False nur bei einer Gebühr ohne Kurs — Gewinn/Verlust dann nicht ermittelt."""
        return self.kind != DisposalKind.FEE or self.fee_price_per_btc is not None

    @property
    def price_per_btc(self) -> Decimal:
        """Kurs, zu dem der Abgang bewertet ist (0 = unentgeltlich oder unbekannt)."""
        if self.kind == DisposalKind.SELL:
            return self.sell_tx.eur_price_per_btc
        if self.kind == DisposalKind.FEE and self.fee_price_per_btc is not None:
            return self.fee_price_per_btc
        return Decimal("0")

    @property
    def proceeds_eur(self) -> Decimal:
        """Veräußerungserlös vor Gebühren (Verkauf) bzw. Wert des Gebührenanteils.
        0 bei unentgeltlicher Übertragung und bei Gebühr ohne Kurs."""
        if self.kind == DisposalKind.SELL:
            return self.sell_tx.eur_amount
        if self.kind == DisposalKind.FEE and self.fee_price_per_btc is not None:
            return self.sell_tx.fee_btc * self.fee_price_per_btc
        return Decimal("0")

    @property
    def is_fully_covered(self) -> bool:
        """True nur, wenn die GESAMTE veräußerte Menge FiFo-Lots zugeordnet wurde.

        Ein Leere-Test auf matches reicht nicht: läuft der Pool mitten im Verkauf
        leer, ist matches nicht leer, aber zu kurz — und all(m.is_tax_free) über
        die vorhandenen Lots würde eine Steuerfreiheit bescheinigen, die für die
        fehlende Menge nie berechnet wurde.
        """
        return bool(self.matches) and self.unmatched_btc <= Decimal("0")

    @property
    def total_btc_matched(self) -> Decimal:
        return sum((m.btc_used for m in self.matches), start=Decimal("0"))

    # start=Decimal("0") ist Pflicht: ohne ihn liefert sum() bei leerer
    # matches-Liste den int 0, und _r()/quantize() in tax_report.py stirbt
    # dann mit AttributeError (unzugeordneter Verkauf → kein Report).
    @property
    def total_gain_taxable(self) -> Decimal:
        return sum((m.gain_eur for m in self.matches if not m.is_tax_free), start=Decimal("0"))

    @property
    def total_gain_tax_free(self) -> Decimal:
        return sum((m.gain_eur for m in self.matches if m.is_tax_free), start=Decimal("0"))

    @property
    def total_gain(self) -> Decimal:
        return sum((m.gain_eur for m in self.matches), start=Decimal("0"))
