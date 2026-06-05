# BTC Steuertool — Anleitung

## Was macht dieses Tool?

Es liest deine CSV-Dateien von BitBox, 21bitcoin, Bison, Swissquote, Strike, Pocket und Bisq
und berechnet daraus automatisch, welche Bitcoin-Verkäufe steuerpflichtig oder steuerfrei waren.
Die Berechnung folgt der deutschen FiFo-Methode (§ 23 EStG): BTC die länger als
365 Tage gehalten wurden, sind beim Verkauf steuerfrei.

---

## Erste Einrichtung (einmalig)

Öffne ein Terminal im Projektordner und führe aus:

**Mac/Linux:**
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p bitbox Broker
```

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
mkdir bitbox
mkdir Broker
```

Die Ordner `bitbox/` und `Broker/` sowie die Dateien `manual_buys.csv` und
`manual_sales.csv` existieren nicht im Repository — sie sind in `.gitignore`
eingetragen damit deine persönlichen Finanzdaten nie versehentlich auf GitHub
landen. Du musst sie bei Bedarf selbst anlegen:

- `bitbox/` und `Broker/` → einmalig mit den mkdir-Befehlen oben anlegen
- `manual_buys.csv` → im Projektordner anlegen wenn du noKYC-Käufe hast (Bisq, Robosats, P2P)
- `manual_sales.csv` → im Projektordner anlegen wenn du private P2P-Verkäufe hast

Das richtest du nur einmal ein. Danach brauchst du nur noch die Befehle unten.

---

## Tägliche Nutzung

### Report für ein bestimmtes Jahr

```bash
.venv/bin/python src/main.py --year 2025
```

Gibt den Steuerreport für 2025 aus und speichert ihn unter `reports/steuerreport_2025.txt`.

---

### Report für alle Jahre auf einmal

```bash
.venv/bin/python src/main.py --all
```

Erzeugt Reports für jedes Jahr in dem Transaktionen vorhanden sind.

---

### Zusätzlich CSV-Dateien exportieren

```bash
.venv/bin/python src/main.py --year 2025 --csv
```

Speichert zusätzlich zwei CSV-Dateien:
- `reports/kaeufe_2025.csv` — alle Käufe des Jahres
- `reports/verkaeufe_2025.csv` — alle Verkäufe mit FiFo-Aufschlüsselung

Nützlich wenn dein Steuerberater die Daten in Excel öffnen möchte.

---

### Formaler Nachweis für Steuerberater oder Finanzamt

```bash
.venv/bin/python src/main.py --year 2025 --nachweis
```

Erzeugt ein lesbares Dokument (`reports/steuernachweis_2025.txt`) mit:
- Deckblatt mit Ergebnis-Zusammenfassung
- Detailnachweis für jeden Verkauf (Kaufdatum, Haltedauer in Tagen, steuerfrei/pflichtig)
- Liste aller Käufe des Jahres
- Erklärung der Methodik und Datenquellen

Dieses Dokument kann man ausdrucken und dem Steuerberater oder Finanzamt vorlegen.

**Hinweis:** Die `.txt`-Datei direkt ausdrucken oder als Datei weitergeben — nicht in PDF
konvertieren. PDF-Konverter zerstören die Spaltenausrichtung der Tabellen.

**Wichtig:** Der Nachweis allein reicht nicht. Er enthält zwar die Kaufdaten, aber
keinen Beleg dass diese Käufe wirklich stattgefunden haben. Deshalb immer zusammen
mit den Original-CSV-Dateien der betroffenen Broker einreichen.

---

### Alles auf einmal (empfohlen am Jahresende)

```bash
.venv/bin/python src/main.py --year 2025 --csv --nachweis
```

---

### Getrenntes Datenverzeichnis (z.B. für ein zweites Portfolio)

```bash
.venv/bin/python src/main.py --data-dir /pfad/zum/anderen/verzeichnis/ --all
```

Das Datenverzeichnis muss die gleiche Struktur haben (`bitbox/`, `Broker/`, optional `manual_buys.csv` / `manual_sales.csv`).

---

## Wo liegen die Ergebnisse?

Alle erzeugten Dateien landen im Ordner `reports/`:

```
reports/
├── steuerreport_2025.txt     ← Übersichtlicher Report (für Finanzamt verwendbar)
├── steuernachweis_2025.txt   ← Formaler Nachweis (druckfertig, für Finanzamt)
├── nokyc_intern_2025.txt     ← noKYC-Käufe — NUR INTERN, nicht für Finanzamt!
├── kaeufe_2025.csv           ← Käufe als Tabelle (für Excel)
└── verkaeufe_2025.csv        ← Verkäufe mit FiFo-Details (für Excel)
```

