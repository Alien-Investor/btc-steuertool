"""Diagnose für Bug-Reports (v1.4): was der Nutzer dem Autor schicken kann, ohne private Daten.

Die App stellt zusammen, WAS geladen wurde und WAS schiefging — nie, WELCHE Daten:
keine Dateinamen (oft private Wallet-Namen), keine Wallet- oder Kontonamen, keine Beträge,
Daten oder Uhrzeiten, keine Transaktions-IDs, Adressen oder xpubs, kein Hinweis auf noKYC-
Bestände. Die Schwärzung liegt hier, an einer Stelle — die GUI liefert nur Rohangaben und zeigt
das Ergebnis vor dem Senden vollständig an. Support gibt es nur zu Technik und Format.

Zwei Prinzipien (Release-Audit v1.4, Runde 3):
- **Positivliste statt Negativliste, wo es geht.** Die erste Zeile einer nicht erkannten Datei
  kann in Wahrheit eine Datenzeile sein (Bank-Export: Name, IBAN, E-Mail). Sie wird nie als Text
  übertragen, sondern nur als Struktur: Feldanzahl, Trennzeichen und je Feld der Spaltenname,
  wenn er ausschließlich aus bekannten Wörtern besteht — sonst „<feld>“.
- **Meldungen: Ziffern sind verdächtig.** Erlaubt bleiben nur Jahreszahlen (2009–2099), die
  Zeilennummer nach „Zeile“ und kleine Zählungen; Beträge, Daten, Uhrzeiten, IDs, Adressen und
  Zellinhalte in Anführungszeichen werden ersetzt. Meldungen aus Dateien, die noKYC sein können,
  und zur Trennung der Bestände erscheinen nur als ein allgemeiner Satz, der auch bei anderen
  privaten Meldungen (manuelle Dateien, Zuordnung) steht — er verrät also nichts.

Grundsatz: lieber zu viel schwärzen. Eine Rückfrage kostet wenig; ein Betrag oder Wallet-Name
im Postfach des Autors lässt sich nicht zurückholen.
"""
from __future__ import annotations

import re
import unicodedata

from .parsers import _sanitize

TITLE = "BTC Steuertool – Diagnose (ohne Dateinamen, Beträge, Daten, Adressen und Wallet-Namen)"

# Ein Satz für alle Meldungen, die private Angaben tragen können (siehe Modul-Doku)
PRIVATE_TEXT = "Meldung enthält private Angaben (Details nur im lokalen Log)."

_CLASS_WORDS = re.compile(r"no[\s_-]?kyc|p2p|bisq|robosats|hodl\s*hodl|peach|agoradesk|bargeld|"
                          r"manual_buys|manual_sales|transfer_zuordnung", re.IGNORECASE)

# Wörter, aus denen ein Spaltenname bestehen darf (klein, ohne Satzzeichen). Alles andere → <feld>.
_HEADER_WORDS = set("""
date time datum zeit uhrzeit timestamp created updated completed executed utc local timezone tz
type typ kind art side richtung direction operation operations transaction transactions transaktion transaktionen
tx txid txhash hash id ids reference ref order auftrag trade handel handels nr no number nummer
amount amounts betrag menge quantity qty volume anzahl value wert values total summe gesamt net brutto netto
fee fees gebühr gebühren gebuehr commission kosten cost costs spread
price preis rate kurs market markt pair paar symbol ticker asset assets coin coins currency currencies währung waehrung
unit units einheit eur usd chf btc sat sats satoshi xbt fiat crypto
buy sell kauf verkauf bought sold incoming outgoing in out received sent receive send deposit withdrawal withdraw
from to von nach source destination ziel quelle sender recipient empfänger
account konto wallet exchange integration platform plattform network netzwerk chain
address adresse addresses label labels note notes notiz notizen comment comments kommentar description beschreibung memo
status state confirmed confirmations bestätigt balance saldo stand
name group gruppe trade-group optional of the at per and or
""".split())

_MONTH = (r"(?:jan(?:uar|uary)?|feb(?:ruar|ruary)?|m(?:ä|ae)rz|mar(?:ch)?|apr(?:il)?|mai|may|jun(?:e|i)?|"
          r"jul(?:y|i)?|aug(?:ust)?|sep(?:t(?:ember)?)?|o[ck]t(?:ober)?|nov(?:ember)?|de[cz](?:ember)?)")
