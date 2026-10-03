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


class FileRef:
    """Ein Dateiname, der nur im internen Kanal ausgeschrieben werden darf (SA2-06).

    Dateinamen sind private Labels aus der Ablage des Nutzers: Wallet-Namen,
    aber auch Broker-Namen wie `robosats-export.csv`, die allein schon eine
    noKYC-Plattform benennen. In einem Dokument, das unter Klarnamen ans
    Finanzamt geht, haben sie nichts zu suchen — dieselbe Begründung, mit der
    die BitBox-Wallet-Namen aus dem Steuernachweis geflogen sind (SA-016).

    Bewusst KEINE pauschale Regex über die fertige Meldung: die würde auch die
    eigenen Textbausteine treffen („bitte als manual_sales.csv erfassen", die
    Liste der erwarteten Dateinamen) und genau deren einzigen nützlichen Inhalt
    zerstören. Redigiert wird nur der eingesetzte Wert, nie unser eigener Text.
    """

    __slots__ = ("name", "placeholder")

    def __init__(self, name, placeholder: str = "eine der eingelesenen Dateien") -> None:
        self.name = str(name)
        self.placeholder = placeholder

    def __str__(self) -> str:
        return self.name


class ParserWarning:
    """Warnung mit Vertraulichkeits-Flag und redigierter Zweitfassung.

    `str()` liefert die REDIGIERTE Fassung — absichtlich fail-safe: wer eine
    Senke übersieht, verliert einen Dateinamen in der Anzeige, statt ihn ins
    Finanzamt-Dokument zu schreiben. Die volle Fassung gibt es nur über `.full`
    (interner Report, GUI-Log, CLI-Ausgabe — alles Kanäle, die nur der Nutzer
    selbst sieht).

    `year` grenzt eine Warnung auf ein Steuerjahr ein; None heißt „betrifft
    alle Jahre" (Datei-Ebene, z.B. eine nicht geladene Datei).
    """

    __slots__ = ("msg", "internal", "msg_public", "year")

    def __init__(self, msg: str, internal: bool = False,
                 msg_public: str | None = None, year: int | None = None) -> None:
        self.msg = msg
        self.internal = internal
        self.msg_public = msg if msg_public is None else msg_public
        self.year = year

    def __str__(self) -> str:
        return self.msg_public

    @property
    def full(self) -> str:
        """Fassung mit Dateinamen — nur für Kanäle, die der Nutzer selbst sieht."""
        return self.msg

    def __repr__(self) -> str:
        return f"ParserWarning({self.msg!r}, internal={self.internal}, year={self.year})"

    def __eq__(self, other) -> bool:
        if isinstance(other, ParserWarning):
            return (self.msg, self.internal) == (other.msg, other.internal)
        return self.msg == other

    def __hash__(self) -> int:
        return hash(self.msg)


parser_warnings: list[ParserWarning] = []

# Zeilen aus transfer_zuordnung.csv (manuelle Übertrags-Zuordnung, BMF Rn. 90).
# Wie parser_warnings je Lauf gesammelt: load_all_transactions füllt, run_engine
# liest — so bleibt der GUI-Bootstrap unverändert (er ruft nur beide auf).
manual_links: list = []

# Quellen aus dem Sammelimport (CoinTracking/Blockpit): Kontoname → Herkunft
# („CoinTracking-Export"). Der Steuernachweis listet sie unter „Datenquellen";
# wie parser_warnings je Lauf gefüllt und in reset_warnings geleert.
aggregate_sources: dict[str, str] = {}


def warn(msg: str, *, internal: bool, year: int | None = None) -> None:
    """internal=True → nur interner noKYC-Report + GUI-Log, nie Finanzamt.

    `internal` ist PFLICHT und hat bewusst keinen Standardwert (H1): der alte
    Standard `False` hiess „sichtbar fuers Finanzamt", man bekam ihn also durchs
    Vergessen. Genau daraus entstand SA2-06. Jetzt scheitert eine unklassifizierte
    Warnung sofort mit TypeError, statt still im falschen Kanal zu landen.

    Sanitisiert hier am Choke-Point, nicht in den Senken: jede Warnung geht
    durch diese Funktion, die Senken (tax_report, formal_report, GUI-Log) sind
    mehrere und würden auseinanderlaufen.
    """
    _append_warning(ParserWarning(_sanitize(msg), internal, year=year))


