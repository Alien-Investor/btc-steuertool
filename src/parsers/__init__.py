"""Gemeinsame Warnungs-Sammlung aller Parser.

Grundsatz: Kein Parser verwirft steuerlich relevante Zeilen stillschweigend.
Was nicht als Transaktion verbucht wird und relevant sein könnte (z.B. ein
Verkaufstyp, den der Parser noch nicht kennt), landet hier als Warnung und
wird im Report und im GUI-Log sichtbar gemacht. Bekannte irrelevante Zeilen
(EUR-Einzahlungen, andere Assets, abgebrochene Trades) bleiben stumm.

Zweiter Grundsatz (Vertraulichkeit): Warnungen, die noKYC-Vorgänge betreffen,
dürfen NICHT in steuerreport_*.txt oder steuernachweis_*.txt landen — diese
Dateien gehen an Steuerberater und Finanzamt. Solche Warnungen werden mit
internal=True markiert und erscheinen nur im internen noKYC-Report und im
GUI-Log. Die offiziellen Dokumente bekommen stattdessen einen neutralen
Zähl-Hinweis.
"""
from __future__ import annotations


class ParserWarning:
    """Warnung mit Vertraulichkeits-Flag.

    Verhält sich in jeder String-Verwendung (f-Strings, str(), print) wie die
    reine Meldung — bestehende Konsumenten in tax_report/formal_report und der
    GUI-Bootstrap bleiben dadurch unverändert lauffähig.
    """

    __slots__ = ("msg", "internal")

    def __init__(self, msg: str, internal: bool = False) -> None:
        self.msg = msg
        self.internal = internal

    def __str__(self) -> str:
        return self.msg

    def __repr__(self) -> str:
        return f"ParserWarning({self.msg!r}, internal={self.internal})"

    def __eq__(self, other) -> bool:
        if isinstance(other, ParserWarning):
            return (self.msg, self.internal) == (other.msg, other.internal)
        return self.msg == other

    def __hash__(self) -> int:
        return hash(self.msg)


parser_warnings: list[ParserWarning] = []


def warn(msg: str, internal: bool = False) -> None:
    """internal=True → nur interner noKYC-Report + GUI-Log, nie Finanzamt."""
    parser_warnings.append(ParserWarning(msg, internal))


def reset_warnings() -> None:
    parser_warnings.clear()