# Bekannte Wörter mit Ziffern, die keine IDs sind
_KEEP = {"21bitcoin"}

_RULES = [
    # Zellinhalte in Anführungszeichen
    (re.compile(r"'[^']*'"), "'…'"),
    (re.compile(r"„[^“]*“"), "„…“"),
    (re.compile(r"\"[^\"]*\""), '"…"'),
    # E-Mail, IBAN
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "<email>"),
    (re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[0-9A-Z]{4}){2,7}(?:[ ]?[0-9A-Z]{1,4})?\b"), "<iban>"),
    # Lightning, xpubs, Adressen (alle Netze), Hashes
    (re.compile(r"\bln(?:bc|tb|bcrt)[0-9a-z]{10,}", re.IGNORECASE), "<lightning>"),
    (re.compile(r"\b(?:[xyztuv]pub|[XYZTUV]pub|npub|nsec)[1-9A-HJ-NP-Za-km-z0-9]{4,}"), "<schlüssel>"),
    (re.compile(r"\b(?:bc1|tb1|bcrt1)[0-9a-z]{6,}\b", re.IGNORECASE), "<adresse>"),
    (re.compile(r"\b[123mn][1-9A-HJ-NP-Za-km-z]{25,39}\b"), "<adresse>"),
    (re.compile(r"\b0x[0-9a-f]{6,}\b", re.IGNORECASE), "<adresse>"),
    (re.compile(r"\b[0-9a-f]{12,}\b", re.IGNORECASE), "<id>"),
    # gemischte Buchstaben-Ziffern-Folgen ab 6 Zeichen: IDs, Referenzen
    (re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{6,}\b"),
     lambda m: m.group(0) if m.group(0).casefold() in _KEEP else "<id>"),
    # Daten → nur das Jahr (ISO, deutsch, US, englisch mit Monatsnamen, kompakt)
    (re.compile(r"\b(20\d\d|19\d\d)-\d{1,2}-\d{1,2}(?:[T ]\d{1,2}[:.]\d{2}(?:[:.]\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?"), r"\1"),
    (re.compile(r"\b(20\d\d)/\d{1,2}/\d{1,2}\b"), r"\1"),
    (re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-](\d{4})\b"), r"\1"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/(\d{2})\b"), "<datum>"),
    (re.compile(rf"\b\d{{1,2}}\.?\s+{_MONTH}\.?(?:\s+(\d{{4}}))?\b", re.IGNORECASE), lambda m: m.group(1) or "<datum>"),
    (re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?(?:\s+(\d{{4}}))?\b", re.IGNORECASE), lambda m: m.group(1) or "<datum>"),
    (re.compile(rf"\b{_MONTH}\.?\s+(\d{{4}})\b", re.IGNORECASE), r"\1"),
    (re.compile(r"\b(20\d\d)(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\b"), r"\1"),
    # Uhrzeiten
    (re.compile(r"\b\d{1,2}[:.h]\d{2}(?:[:.]\d{2})?\s*(?:am|pm|uhr)?\b", re.IGNORECASE), "<zeit>"),
    # Beträge: Dezimalzahlen (auch „1.“, „,5“, „1.234,56“), Zahlen mit Einheit, Exponenten
    (re.compile(r"-?(?<![\w.,])(?:\d{1,3}(?:[.  ']\d{3})+|\d+)?[.,]\d+(?:e[+-]?\d+)?(?![\w])", re.IGNORECASE), "<betrag>"),
    (re.compile(r"-?\b\d+[.,](?=\s|$|[^\w])"), "<betrag>"),
    (re.compile(r"-?\b\d+(?:[  ]\d{3})*\s*(?:btc|xbt|eur|€|usd|\$|chf|sats?|satoshis?|mbtc|msat)\b", re.IGNORECASE), "<betrag>"),
    (re.compile(r"-?\b\d+e[+-]?\d+\b", re.IGNORECASE), "<betrag>"),
]
_ZEILE = re.compile(r"\b(Zeile|line|Zeilen)\s+(\d+)", re.IGNORECASE)
_NUM = re.compile(r"(?<![\w<#])-?\d+(?![\w>#])")

_MAX_LINE = 300
_MAX_WARNINGS = 30


def _norm(text: str) -> str:
    return _sanitize(unicodedata.normalize("NFC", str(text or ""))).casefold()


