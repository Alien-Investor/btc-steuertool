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

    def __post_init__(self):
        # Sicherstellen dass alle Decimal-Felder auch Decimal sind
        for f in ("btc_amount", "eur_amount", "eur_price_per_btc", "fee_eur"):
            val = getattr(self, f)
            if not isinstance(val, Decimal):
                object.__setattr__(self, f, Decimal(str(val)))
        # Negative Beträge hart ablehnen — ein Vorzeichen-Tippfehler (z.B. in
        # manual_buys.csv) würde sonst die FiFo-Kette lautlos korrumpieren
        if self.type in (TxType.BUY, TxType.SELL):
            if self.btc_amount < 0 or self.eur_amount < 0 or self.fee_eur < 0:
                raise ValueError(
                    f"{self.source} {de_date(self.date)}: negativer Betrag bei {self.type.value} "
                    f"(btc={self.btc_amount}, eur={self.eur_amount}, fee={self.fee_eur}) — "
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
    """Komplettes Ergebnis eines Verkaufs nach FiFo-Auflösung."""
    sell_tx: Transaction
    matches: list[DisposalMatch] = field(default_factory=list)

    @property
    def total_gain_taxable(self) -> Decimal:
        return sum(m.gain_eur for m in self.matches if not m.is_tax_free)

    @property
    def total_gain_tax_free(self) -> Decimal:
        return sum(m.gain_eur for m in self.matches if m.is_tax_free)

    @property
    def total_gain(self) -> Decimal:
        return sum(m.gain_eur for m in self.matches)