# Länge, ab der ein EINGESETZTER Wert gekappt wird (H2). _MAX_WARNING_LEN kappt
# erst die fertige Meldung — eine überlange CSV-Zelle könnte bis dahin unseren
# eigenen Text hinausdrängen. Hier wird der Wert gekappt, nicht die Meldung.
_MAX_CELL_LEN = 80


def _cell(value) -> str:
    text = str(value)
    return text if len(text) <= _MAX_CELL_LEN else text[: _MAX_CELL_LEN - 1] + "…"


def make_warning(msg: str, *, internal: bool, year: int | None = None) -> ParserWarning:
    """Sanitisierte ParserWarning für Erzeuger außerhalb der Parser (H3).

    `fifo_engine` sammelt eigene Warnungen und baute `ParserWarning` bisher direkt —
    damit lief es an `_sanitize()` vorbei und widersprach der Zusage dieses Moduls,
    dass es genau einen Choke-Point gibt.
    """
    return ParserWarning(_sanitize(msg), internal, year=year)


def warn_fmt(template: str, *, internal: bool, year: int | None = None, **values) -> None:
    """Wie warn(), aber FileRef-Werte werden im offiziellen Kanal neutralisiert.

    Die Vorlage wird zweimal gefüllt: einmal mit den echten Werten (interner
    Kanal), einmal mit den Platzhaltern der FileRefs (Finanzamt-Kanal). Alles,
    was kein FileRef ist, bleibt in beiden Fassungen identisch — unsere eigenen
    Textbausteine werden also nie angetastet.
    """
    _append_warning(make_warning_fmt(template, internal=internal, year=year, **values))


def make_warning_fmt(template: str, *, internal: bool, year: int | None = None,
                     **values) -> ParserWarning:
    """Wie warn_fmt(), liefert die Warnung aber zurück statt sie zu sammeln —
    für Erzeuger außerhalb der Parser (Übertrags-Zuordnung, Engine)."""
    full = {k: _cell(v) for k, v in values.items()}
    public = {k: _cell(v.placeholder if isinstance(v, FileRef) else v)
              for k, v in values.items()}
    return ParserWarning(
        _sanitize(template.format(**full)),
        internal,
        msg_public=_sanitize(template.format(**public)),
        year=year,
    )


def warn_both(full: str, public: str, *, internal: bool, year: int | None = None) -> None:
    """Warnung mit eigener Fassung je Kanal: `full` (interner Report, GUI-Log, CLI) und
    `public` (Finanzamt-Dokumente). Für Meldungen, die einen Dateinamen UND einen
    längeren Text tragen — warn_fmt kürzt eingesetzte Werte auf 80 Zeichen."""
    _append_warning(ParserWarning(_sanitize(full), internal, msg_public=_sanitize(public), year=year))


def reset_warnings() -> None:
    parser_warnings.clear()
    manual_links.clear()
    aggregate_sources.clear()
    reset_suppressed()


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


# ───────────────────────── Gemeinsames Leser-Grundgerüst (Parser-Audit 03.10.2026) ─────────────────────────
#
# Fast alle Funde des Audits hatten eine Ursache: Die Parser lasen Spalten mit
# `row.get("Spalte", "")`. Eine umbenannte Spalte oder eine BOM am Dateianfang
# machte daraus still „leer" oder 0 — ganze Dateien verschwanden (Pocket, Bison,
# Swissquote), Käufe standen mit 0 BTC im Report (Strike), Gebühren wurden 0.
# Deshalb liest jetzt jeder Parser über `read_rows`: BOM-tolerant, Pflichtspalten
# hart geprüft, Feldanzahl je Zeile geprüft, Zeilenumbruch im Feld (nicht
# geschlossenes Anführungszeichen verschluckt sonst den Dateirest) hart geprüft,
# jede Meldung mit Datei und Zeile.

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

LINE_KEY = "__zeile__"   # Zeilennummer der Datei, von read_rows in jede Zeile gelegt

# Ab hier werden Warnungen nur noch gezählt (B6): 200.000 unbekannte Zeilen
# erzeugten sonst 200.000 Warnobjekte und einen 15-MB-Report je Jahr.
_MAX_WARNINGS = 1000
_suppressed = 0