**Wichtig:** `nokyc_intern_YYYY.txt` wird nur erzeugt wenn du Bisq-/noKYC-Daten hast.
Diese Datei **niemals** dem Finanzamt oder Steuerberater übergeben — sie enthält
P2P-Käufe die bewusst aus dem offiziellen Report herausgehalten werden.

---

## Was dem Steuerberater / Finanzamt übergeben werden soll

Der Nachweis für steuerfreie oder steuerpflichtige Verkäufe besteht immer aus zwei Teilen:
der **Berechnung** (was das Tool erzeugt) und den **Originalbelegen** (die CSVs der Broker).
Beides zusammen ergibt die vollständige Nachvollziehbarkeit.

| Dokument | Zweck |
|----------|-------|
| `reports/steuernachweis_JAHR.txt` | Hauptdokument: Berechnung, FiFo-Nachweis, Haltedauer |
| Original-CSV des Brokers | Originalbeleg: belegt Kauf- und Verkaufsdaten |
| `reports/kaeufe_JAHR.csv` / `verkaeufe_JAHR.csv` | Optional: für Steuerberater der Zahlen in Excel prüfen möchte |

Das Tool zeigt im Steuernachweis unter "Quelle" genau welcher Broker welches Lot geliefert hat.
Waren Käufe bei mehreren Brokern beteiligt, müssen auch deren CSVs beigelegt werden.

**Nicht beteiligte Broker weglassen:** Nur die CSVs der Broker beilegen, die im
Steuernachweis unter "Quelle" in der FiFo-Zuordnung der Verkäufe auftauchen.
CSVs anderer Broker haben keine Beleg-Funktion — der Nachweis listet die
Jahres-Anschaffungen bereits auf. "Gesamt"-CSVs verraten zudem immer auch
Transaktionen aus anderen Jahren (z.B. Käufe des laufenden Jahres) und ggf.
Einnahmen wie Spenden-Eingänge, die mit dem Steuerjahr nichts zu tun haben.

### Was das Finanzamt NICHT bekommt

Genauso wichtig wie die richtigen Unterlagen: zu wissen, was nicht in die Belegkette gehört.

| Datei | Warum nicht |
|-------|-------------|
| `reports/nokyc_intern_JAHR.txt` | Interne noKYC-Übersicht — niemals einreichen |
| BitBox-CSVs (`bitbox/`) | Selbst erstellte Dateien ohne Beweiswert — das Finanzamt hat keinen Anspruch auf deine Wallet-Historie. Die Belegkette besteht aus den Broker-CSVs. |
| `Broker/bisq*.csv` und `manual_buys.csv` | noKYC-Quellen — nur für die interne Buchführung |
| `fx_cache.json` und Quellcode | Technische Dateien, für das Finanzamt irrelevant |

**Wallet-Notizen neutral halten:** Die Notiz-Felder in den BitBox-CSVs sind private
Anmerkungen — sie tauchen in keinem vom Tool erzeugten Finanzamt-Dokument auf.
Trotzdem empfiehlt es sich, Notizen neutral zu formulieren („Übertrag" statt
detaillierter Beschreibungen). Falls eine Wallet-CSV doch einmal weitergegeben wird,
steht dort nichts, was das Finanzamt nichts angeht. Notizen lassen sich in der
BitBoxApp jederzeit ändern — danach die CSV einfach neu exportieren.

---

## Wenn neue CSV-Dateien dazukommen

Einfach die neue CSV-Datei in den richtigen Ordner legen:

- BitBox-Export → `bitbox/`
- 21bitcoin-Export → `Broker/` (Dateiname muss mit `21bitcoin` beginnen)
- Bison-Export → `Broker/Bison-CSV-Gesamt.csv`
- Swissquote-Export → `Broker/Swissquote_CSV-Gesamt.csv`
- Strike-Export → `Broker/` (Dateiname muss mit `strike_` beginnen, z.B. `strike_2026.csv`)
- Pocket-Export → `Broker/` (Dateiname muss mit `Pocket` beginnen)
- Bisq-Export → `Broker/` (Dateiname muss mit `bisq` beginnen, z.B. `bisq.csv`)

Bei Bison und Swissquote: neue Transaktionen in die bestehende Datei einfügen.
Bei Strike, Pocket und Bisq: einfach eine neue Datei ablegen, das Tool liest alle automatisch ein.

Für manuelle Einträge direkt im Projektordner (nicht in einem Unterordner):
- `manual_buys.csv` → noKYC-Käufe manuell (Robosats, P2P, Bargeld) — eine Zeile pro Kauf
- `manual_sales.csv` → private P2P-Verkäufe — eine Zeile pro Verkauf

