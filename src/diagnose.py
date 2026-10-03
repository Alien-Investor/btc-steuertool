"""Diagnose für Bug-Reports (v1.4): was der Nutzer dem Autor schicken kann, ohne private Daten.

Die App stellt zusammen, WAS geladen wurde und WAS schiefging — nie, WELCHE Daten: keine
Dateinamen, Wallet- oder Kontonamen, Beträge, Daten, Uhrzeiten, Transaktions-IDs, Adressen,
Schlüssel, Labels, kein Hinweis auf noKYC-Bestände. Die Schwärzung liegt hier, an einer Stelle —
die GUI liefert nur Rohangaben und zeigt das Ergebnis vor dem Senden vollständig an. Support gibt
es nur zu Technik und Format.

Positivlisten statt Negativlisten (Release-Audit v1.4, Runden 3–5 — jede Negativliste hatte Lücken):
- **Meldungen:** stehen bleiben nur Wörter aus den Meldungsvorlagen des Tools selbst (Texte in
  `raise …(…)` und `warn*(…)` in src/, ohne Einzelbuchstaben, Zahlwörter, Monatsnamen),
  Jahreszahlen 2009–2099 und die Zeilennummer nach „Zeile“. Jedes andere Wort wird „…“, jede andere
  Zahl „<n>“. Inhalte in Anführungszeichen (Zellwerte, Labels, Wallet-Namen) werden immer ganz
  ersetzt; eine zitierte erste Zeile („Gelesen: …“) erscheint nur als Struktur.
- **Erste Zeile unbekannter Dateien:** nur Feldanzahl, Trennzeichen und je Feld der Spaltenname,
  wenn er ausschließlich aus bekannten Spaltenwörtern besteht — sonst „<feld>“.
- **noKYC:** Meldungen aus Dateien, die noKYC sein können (`parsers.PrivateError`), und alles mit
  Bestandstrennungs-Wörtern (noKYC, Bisq-Spalten, P2P-Plattformen …) erscheinen nur als ein
  allgemeiner Satz; solche Dateien werden nur gezählt.
Lieber zu viel schwärzen: eine Rückfrage kostet wenig, ein Name im Postfach des Autors ist nicht
zurückzuholen.
"""
from __future__ import annotations

import ast
import re
import unicodedata
from pathlib import Path

from .parsers import _sanitize

TITLE = "BTC Steuertool – Diagnose (ohne Dateinamen, Beträge, Daten, Adressen und Wallet-Namen)"
PRIVATE_TEXT = "Meldung enthält private Angaben (Details nur im lokalen Log)."

_CLASS_WORDS = re.compile(
    r"no[\s_-]?kyc|(?:kein|keine|ohne|non|without|no)[\s_-]*kyc|kyc[\s_-]*(?:frei|free|los)|p2p|coinjoin|"
    r"bisq|bsq|robosats|hodl\s*hodl|peach|agoradesk|lnp2p|bargeld|kaution|deposit|angebotstyp|offer\s*type|"
    r"handels-id|abweichung|deviation",
    re.IGNORECASE)

# Spaltenwörter für den Aufbau einer unbekannten ersten Zeile (klein). Alles andere → <feld>.
_HEADER_WORDS = set("""
date time datum zeit uhrzeit timestamp created updated completed executed utc local timezone tz
type typ kind art side richtung direction operation operations transaction transactions transaktion transaktionen
tx txid txhash hash id ids reference ref order auftrag trade nr no number nummer
amount amounts betrag menge quantity qty volume anzahl value wert values total summe gesamt net brutto netto
fee fees gebühr gebühren gebuehr commission kosten cost costs spread
price preis rate kurs market markt pair paar symbol ticker asset assets coin coins currency currencies währung waehrung
unit units einheit eur usd chf btc sat sats satoshi xbt fiat crypto
buy sell kauf verkauf bought sold incoming outgoing in out received sent receive send withdrawal withdraw
from to von nach source destination ziel quelle sender recipient empfänger
account konto wallet exchange integration platform plattform network netzwerk chain
address adresse addresses label labels note notes notiz notizen comment comments kommentar description beschreibung memo
status state confirmed confirmations bestätigt balance saldo stand
name group gruppe optional of the at per and or
""".split())

_MONTH_WORDS = {
    "jan", "januar", "january", "feb", "februar", "february", "mär", "märz", "maerz", "mar", "march", "apr",
    "april", "mai", "may", "jun", "juni", "june", "jul", "juli", "july", "aug", "august", "sep", "sept",
    "september", "okt", "oct", "oktober", "october", "nov", "november", "dez", "dec", "dezember", "december",
}
# Nie aus dem Wörterbuch: Zahlwörter (Beträge in Worten) und Wörter, die als private Notiz taugen
_DENY = {"null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "hundert",
         "tausend", "mio", "million", "millionen", "half", "halb", "kind", "kinder", "gross", "groß",
         # Durchsicht der Liste (03.10.2026): taugen als private Notiz/Label
         "geschenk", "schenkung", "schenkers", "hingegebenen", "lightning", "diebstahl", "verlust", "zahltag", "ort"}
# Bekannte Wörter mit Ziffern, die keine IDs sind
_KEEP = {"21bitcoin"}
# Aufrufe, deren Texte Meldungsvorlagen sind
_MESSAGE_CALLS = {"warn", "warn_fmt", "warn_both", "make_warning", "make_warning_fmt", "wrn",
                  "ValueError", "PrivateError", "RuntimeError", "err"}
_MESSAGE_VARS = {"text", "msg", "message", "template", "hint", "extra", "where"}

_MAX_LINE = 300
_MAX_WARNINGS = 30
_VOCAB: set[str] | None = None