def _append_warning(w: ParserWarning) -> None:
    global _suppressed
    if len(parser_warnings) < _MAX_WARNINGS:
        parser_warnings.append(w)
        return
    _suppressed += 1
    parser_warnings[-1] = ParserWarning(
        f"{_suppressed} weitere Warnung(en) nicht angezeigt (Grenze {_MAX_WARNINGS}) — "
        f"die eingelesenen Dateien enthalten massenhaft nicht verarbeitbare Zeilen, bitte prüfen.",
        internal=False,
    )


def read_rows(filepath: Path, *, label: str, required: tuple[str, ...] | list[str] = (),
              delimiter: str = ",", encodings: tuple[str, ...] = ("utf-8-sig",),
              comment: str | None = None) -> tuple[list[dict], list[str]]:
    """Liest eine CSV vollständig als Liste von Zeilen-Dicts (Schlüssel und Werte
    getrimmt, zusätzlich LINE_KEY = Zeilennummer) und gibt die Kopfzeile zurück.

    `encodings` werden der Reihe nach probiert (Swissquote: UTF-8, sonst Windows-1252).
    `comment`: einspaltige Zeilen, die damit beginnen, werden übersprungen (Sparrow hängt
    „# Historical EUR values …“ ans Dateiende). Leere Zeilen überspringt csv ohnehin.
    Jeder Fehler ist ein ValueError, der Datei und Zeile nennt — der Dateiname ist
    hier richtig: Fehler brechen den Lauf ab, bevor ein Dokument entsteht, und
    erreichen nur den Nutzer (CLI, GUI-Fehlerkarte; der Bug-Report übernimmt die
    Meldung nicht).
    """
    name = Path(filepath).name
    data = Path(filepath).read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]   # UTF-8-BOM auch vor einer Windows-1252-Datei abstreifen
    text = None
    last_err: UnicodeDecodeError | None = None
    for enc in encodings:
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError as e:
            last_err = e
    if text is None:
        hint = " Die Datei sieht nach UTF-16 aus (Excel-Export als Unicode-Text)." if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ""
        raise ValueError(
            f"{label} {name}: Datei ist nicht {' oder '.join(e.replace('-sig', '') for e in encodings)} kodiert "
            f"(Byte 0x{last_err.object[last_err.start]:02x} an Position {last_err.start}).{hint} "
            f"Bitte den Export unverändert verwenden oder als UTF-8 speichern."
        )

    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        fieldnames = reader.fieldnames
    except csv.Error as e:
        raise ValueError(f"{label} {name}: Kopfzeile nicht lesbar ({e}).") from None
    if not fieldnames or not any((h or "").strip() for h in fieldnames):
        raise ValueError(f"{label} {name}: Datei hat keine Kopfzeile.")
    header = [(h or "").strip() for h in fieldnames]
    missing = [c for c in required if c not in header]
    if missing:
        raise ValueError(
            f"{label} {name}: Pflichtspalte(n) fehlen in der Kopfzeile: {', '.join(missing)}. "
            f"Gelesen: {', '.join(header[:20])}. Hat der Anbieter das Exportformat geändert oder wurde "
            f"die Datei in einer Tabellenkalkulation umbenannt? Ohne diese Prüfung ginge die Datei still verloren."
        )
    if len(set(header)) != len(header):
        # Doppelte Spaltennamen eindeutig machen („Cur.", „Cur.#2", „Cur.#3" — die
        # CoinTracking-Handelsliste hat drei Spalten „Cur."). csv.DictReader würde
        # sonst still die letzte behalten.
        seen: dict[str, int] = {}
        unique = []
        for h in header:
            seen[h] = seen.get(h, 0) + 1
            unique.append(h if seen[h] == 1 else f"{h}#{seen[h]}")
        header = unique
        reader.fieldnames = header

    rows: list[dict] = []
    n_cols = len(fieldnames)
    key0 = reader.fieldnames[0]
    try:
        for raw in reader:
            line = reader.line_num
            first = raw.get(key0)
            if (comment and first is not None and first.lstrip().startswith(comment)
                    and None not in raw and all(v is None for k, v in raw.items() if k != key0)):
                continue
            if None in raw:
                extra = raw.pop(None)
                raise ValueError(
                    f"{label} {name} Zeile {line}: {n_cols + len(extra)} Felder statt {n_cols} — "
                    f"ein Trennzeichen im Text ohne Anführungszeichen?"
                )
            if any(v is None for v in raw.values()):
                got = sum(1 for v in raw.values() if v is not None)
                raise ValueError(
                    f"{label} {name} Zeile {line}: {got} Felder statt {n_cols} — Zeile unvollständig "
                    f"oder ein Anführungszeichen nicht geschlossen?"
                )
            row = {(k or "").strip(): v.strip() for k, v in raw.items()}
            if any("\n" in v or "\r" in v for v in row.values()):
                raise ValueError(
                    f"{label} {name} Zeile {line}: Zeilenumbruch innerhalb eines Feldes — ein Anführungszeichen "
                    f"nicht geschlossen? Ab hier würde der Rest der Datei als ein Feld gelesen und verschwände."
                )
            row[LINE_KEY] = line
            rows.append(row)
    except csv.Error as e:
        raise ValueError(f"{label} {name} Zeile {reader.line_num}: CSV-Fehler ({e}) — Anführungszeichen prüfen.") from None
    return rows, header


