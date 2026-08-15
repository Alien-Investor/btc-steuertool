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

Dritter Grundsatz (Integrität): Warnungstexte enthalten roh übernommene
CSV-Zellen. Sie werden mit `_sanitize()` entschärft, BEVOR sie in ein Dokument
gelangen — sonst kann eine präparierte Zelle über Zeilenumbrüche und
leer rendernde Zeichen eigene Abschnitte in steuerreport/steuernachweis
vortäuschen (SA-012).
"""
from __future__ import annotations

import re
import unicodedata

# Länge, ab der eine Warnung gekappt wird. Die längste echte Meldung liegt bei
# ~200 Zeichen; alles darüber stammt aus einer CSV-Zelle, nicht aus unserem Text.
_MAX_WARNING_LEN = 400

# Zeichen, die als Leerraum RENDERN, für Python aber kein Whitespace sind
# (`str.isspace()` ist False). Genau damit ließ sich die Zeilenumbruch-Sperre
# von `para()` aushebeln: eine so gepolsterte Zeile gilt als ein einziges "Wort"
# und wird ungebrochen durchgereicht.
_BLANK_LOOKALIKES = {
    "⠀",  # BRAILLE PATTERN BLANK  (der im Audit belegte Fall)
    "ㅤ",  # HANGUL FILLER
    "ᅟ",  # HANGUL CHOSEONG FILLER
    "ᅠ",  # HANGUL JUNGSEONG FILLER
    "ﾠ",  # HALFWIDTH HANGUL FILLER
}

# 3+ gleiche Trennzeichen in Folge → auf drei kürzen. Verhindert, dass eine
# Zelle wie "="*76 als Abschnittstrennlinie durchgeht (im Audit ebenfalls belegt:
# ein Token ohne Whitespace umgeht die Umbruchbreite von para()).
_RULE_RUN = re.compile(r"([=\-_*#~+])\1{2,}")


def _sanitize(msg: str) -> str:
    """Macht einen Warnungstext für die Aufnahme in ein Dokument ungefährlich.

    Umlaute, ß und € müssen überleben — es wird nur entfernt, was unsichtbar
    ist oder Struktur vortäuscht.
    """
    text = unicodedata.normalize("NFC", str(msg))
    out: list[str] = []
    for ch in text:
        if ch.isspace():
            # \n, \r, \t, NBSP (U+00A0), U+3000, U+2028/29 → ein Leerzeichen
            out.append(" ")
        elif ch in _BLANK_LOOKALIKES:
            out.append(" ")
        elif unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            # Steuerzeichen und unsichtbare Formatzeichen: ZWSP (U+200B),
            # Word Joiner, BOM, Bidi-Overrides (U+202E dreht die Leserichtung um),
            # Tag-Zeichen (U+E0000-E007F), Surrogates, Private Use.
            continue
        else:
            out.append(ch)
    text = " ".join("".join(out).split())
    text = _RULE_RUN.sub(r"\1\1\1", text)
    if len(text) > _MAX_WARNING_LEN:
        text = text[: _MAX_WARNING_LEN - 1].rstrip() + "…"
    return text


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
    """internal=True → nur interner noKYC-Report + GUI-Log, nie Finanzamt.

    Sanitisiert hier am Choke-Point, nicht in den Senken: jede Warnung geht
    durch diese Funktion, die Senken (tax_report, formal_report, GUI-Log) sind
    mehrere und würden auseinanderlaufen.
    """
    parser_warnings.append(ParserWarning(_sanitize(msg), internal))


def reset_warnings() -> None:
    parser_warnings.clear()


def validate_header(
    fieldnames: list[str] | None,
    known: set[str],
    filename: str,
    hints: dict[str, str] | None = None,
) -> None:
    """Unbekannte Spalten in den manuellen CSVs hart ablehnen (SA2-02).

    `csv.DictReader` + `row.get(...)` ignoriert jede Spalte, die der Parser
    nicht liest. Eine vertippte oder aus der Schwesterdatei abgeschriebene
    Flag-Spalte fiele damit lautlos weg — und die beiden Flags haben
    INVERTIERTE Bedeutung (`kyc` in manual_buys, `no_kyc` in manual_sales).
    Wer `kyc=nein` in die Verkaufsdatei schreibt, meint "kein KYC", bekommt
    aber einen KYC-Verkauf: der Vorgang landet im offiziellen Report UND
    verbraucht ein fremdes FiFo-Lot. Beides bleibt ohne diese Prüfung stumm.

    Harter Fehler statt Warnung — analog zum bestehenden Pflichtfeld-Fehler.
    Bewusst wird die Schwester-Schreibweise NICHT stillschweigend akzeptiert:
    dabei müsste der Parser die Polarität raten, und genau das ist der Fehler,
    den diese Prüfung verhindern soll.
    """
    if fieldnames is None:
        raise ValueError(f"{filename}: Datei hat keine Kopfzeile.")

    seen = [f.strip() for f in fieldnames if f is not None and f.strip()]

    missing = [c for c in ("date", "btc_amount", "eur_amount") if c not in seen]
    if missing:
        raise ValueError(
            f"{filename}: Pflichtspalte(n) fehlen in der Kopfzeile: {', '.join(missing)}."
        )

    unknown = [f for f in seen if f not in known]
    if unknown:
        details = []
        for col in unknown:
            hint = (hints or {}).get(col.strip().lower())
            details.append(f"'{col}'" + (f" ({hint})" if hint else ""))
        raise ValueError(
            f"{filename}: unbekannte Spalte(n) in der Kopfzeile: {'; '.join(details)}. "
            f"Erlaubt sind: {', '.join(sorted(known))}. "
            f"Bitte Kopfzeile korrigieren — eine unbekannte Spalte wird sonst "
            f"kommentarlos ignoriert."
        )
