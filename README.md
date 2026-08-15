# BTC Steuertool

Bitcoin-Steuerberechnung für deutsche Privatanleger — § 23 EStG, FiFo-Methode.

Liest CSV-Exporte von BitBox-Wallets und Broker-Konten und erzeugt daraus
steuerrelevante Jahresberichte für das deutsche Finanzamt.

## Features

- FiFo-Engine mit 365-Tage-Haltefrist (steuerfrei / steuerpflichtig)
- Freigrenze automatisch berücksichtigt (600 EUR bis 2023 / 1.000 EUR ab 2024;
  steuerfrei bleibt nur ein Gesamtgewinn **unter** der Grenze, § 23 Abs. 3 EStG)
- **Kein stiller Datenverlust:** Zeilen, die ein Parser nicht verarbeiten kann
  (z.B. ein noch nicht unterstützter Verkaufstyp), erzeugen eine deutliche
  Warnung im Report — statt kommentarlos zu fehlen
- **Dedup:** identische Transaktionen in überlappenden Exporten desselben
  Brokers (Jahres- + Gesamtexport) werden erkannt und nur einmal gezählt
- Steuerjahr und Haltefrist nach **deutschem Kalenderdatum** (Europe/Berlin),
  nicht UTC — relevant bei Käufen/Verkäufen um Mitternacht bzw. am Jahreswechsel
- Unterstützte Broker: **21bitcoin, Bison, Swissquote, Strike, Pocket, Bisq**
- Unterstützte Wallets: **BitBox** (alle Wallet-CSVs werden automatisch eingelesen)
- **noKYC-Käufe** via Bisq-CSV-Direktimport (`Broker/bisq.csv`) oder manuell via `manual_buys.csv`
- **noKYC strikt getrennt** — erscheint nie in `steuerreport_*.txt` oder `steuernachweis_*.txt`, sondern nur in der separaten `nokyc_intern_*.txt` (mit Warnhinweis)
- **Private Verkäufe** via `manual_sales.csv` — für P2P-Verkäufe ohne Broker
- Historische Wechselkurse via EZB (frankfurter.dev) für USD/CHF-Käufe bei Swissquote
- Formaler Steuernachweis für Steuerberater und Finanzamt (`--nachweis`)
- CSV-Export für Excel (`--csv`)
- Mehrere Datenverzeichnisse möglich (`--data-dir`) — praktisch für getrennte Portfolios

## Schnellstart

```bash
# Einmalig einrichten
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # Mac/Linux
# .venv\Scripts\pip install -r requirements.txt  # Windows

# Datenordner anlegen (einmalig — werden nie committed, siehe .gitignore)
mkdir -p bitbox Broker

# Eigene CSV-Dateien ablegen:
# bitbox/*.csv           ← BitBox-Exporte
# Broker/*.csv           ← Broker-Exporte
# Broker/bisq.csv        ← optional: Bisq-Export (direkt aus Bisq exportieren)
# manual_buys.csv        ← optional: noKYC-Käufe manuell (Robosats, P2P, Bargeld)
# manual_sales.csv       ← optional: private P2P-Verkäufe

# Report für ein Jahr
.venv/bin/python src/main.py --year 2024       # Mac/Linux
# .venv\Scripts\python src/main.py --year 2024  # Windows

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
sowie die Dateien `manual_buys.csv` und `manual_sales.csv` sind in `.gitignore`
eingetragen und werden nie versehentlich committed.

## Steuerrechtliche Grundlagen

- Methode: FiFo (First In, First Out)
- Haltefrist: Gewinne sind steuerfrei, wenn zwischen Anschaffung und Veräußerung mehr als
  ein Jahr liegt (§ 23 Abs. 1 Satz 1 Nr. 2 EStG i.V.m. §§ 187 Abs. 1, 188 Abs. 2 BGB)
- Freigrenze: 600 EUR (bis 2023) / 1.000 EUR (ab 2024) — steuerfrei nur, wenn der
  Gesamtgewinn im Kalenderjahr **weniger** als die Grenze beträgt (§ 23 Abs. 3 EStG);
  ab exakt der Grenze ist der volle Betrag steuerpflichtig. Die Freigrenze gilt für
  alle privaten Veräußerungsgeschäfte eines Jahres zusammen, nicht nur für Bitcoin
- Überträge zwischen eigenen Wallets/Konten: der übertragene Bestand ist steuerlich neutral
- In Bitcoin entrichtete Gebühren (Netzwerk-/Auszahlungsgebühren, auch beim Übertrag
  zwischen eigenen Wallets): Veräußerung des Gebührenanteils zum Tagesschlusskurs
  (BMF-Schreiben vom 06.03.2025, Rn. 33, 54, 60) — Gewinn zählt in die Freigrenze,
  die Menge verlässt den Bestand. Kursquelle: gebündelte Tabelle
  `src/data/btc_eur_daily.csv` (Bitstamp BTC/EUR, offline, aktualisieren mit
  `python tools/update_btc_prices.py`)
- Schenkungen/Spenden (BitBox-Notiz enthält z.B. „Spende" oder „Schenkung"): keine
  Veräußerung, aber Bestandsabgang; Anschaffungsdaten werden für den Empfänger
  ausgewiesen (§ 23 Abs. 1 Satz 3 EStG)

## Unterstützung

Wenn dir das Tool hilft, freue ich mich über eine kleine Spende:
👉 [alien-investor.org/spenden.html](https://alien-investor.org/spenden.html)

## Disclaimer

Dieses Tool ersetzt keine Steuerberatung. Die Ergebnisse sollten vor der
Abgabe der Steuererklärung von einem Steuerberater geprüft werden.

## Lizenz

MIT