def _numbers(s: str) -> str:
    """Restliche Zahlen: Jahre 2009–2099 und Zählungen bis 999 bleiben, alles andere → <zahl>.
    Die Zeilennummer nach „Zeile“ ist vorher geschützt."""
    def keep(m):
        v = m.group(0).lstrip("-")
        n = int(v)
        if len(v) == 4 and 2009 <= n <= 2099:
            return m.group(0)
        if len(v) <= 3 and not m.group(0).startswith("-"):
            return m.group(0)
        return "<zahl>"
    return _NUM.sub(keep, s)


def _name_pattern(names) -> re.Pattern | None:
    """Eine kompilierte Alternation aller Namen (längste zuerst), nur an Wortgrenzen —
    ein kurzer Stamm wie „ab“ zerlegt sonst Transaktions-IDs (Audit R3-B4)."""
    variants = set()
    for n in names:
        for v in (_norm(n), _norm(n).replace(" ", "")):
            if len(v) >= 2:
                variants.add(v)
    if not variants:
        return None
    alt = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<![0-9a-z])(?:{alt})(?![0-9a-z])", re.IGNORECASE)


def redact(text: str, names=(), *, private: bool = False, _pattern=None) -> str:
    """Eine Meldung ohne private Angaben — Positivliste (Audit v1.4, Runde 4).

    Stehen bleiben nur Wörter, die in den Meldungstexten des Tools selbst vorkommen (Wörterbuch aus
    den Zeichenketten in src/), Jahreszahlen 2009–2099 und die Zeilennummer nach „Zeile“. Jedes
    andere Wort wird „…“, jede andere Zahl „<n>“ — ein Name, Betrag, Datum oder Zellinhalt kann so
    in keiner Schreibweise durchkommen (ß, Apostroph, Datum im Dateinamen, „Gelesen: <Datenzeile>“).
    `private=True` (PrivateError) und Meldungen zur Bestandstrennung → nur der allgemeine Satz."""
    if private:
        return PRIVATE_TEXT
    s = _norm_keep_case(text)
    if _CLASS_WORDS.search(s):
        return PRIVATE_TEXT
    pattern = _pattern if _pattern is not None else _name_pattern(names)
    if pattern is not None:
        s = pattern.sub(" ", s)
    vocab = _vocabulary()
    out: list[str] = []
    last_word = ""
    for m in re.finditer(r"[^\W_]+|\s+|[\W_]", s):
        tok = m.group(0)
        if tok.isdigit():
            if last_word in ("zeile", "zeilen", "line") and len(tok) <= 7:
                out.append(tok)
            elif len(tok) == 4 and 2009 <= int(tok) <= 2099:
                out.append(tok)
            else:
                out.append("<n>")
            last_word = ""
        elif tok[0].isalnum():
            w = tok.casefold()
            out.append(tok if (tok.isalpha() and w in vocab and w not in _MONTH_WORDS) else "…")
            last_word = w if tok.isalpha() else ""
        else:
            out.append(tok)
            if not tok.isspace():
                last_word = ""
    s = "".join(out)
    # Folgen von Platzhaltern zusammenziehen („… …“, „'…'s …“, „<n>.<n>“)
    s = re.sub(r"(?:…|<n>)(?:[\s'’\"„“‚‘,.:;/()_+\-]*(?:…|<n>))+", lambda m: "<n>" if "…" not in m.group(0) else "…", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > _MAX_LINE:
        s = s[: _MAX_LINE - 1] + "…"
    return s


_MONTH_WORDS = {
    "jan", "januar", "january", "feb", "februar", "february", "mär", "märz", "maerz", "mar", "march", "apr",
    "april", "mai", "may", "jun", "juni", "june", "jul", "juli", "july", "aug", "august", "sep", "sept",
    "september", "okt", "oct", "oktober", "october", "nov", "november", "dez", "dec", "dezember", "december",
}
_VOCAB: set[str] | None = None


def _vocabulary() -> set[str]:
    """Alle Wörter aus Zeichenketten im Quellcode (src/**/*.py) — die Sprache der eigenen Meldungen.
    Wird beim ersten Aufruf gebildet; in der App liegen dieselben Dateien im Worker-Dateisystem."""
    global _VOCAB
    if _VOCAB is None:
        import ast
        from pathlib import Path
        words: set[str] = set()
        for f in Path(__file__).resolve().parent.rglob("*.py"):
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    words.update(w.casefold() for w in re.findall(r"[^\W\d_]+", node.value))
        _VOCAB = words
    return _VOCAB


def _norm_keep_case(text: str) -> str:
    return _sanitize(unicodedata.normalize("NFC", str(text or "")))


def header_shape(line: str) -> str:
    """Erste Zeile einer nicht erkannten Datei nur als Struktur (Positivliste, Audit R3-B1)."""
    raw = _norm_keep_case(line)
    delim = max((",", ";", "\t", "|"), key=raw.count)
    fields = [f.strip().strip('"').strip("'").strip() for f in raw.split(delim)] if raw else []
    shown = []
    for f in fields[:40]:
        words = [w for w in re.split(r"[^0-9a-zäöüß#]+", f.casefold()) if w]
        ok = (0 < len(f) <= 40 and words and all(w in _HEADER_WORDS or w == "#" for w in words)
              and not any(ch.isdigit() for ch in f))
        shown.append(f if ok else "<feld>")
    more = f", … ({len(fields) - 40} weitere)" if len(fields) > 40 else ""
    name = {",": "Komma", ";": "Semikolon", "\t": "Tab", "|": "Senkrechtstrich"}[delim]
    return f"{len(fields)} Felder, Trennzeichen {name}: " + ", ".join(shown) + more


def build(info: dict) -> str:
    """Diagnose-Text aus den Rohangaben der GUI.

    info: platform, lang, files=[{label, lines, kb, hidden, header}], error, error_private, ran,
    warnings (öffentliche Fassung), names (Datei-, Wallet- und Kontonamen, nur zum Schwärzen —
    erscheinen nie im Ergebnis). `hidden`: Datei eines Typs, der noKYC sein kann — nur gezählt.
    """
    names = [str(n) for n in info.get("names", [])]
    for n in list(names):
        names.append(n.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    pattern = _name_pattern(names)
    out = [TITLE, ""]
    out.append(f"Plattform: {redact(info.get('platform', '?'))} · Sprache: {redact(info.get('lang', '?'))}")
    files = info.get("files", [])
    shown = [f for f in files if not f.get("hidden")]
    hidden = len(files) - len(shown)
    out.append("")
    out.append(f"Dateien ({len(files)}):")
    groups: dict[str, list] = {}
    for f in shown:
        groups.setdefault(str(f.get("label", "?")), []).append(f)
    for label, fs in groups.items():
        lab = redact(label, _pattern=pattern)
        if len(fs) == 1:
            f = fs[0]
            out.append(f"  - {lab}: {int(f.get('lines', 0))} Zeilen, {_size(f.get('kb', 0))}")
        else:
            out.append(f"  - {lab}: {len(fs)} Dateien, zusammen {sum(int(f.get('lines', 0)) for f in fs)} Zeilen")
    if hidden:
        out.append(f"  - weitere Dateien (nicht aufgeschlüsselt): {hidden}")
    headers = [f for f in shown if f.get("header")]
    if headers:
        out.append("")
        out.append("Nicht erkannte Dateien – Aufbau der ersten Zeile (nur bekannte Spaltennamen):")
        for f in headers:
            out.append(f"  - {header_shape(f['header'])}")
    out.append("")
    error = info.get("error")
    if error:
        out.append(f"Letzte Berechnung: Abbruch — {redact(error, private=bool(info.get('error_private')), _pattern=pattern)}")
    elif info.get("ran"):
        out.append("Letzte Berechnung: ohne Abbruch")
    else:
        out.append("Letzte Berechnung: keine")
    warnings = []
    for w in info.get("warnings", []):
        r = redact(w, _pattern=pattern)
        if r not in warnings:
            warnings.append(r)
    if warnings:
        out.append("")
        out.append(f"Hinweise der letzten Berechnung ({len(warnings)}, geschwärzt):")
        for r in warnings[:_MAX_WARNINGS]:
            out.append(f"  - {r}")
        if len(warnings) > _MAX_WARNINGS:
            out.append(f"  - … {len(warnings) - _MAX_WARNINGS} weitere")
    return "\n".join(out) + "\n"


def _size(kb) -> str:
    """Größe grob (Größenordnung reicht für Format-Fragen)."""
    kb = float(kb or 0)
    for limit, text in ((10, "unter 10 KB"), (100, "10–100 KB"), (1000, "100 KB–1 MB"), (10000, "1–10 MB")):
        if kb < limit:
            return text
    return "über 10 MB"
