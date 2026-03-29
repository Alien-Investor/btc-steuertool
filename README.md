# BTC Steuertool

Bitcoin-Steuerberechnung für deutsche Privatanleger — § 23 EStG, FiFo-Methode.

Liest CSV-Exporte von BitBox-Wallets und Broker-Konten und erzeugt daraus
steuerrelevante Jahresberichte für das deutsche Finanzamt.

## Features

- FiFo-Engine mit 365-Tage-Haltefrist (steuerfrei / steuerpflichtig)
- Freigrenze automatisch berücksichtigt (600 EUR bis 2023 / 1.000 EUR ab 2024)
- Unterstützte Broker: **21bitcoin, Bison, Swissquote, Strike, Pocket**
- Unterstützte Wallets: **BitBox** (alle Wallet-CSVs werden automatisch eingelesen)
- Historische Wechselkurse via EZB (frankfurter.app) für USD/CHF-Käufe bei Swissquote
- Formaler Steuernachweis für Steuerberater und Finanzamt (`--nachweis`)
- CSV-Export für Excel (`--csv`)
- Mehrere Datenverzeichnisse möglich (`--data-dir`) — praktisch für getrennte Portfolios

## Schnellstart

```bash
# Einmalig einrichten
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# CSV-Dateien ablegen (werden nie committed — siehe .gitignore)
# bitbox/*.csv       ← BitBox-Exporte
# Broker/*.csv       ← Broker-Exporte
# manual_sales.csv   ← optional: private P2P-Verkäufe

# Report für ein Jahr
.venv/bin/python src/main.py --year 2024

# Alle Jahre
.venv/bin/python src/main.py --all

# Mit CSV-Export und formalem Nachweis
.venv/bin/python src/main.py --year 2024 --csv --nachweis
```

## Beispieldaten

Im Ordner `examples/` liegen fiktive Testdaten für alle unterstützten Broker/Wallets:

```bash
.venv/bin/python src/main.py --data-dir examples/ --all
```

## Datenschutz

Eigene CSV-Dateien enthalten sensible Finanzdaten. Die Ordner `bitbox/`, `Broker/`
und die Datei `manual_sales.csv` sind in `.gitignore` eingetragen und werden
nie versehentlich committed.

## Steuerrechtliche Grundlagen

- Methode: FiFo (First In, First Out)
- Haltefrist: Gewinne nach > 365 Tagen Haltedauer sind steuerfrei (§ 23 Abs. 1 Nr. 2 EStG)
- Freigrenze: 600 EUR (bis 2023) / 1.000 EUR (ab 2024) — bei Überschreitung voller Betrag steuerpflichtig
- Überträge zwischen eigenen Wallets/Konten: steuerlich neutral

## Unterstützung

Wenn dir das Tool hilft, freue ich mich über eine kleine Spende:
👉 [alien-investor.org/spenden.html](https://alien-investor.org/spenden.html)

## Disclaimer

Dieses Tool ersetzt keine Steuerberatung. Die Ergebnisse sollten vor der
Abgabe der Steuererklärung von einem Steuerberater geprüft werden.

## Lizenz

MIT