_AMOUNT_LIMIT = Decimal("1e15")


def parse_amount(value: str | None, *, label: str, filename: str, line: int | str, field: str) -> Decimal:
    """Zahl aus einer CSV-Zelle. Leer und „-" (CoinTracking) sind 0.

    Dezimaltrenner ist der Punkt (alle unterstützten Exporte). Ein Komma gilt nur
    dann als Dezimaltrenner, wenn kein Punkt vorkommt, es genau einmal steht und
    nicht wie ein Tausendertrenner aussieht („2,500" ist mehrdeutig und wird
    abgelehnt — bisher wurde daraus still 2.5, Faktor 1000). NaN/Infinity und
    Werte ab 1e15 werden hier abgelehnt, nicht erst in der Engine (B3).
    """
    text = (value or "").strip()
    if text in ("", "-"):
        return Decimal("0")
    where = f"{' '.join(x for x in (label, filename) if x)} Zeile {line}, Spalte '{field}': '{text}'"
    if "," in text:
        if "." in text or text.count(",") > 1:
            raise ValueError(f"{where} enthält Komma und Punkt — Tausendertrennzeichen? Zahlen bitte ohne Gruppierung, Dezimaltrenner Punkt.")
        frac = text.split(",")[1]
        if len(frac) == 3 and frac.isdigit():
            raise ValueError(f"{where} ist mehrdeutig (Dezimalkomma oder Tausendertrenner?) — Zahlen bitte mit Punkt als Dezimaltrenner.")
        text = text.replace(",", ".")
    try:
        d = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{where} ist keine Zahl.") from None
    if not d.is_finite():
        raise ValueError(f"{where} ist keine endliche Zahl.")
    if abs(d) >= _AMOUNT_LIMIT:
        raise ValueError(f"{where} ist unplausibel groß.")
    return d


def amount(row: dict, field: str, *, label: str, filename: str) -> Decimal:
    """parse_amount für eine Zeile aus read_rows (Zeilennummer aus LINE_KEY)."""
    return parse_amount(row.get(field), label=label, filename=filename, line=row.get(LINE_KEY, "?"), field=field)


def parse_iso_datetime(value: str | None, *, label: str, filename: str, line: int | str, field: str) -> datetime:
    """ISO-8601-Zeitstempel MIT Zeitzone → UTC. „Z" wird akzeptiert (Python 3.10 kennt es nicht).

    Ohne Offset harter Fehler (A8): `fromisoformat(...).astimezone(utc)` nähme sonst die
    Systemzeitzone — derselbe Export ergäbe im Browser und im CLI verschiedene Steuerjahre.
    """
    text = (value or "").strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    where = f"{' '.join(x for x in (label, filename) if x)} Zeile {line}, Spalte '{field}': '{value}'"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"{where} ist kein ISO-8601-Zeitstempel (erwartet z.B. 2024-03-15T14:22:10+01:00).") from None
    if dt.tzinfo is None:
        raise ValueError(
            f"{where} hat keine Zeitzone — Datei in einer Tabellenkalkulation umformatiert? "
            f"Ohne Zeitzone hinge das Steuerjahr von der Systemzeit ab; bitte den Original-Export verwenden."
        )
    return dt.astimezone(timezone.utc)


def reset_suppressed() -> None:
    global _suppressed
    _suppressed = 0