def _vocabulary() -> set[str]:
    """Wörter aus den Meldungsvorlagen in src/ (nicht aus Docstrings oder Kommentaren — die brachten
    „Hidden“, „Seed“, „Schwester“, „Berlin“ ins Wörterbuch, Audit R5-B5). In der App liegen dieselben
    Dateien im Worker-Dateisystem."""
    global _VOCAB
    if _VOCAB is None:
        words: set[str] = set()
        for f in Path(__file__).resolve().parent.rglob("*.py"):
            if f.name == "diagnose.py":
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                target = None
                if isinstance(node, ast.Raise) and node.exc is not None:
                    target = node.exc
                elif isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                    if name in _MESSAGE_CALLS:
                        target = node
                elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    # Meldungsbausteine in Variablen/Tabellen: template, hint, extra, _STAT_TEXT …
                    tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
                    ids = {t.id for t in tgts if isinstance(t, ast.Name)}
                    if any(i.lower() in _MESSAGE_VARS or any(k in i.upper() for k in ("TEXT", "MSG", "TEMPLATE"))
                           for i in ids):
                        target = node.value
                if target is None:
                    continue
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        words.update(w.casefold() for w in re.findall(r"[^\W\d_]+", sub.value))
        _VOCAB = {w for w in words if len(w) > 1 and w not in _MONTH_WORDS and w not in _DENY}
    return _VOCAB


def _norm(text) -> str:
    return _sanitize(unicodedata.normalize("NFC", str(text or "")))


def _name_pattern(names) -> re.Pattern | None:
    """Alle bekannten privaten Namen als eine Alternation (längste zuerst), nur an Wortgrenzen."""
    variants = set()
    for n in names:
        base = _norm(n)
        for v in (base, base.casefold(), base.lower(), base.replace(" ", "")):
            if len(v) >= 2:
                variants.add(v)
    if not variants:
        return None
    alt = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<![^\W_])(?:{alt})(?![^\W_])", re.IGNORECASE)


_QUOTED = re.compile(r"„[^“]*“|'[^']*'|\"[^\"]*\"|‚[^‘]*‘|«[^»]*»")
_READ_LINE = re.compile(r"(Gelesene Kopfzeile|Gelesen):\s*(.+?)(?=\.\s|\.$|$)", re.IGNORECASE)


def redact(text: str, names=(), *, private: bool = False, _pattern=None) -> str:
    """Eine Meldung ohne private Angaben (siehe Modul-Doku)."""
    if private:
        return PRIVATE_TEXT
    s = _norm(text)
    if _CLASS_WORDS.search(s):
        return PRIVATE_TEXT
    # zitierte erste Zeile → nur ihr Aufbau (R5-B2); Zitate → ganz ersetzt (R5-B1)
    s = _READ_LINE.sub(lambda m: f"{m.group(1)}: [{_shape_fields(m.group(2).split(','))}]", s)
    s = _QUOTED.sub(lambda m: m.group(0)[0] + "…" + m.group(0)[-1], s)
    pattern = _pattern if _pattern is not None else _name_pattern(names)
    if pattern is not None:
        s = pattern.sub(" ", s)
    vocab = _vocabulary()
    out: list[str] = []
    last_word = ""
    for m in re.finditer(r"<feld>|[^\W_]+|\s+|[\W_]", s):
        tok = m.group(0)
        if tok == "<feld>":
            out.append(tok)
        elif tok.isdigit():
            if last_word in ("zeile", "zeilen", "line") and len(tok) <= 7:
                out.append(tok)
            elif len(tok) == 4 and 2009 <= int(tok) <= 2099:
                out.append(tok)
            else:
                out.append("<n>")
            last_word = ""
        elif tok[0].isalnum():
            w = tok.casefold()
            ok = (tok.isalpha() and w in vocab) or w in _KEEP
            out.append(tok if ok else "…")
            last_word = w if tok.isalpha() else ""
        else:
            out.append(tok)
            if not tok.isspace():
                last_word = ""
    s = "".join(out)
    s = re.sub(r"(?:…|<n>)(?:[\s'’\"„“‚‘,.:;/()_+\-]*(?:…|<n>))+",
               lambda m: "<n>" if "…" not in m.group(0) else "…", s)
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > _MAX_LINE:
        s = s[: _MAX_LINE - 1] + "…"
    return s


def _shape_fields(fields) -> str:
    shown = []
    for f in fields[:40]:
        f = f.strip().strip('"').strip("'").strip()
        words = [w for w in re.split(r"[^0-9a-zäöüß#]+", f.casefold()) if w]
        ok = (0 < len(f) <= 40 and words and all(w in _HEADER_WORDS or w == "#" for w in words)
              and not any(ch.isdigit() for ch in f))
        shown.append(f if ok else "<feld>")
    more = f", … ({len(fields) - 40} weitere)" if len(fields) > 40 else ""
    return ", ".join(shown) + more


def header_shape(line: str) -> str:
    """Erste Zeile einer nicht erkannten Datei nur als Struktur (Positivliste, Audit R3-B1).
    Trägt sie Bestandstrennungs-Wörter (Bisq-Spalten …), nur die Feldanzahl (R5-B3)."""
    raw = _norm(line)
    delim = max((",", ";", "\t", "|"), key=raw.count)
    fields = raw.split(delim) if raw else []
    name = {",": "Komma", ";": "Semikolon", "\t": "Tab", "|": "Senkrechtstrich"}[delim]
    if _CLASS_WORDS.search(raw):
        return f"{len(fields)} Felder, Trennzeichen {name} (Spaltennamen nicht übertragen)"
    return f"{len(fields)} Felder, Trennzeichen {name}: " + _shape_fields(fields)


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
