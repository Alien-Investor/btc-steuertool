# BTC Steuertool

Bitcoin-Steuerberechnung für deutsche Privatanleger — § 23 EStG, FiFo-Methode.

Liest CSV-Exporte von BitBox-Wallets und Broker-Konten und erzeugt daraus
steuerrelevante Jahresberichte für das deutsche Finanzamt.

## Features

- FiFo-Engine mit Haltefrist von einem Jahr (§ 23 Abs. 1 Nr. 2 EStG i.V.m. §§ 187 Abs. 1,
  188 Abs. 2 BGB) — steuerfrei / steuerpflichtig je Lot
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
- Historische Wechselkurse für USD/CHF-Käufe (Swissquote, Pocket): EZB-Referenzkurse,
  gebündelt unter `src/data/ecb_eur_daily.csv` — das Tool braucht keine Internetverbindung
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

## Web-Version im Browser (frei)

Wer kein Terminal nutzen will: **https://api.alien-investor.org/steuertool/** — dieselbe
Engine läuft dort unverändert per Pyodide (Python in WebAssembly) im Browser. CSV-Dateien
werden nie hochgeladen, es gibt keinen Account und keine Bezahlschranke. Broker werden am
Dateiinhalt erkannt, ZIPs werden entpackt, alle Reports kommen als ein ZIP.

Offen gesagt: die Web-Version lädt den Code bei jedem Aufruf vom Server. Wer maximale
Kontrolle will, nimmt das CLI aus diesem Repo (oder baut die Web-Version selbst, siehe
`web/`).

Lokal bauen und testen: `cd web && ./vendor-setup.sh && ./build.sh`, dann
`python3 -m http.server 8741 --directory dist` und `http://localhost:8741/` öffnen.

## Linux-Desktop-App (Flatpak, frei)

Dieselbe Oberfläche und dieselbe Engine als App, die nach der Installation **nichts mehr nachlädt**:
Pyodide, Rechenkern und Kurstabellen sind eingebaut. Das Flatpak hat **kein Netz** (`--share=network`
fehlt) und **keinen Dateisystem-Zugriff** — CSVs kommen über den Datei-Dialog oder per Drag&Drop
herein, Reports gehen über den Speichern-Dialog hinaus. Anleitung in der App über den „?“-Knopf.

Download: Bundle `btc-steuertool-<Version>-linux-x86_64.flatpak` mit `SHA256SUMS` und GPG-Signatur
`SHA256SUMS.asc` aus den GitHub-Releases bzw. unter https://api.alien-investor.org/downloads/steuertool/.

```bash
gpg --verify SHA256SUMS.asc SHA256SUMS      # Schlüssel 100F 9E25 BFAE A807 DBC3  57D7 50C0 D785 83BF CB81
sha256sum -c SHA256SUMS
flatpak install --user btc-steuertool-*-linux-x86_64.flatpak   # Laufzeit kommt von Flathub
flatpak run org.alieninvestor.steuertool
```

Update: alte Version deinstallieren (`flatpak uninstall --user org.alieninvestor.steuertool`), neue
installieren — die App speichert keine Daten. Selbst bauen: `desktop/build-desktop.sh`
(Details und Sicherheitsregeln in `desktop/DESKTOP-INVARIANTEN.md`).

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