Diese Dateien existieren nicht im Repository (gitignored) — einfach neu anlegen und befüllen.
Das Format ist in den Abschnitten "noKYC-Käufe" und "Private Verkäufe" weiter unten beschrieben.

Danach einfach den gewünschten Befehl neu ausführen — das Tool liest immer alle Dateien neu ein.

---

## noKYC-Käufe (Bisq, Robosats, P2P, Bargeld)

Wenn du BTC ohne KYC-Broker gekauft hast — über Bisq, Robosats, HodlHodl, direkt
von Person zu Person oder gegen Bargeld — gibt es drei Wege:

### Option A: Bisq-CSV direkt importieren (empfohlen für Bisq-Nutzer)

Bisq bietet einen CSV-Export unter "Portfolio → Trades → Exportieren".
Diese Datei einfach als `bisq.csv` in den `Broker/`-Ordner legen.
Das Tool liest sie automatisch ein und erkennt alle abgeschlossenen Käufe.

### Option B: Manuelle Eingabe via `manual_buys.csv`

Für Robosats, HodlHodl, P2P oder Bargeldkäufe — also alles ohne CSV-Export:

```csv
date,btc_amount,eur_amount,note
2024-03-10,0.01000000,550.00,Robosats Trade
2024-07-22,0.00500000,280.00,P2P Kauf
```

- `date`: Datum im Format YYYY-MM-DD
- `btc_amount`: gekaufte BTC-Menge
- `eur_amount`: gezahlter EUR-Betrag (Gesamtbetrag inkl. etwaiger Gebühren)
- `note`: Freitext zur eigenen Dokumentation (z.B. Trade-ID, Quelle)

### Option C: Dedizierte noKYC-BitBox-Wallet

Wenn du eine eigene BitBox-Wallet nur für noKYC-Sats verwendest (z.B. Bisq-Eingang,
Wasabi-Outputs, Lightning-Swaps), kannst du deren CSV in den Unterordner `bitbox/nokyc/`
legen. Das Tool erkennt den Ordner automatisch und markiert alle Transaktionen als intern:

```
bitbox/
├── wallet1.csv           ← normale KYC-Wallet
└── nokyc/
    └── nokyc_wallet.csv  ← NUR INTERN, nicht für Finanzamt
```

Alle Wallet-Bewegungen aus `bitbox/nokyc/` erscheinen:
- **nicht** in `steuerreport_*.txt` oder `steuernachweis_*.txt`
- **nur** in `nokyc_intern_*.txt` unter "noKYC-WALLET-AKTIVITÄT"

Das ist sinnvoll um den Saldo und die Bewegungen intern nachzuhalten, ohne dass
das Finanzamt von dieser Wallet-Aktivität erfährt.

### Wie noKYC-Käufe im Report erscheinen

noKYC-Käufe tauchen in **keiner** der Finanzamt-Dateien auf:

- `steuerreport_2025.txt` — enthält **keine** noKYC-Daten
- `steuernachweis_2025.txt` — enthält **keine** noKYC-Daten

Das Tool erzeugt stattdessen eine eigene Datei:

- `nokyc_intern_2025.txt` — **nur für dich**, niemals weitergeben

Diese Datei beginnt mit einem deutlichen Warnhinweis:

```
========================================================================
  !! INTERN — NICHT FÜR FINANZAMT BESTIMMT !!

  Diese Datei enthält noKYC-Käufe (Bisq / Robosats / P2P).
  Sie dient ausschließlich der eigenen Buchführung.
  NICHT an Steuerberater oder Finanzamt weitergeben.
========================================================================
```

Danach folgen alle noKYC-Käufe und verbleibenden noKYC-Bestände zur eigenen Übersicht.

**Zur Rechtslage:** Du bist nicht verpflichtet, deinen vollständigen Wallet-Fingerprint
offenzulegen. Solange die Anschaffungskosten korrekt angegeben sind und steuerpflichtige
Gewinne vollständig gemeldet werden, ist die selektive Angabe steuerrechtlich unbedenklich.

**Wichtig für den Steuernachweis:** Bei noKYC-Käufen gibt es keinen Broker-Beleg.
Eigene Aufzeichnungen aufbewahren — z.B. Bisq-Trade-History, Wallet-Transaktionsbelege
oder Kontoauszüge für den EUR-Abfluss.

---

## Private Verkäufe (Peer-to-Peer)

Wenn du BTC direkt an eine Person verkaufst — also außerhalb eines Brokers, z.B. gegen
eine Überweisung — gibt es keine CSV von einer Plattform. Dafür gibt es die Datei
`manual_sales.csv` im Projektordner.

