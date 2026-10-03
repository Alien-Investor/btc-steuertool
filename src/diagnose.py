"""Diagnose für Bug-Reports (v1.4): was der Nutzer dem Autor schicken kann, ohne private Daten.

Die App stellt zusammen, WAS geladen wurde und WAS schiefging — nie, WELCHE Daten:
keine Dateinamen (oft private Wallet-Namen), keine Beträge, Daten oder Uhrzeiten, keine
Transaktions-IDs, Adressen oder xpubs, kein Hinweis auf noKYC-Bestände. Die Schwärzung
liegt hier, an einer Stelle — die GUI liefert nur Rohangaben und zeigt das Ergebnis vor
dem Senden vollständig an. Support gibt es nur zu Technik und Format, nicht zu Steuerfragen.

Grundsatz: lieber zu viel schwärzen. Eine Meldung, aus der nichts mehr hervorgeht, kostet
eine Rückfrage; ein Betrag oder Wallet-Name im Postfach des Autors lässt sich nicht
zurückholen.
"""
from __future__ import annotations

import re

from .parsers import _sanitize

TITLE = "BTC Steuertool – Diagnose (ohne Dateinamen, Beträge, Daten, Adressen und Wallet-Namen)"

# Meldungen, die die getrennten Bestände betreffen, gehen nur als neutraler Satz hinaus
_CLASS_WORDS = re.compile(r"no[\s_-]?kyc|p2p|bisq|robosats|hodl\s*hodl|peach|agoradesk|bargeld", re.IGNORECASE)
_CLASS_TEXT = "Abbruch bzw. Hinweis zur Trennung der Bestände (Details nur im lokalen Log)."

_RULES = [
    # Werte in Anführungszeichen sind Zellinhalte aus der Datei
    (re.compile(r"'[^']*'"), "'…'"),
    (re.compile(r"„[^“]*“"), "„…“"),
    (re.compile(r'"[^"]*"'), '"…"'),
    # xpubs, Adressen, Transaktions-IDs
    (re.compile(r"\b[xyztuv]pub[1-9A-HJ-NP-Za-km-z]{8,}", re.IGNORECASE), "<xpub>"),
    (re.compile(r"\b(?:bc1|tb1)[0-9a-z]{8,}\b", re.IGNORECASE), "<adresse>"),
    (re.compile(r"\b[13][1-9A-HJ-NP-Za-km-z]{25,34}\b"), "<adresse>"),
    (re.compile(r"\b0x[0-9a-f]{8,}\b", re.IGNORECASE), "<adresse>"),
    (re.compile(r"\b[0-9a-f]{16,}\b", re.IGNORECASE), "<id>"),
    # Datum → nur das Jahr, Uhrzeit weg
    (re.compile(r"\b(\d{4})-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?"), r"\1"),
    (re.compile(r"\b\d{1,2}\.\d{1,2}\.(\d{4})\b"), r"\1"),
    (re.compile(r"\b\d{1,2}/\d{1,2}/(\d{2,4})\b"), r"\1"),
    (re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"), "<zeit>"),
    # Beträge: Dezimalzahlen, große Ganzzahlen (Satoshi, Unix-Zeit), Exponenten
    (re.compile(r"-?\b\d+[.,]\d+(?:e[+-]?\d+)?\b", re.IGNORECASE), "<betrag>"),
    (re.compile(r"-?\b\d+e[+-]?\d+\b", re.IGNORECASE), "<betrag>"),
    (re.compile(r"-?\b\d{5,}\b"), "<zahl>"),
]

_MAX_LINE = 300
_MAX_WARNINGS = 30


def redact(text: str, names: list[str] = ()) -> str:
    """Eine Meldung oder Kopfzeile ohne private Angaben."""
    s = _sanitize(str(text or ""))
    # Dateinamen und ihre Stämme zuerst (längste zuerst: „cold_full.csv“ vor „cold“)
    for name in sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True):
        s = re.sub(re.escape(name), "<datei>", s, flags=re.IGNORECASE)
    if _CLASS_WORDS.search(s):
        return _CLASS_TEXT
    for rx, repl in _RULES:
        s = rx.sub(repl, s)
    # Wallet-Präfixe mit Namen („sparrow:cold“), falls ein Name nicht als Datei bekannt war
    s = re.sub(r"\b(bitbox|sparrow|electrum|trezor|ledger):\S+", r"\1:<name>", s, flags=re.IGNORECASE)
    if len(s) > _MAX_LINE:
        s = s[: _MAX_LINE - 1] + "…"
    return s


def build(info: dict) -> str:
    """Diagnose-Text aus den Rohangaben der GUI.

    info: platform, lang, files=[{label, lines, kb, hidden, header}], error, warnings (öffentliche
    Fassung), names (alle Dateinamen und -stämme, nur zum Schwärzen — erscheinen nie im Ergebnis).
    `hidden`: Datei eines Typs, der noKYC sein kann — nur gezählt, nie einzeln aufgeführt.
    """
    names = [str(n) for n in info.get("names", [])]
    for n in list(names):
        stem = n.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        names.append(stem)
    out = [TITLE, ""]
    out.append(f"Plattform: {redact(info.get('platform', '?'))} · Sprache: {redact(info.get('lang', '?'))}")
    files = info.get("files", [])
    shown = [f for f in files if not f.get("hidden")]
    hidden = len(files) - len(shown)
    out.append("")
    out.append(f"Dateien ({len(files)}):")
    for f in shown:
        out.append(f"  - {redact(f.get('label', '?'), names)}: {int(f.get('lines', 0))} Zeilen, "
                   f"{_size(f.get('kb', 0))}")
    if hidden:
        out.append(f"  - weitere Dateien (nicht aufgeschlüsselt): {hidden}")
    headers = [f for f in shown if f.get("header")]
    if headers:
        out.append("")
        out.append("Nicht erkannte Dateien – erste Zeile (geschwärzt):")
        for f in headers:
            out.append(f"  - {redact(f['header'], names)}")
    out.append("")
    error = info.get("error")
    if error:
        out.append(f"Letzte Berechnung: Abbruch — {redact(error, names)}")
    elif info.get("ran"):
        out.append("Letzte Berechnung: ohne Abbruch")
    else:
        out.append("Letzte Berechnung: keine")
    warnings = []
    for w in info.get("warnings", []):
        r = redact(w, names)
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
    """Größe grob (Größenordnung reicht für Format-Fragen, verrät keinen Datensatzumfang genau)."""
    kb = float(kb or 0)
    for limit, text in ((10, "unter 10 KB"), (100, "10–100 KB"), (1000, "100 KB–1 MB"), (10000, "1–10 MB")):
        if kb < limit:
            return text
    return "über 10 MB"