Format (eine Zeile pro Verkauf, Spalte `no_kyc` optional):

```csv
date,btc_amount,eur_amount,note,no_kyc
2024-06-15,0.00500000,325.00,P2P Verkauf,
2024-08-01,0.00300000,180.00,Verkauf aus noKYC-Bestand,ja
```

- `date`: Datum im Format YYYY-MM-DD
- `btc_amount`: verkaufte BTC-Menge
- `eur_amount`: erhaltener EUR-Betrag (netto, ohne zusätzliche Gebühren)
- `note`: Freitext zur eigenen Dokumentation
- `no_kyc`: `ja` → Verkauf stammt aus dem noKYC-Bestand (siehe unten). Leer = normaler Verkauf.

Das Tool liest diese Datei automatisch ein und behandelt jeden Eintrag als Verkauf.
Normale Einträge tauchen im offiziellen Report unter der Quelle `manual` auf.

**Getrennte FiFo-Pools (wichtig):** KYC- und noKYC-Bestände werden in zwei strikt
getrennten FiFo-Pools geführt. Broker-Verkäufe und normale manuelle Verkäufe
verbrauchen ausschließlich KYC-Lots — ein Bisq- oder Robosats-Kauf kann dadurch
niemals in der FiFo-Zuordnung eines Finanzamt-Dokuments auftauchen.

Verkäufe mit `no_kyc=ja` verbrauchen ausschließlich den noKYC-Pool und erscheinen
**nur** in `nokyc_intern_YYYY.txt` — inklusive FiFo-Zuordnung, Haltedauer und Gewinn,
damit du die steuerliche Lage selbst beurteilen kannst.

**Wichtig für den Steuernachweis:** Bei privaten Verkäufen gibt es keinen Broker-Beleg.
Als Nachweis sollten Kontoauszug (EUR-Eingang) und ggf. Kommunikation mit dem Käufer
aufbewahrt werden.

---

## Was bedeuten die Ergebnisse?

**Steuerpflichtiger Gewinn** — dieser Betrag muss in der Steuererklärung in der
Anlage SO (Sonstige Einkünfte) angegeben werden.

**Steuerfreier Gewinn** — muss nicht angegeben werden (Haltedauer > 365 Tage).

**Freigrenze** — Bis 600 EUR (vor 2024) bzw. 1.000 EUR (ab 2024) steuerpflichtiger
Gewinn pro Jahr fällt keine Steuer an. Bei Überschreitung wird der **gesamte**
Betrag steuerpflichtig, nicht nur der Teil über der Grenze.

**Verbleibende BTC-Bestände** — zeigt dir welche Lots du noch hältst, mit Kaufdatum
und Einstandspreis. Erscheint am Ende des laufenden Jahres-Reports.

---

## Häufige Fragen

**Muss ich die CSV-Dateien aktuell halten?**
Ja. Das Tool kann nur auswerten was in den CSV-Dateien steht. Exportiere am
Jahresende (oder vor der Steuererklärung) frische CSVs von allen Plattformen.

**Was ist mit den Überträgen zwischen meinen Wallets?**
Die erkennt das Tool automatisch und ignoriert sie steuerlich. Überträge zwischen
eigenen Wallets (BitBox ↔ Bison, BitBox ↔ 21bitcoin usw.) sind kein steuerpflichtiger
Vorgang.

**Swissquote hat manche Käufe in USD — ist das ein Problem?**
Nein. Das Tool fragt automatisch einen historischen EUR/USD-Kurs ab (von
frankfurter.app, der offiziellen EZB-Datenquelle) und rechnet um. Der Kurs wird
lokal in `fx_cache.json` gespeichert, damit er nicht jedes Mal neu abgerufen werden muss.

**Kann ich dem Ergebnis vertrauen?**
Das Tool rechnet nach der FiFo-Methode wie vom deutschen Steuerrecht vorgeschrieben.
Die Ergebnisse sollten aber immer von deinem Steuerberater geprüft werden —
besonders wenn steuerpflichtige Gewinne ausgewiesen werden.

**Warum tauchen Bisq/noKYC-Käufe nicht im Finanzamt-Report auf?**
Das ist bewusst so gestaltet. noKYC-Käufe erscheinen nur im internen Block am Ende
des Reports — nicht im offiziellen Teil. Für die Steuer relevant ist, ob du
steuerpflichtige Gewinne erzielt hast. Bei P2P-Käufen die du als langfristige
Selbstverwahrung hältst und nie über eine KYC-Börse verkaufst, entsteht kein
steuerpflichtiger Vorgang der gemeldet werden müsste.
