# Changelog — BTC Steuertool (Apps: Linux-Desktop + Android)

Das CLI und die Web-Version haben keine eigenen Versionen; sie laufen immer auf dem Stand von `main`.
Dieses Änderungsprotokoll gilt für die App-Fassungen (Flatpak + APK), die denselben Rechenkern enthalten.

## Unveröffentlicht (main)
- Bisq: auch der **englische Export** wird gelesen (Spaltenköpfe „Trade ID, Date/Time, …“, Werte „Buy BTC“/„Completed“); die
  Zeitstempel aller englischen Länder-Einstellungen von Bisq werden erkannt. Abgeleitet aus dem Bisq-Quellcode, noch nicht an
  einem echten englischen Export bestätigt — bitte Ergebnis prüfen und Abweichungen melden.
- Bisq: Trades auf Altcoin-Märkten (XMR/BTC, BSQ/BTC …) werden als Veräußerung bzw. Anschaffung von BTC gemeldet statt nur stumm
  gezählt; eine Datei, die nur Verkäufe enthält, bekommt keine zweite Sammelwarnung mehr; eine BOM in der Kopfzeile (Excel) stört nicht mehr.
- Oberfläche: CSV-Dateien mit BOM werden erkannt statt als „unbekannt“ gesperrt.

## v1.2 — 2026-10-02
- **FiFo jetzt walletbezogen** (BMF-Schreiben vom 06.03.2025, Rn. 61 f.): Jede Wallet ist ein eigener Bestand, jedes Börsenkonto behandelt das
  Tool als eigene Wallet. Bei
  Überträgen zwischen eigenen Wallets gibt die abgebende Wallet ihre ältesten Einheiten ab; Anschaffungsdatum und -kosten wandern mit in die
  empfangende Wallet. Bisher rechnete das Tool einen gemeinsamen Bestand über alle Quellen. Ergebnisse können sich dadurch ändern (andere
  Zuordnung von Verkauf zu Kauf, andere Haltefrist); die Reports erklären die Methode selbst.
- Überträge werden automatisch zugeordnet (Transaktions-ID, sonst Betrag und Zeit innerhalb von 48 Stunden). Sonderfälle wie Sammelauszahlungen
  über die optionale Datei `transfer_zuordnung.csv`. Abgänge ohne erkennbaren Eingang gelten als Übertrag in eine nicht eingelesene eigene
  Wallet und werden gemeldet, nie still als Verkauf gebucht.
- Neue optionale Spalte `wallet` in `manual_buys.csv` und `manual_sales.csv`.
- Steuerreport und Steuernachweis: Abschnitt „Umbuchungen zwischen eigenen Wallets“; der Steuerreport zeigt zusätzlich den Bestand je Wallet
  zum Jahresende. BitBox-Wallets erscheinen dort nur als „BitBox-Wallet“ (bei mehreren „BitBox-Wallet 1“, „BitBox-Wallet 2“ …), nie mit Dateinamen.
- Neue interne Datei `wallet_abgleich_intern_JAHR.txt` (im ZIP unter INTERN-NICHT-WEITERGEBEN): echte Wallet-Namen, alle Zuordnungen, offene
  Punkte und der Vergleich zur bisherigen gemeinsamen Rechnung.
- Strike: die in Bitcoin gezahlte Netzwerkgebühr (`Fee BTC`) wird jetzt als Veräußerung des Gebührenanteils erfasst; bisher ging sie in der
  Auszahlungsmenge unter.
- Oberfläche: Abzeichen „BETA“ entfernt. Hilfetext zum Bisq-Export präzisiert (deutsche Bisq-Oberfläche).
- Internes Audit der neuen Rechenlogik (Rechenlogik und Datenschutz) vor dem Release, alle Funde behoben; neuer Mengenbilanz-Test.

## v1.1 — 2026-10-02
- Spenden-Blitz unten in der App („Energie aufladen · Spenden“) wie in den anderen Alien-Apps. Er öffnet die Spendenseite auf
  alien-investor.org im Browser des Systems; die App selbst bleibt ohne Netz.

## v1.0 — 2026-10-02
- Erste Veröffentlichung als App: **Linux-Desktop (Flatpak)** und **Android (APK)**, frei und quelloffen.
- Derselbe Rechenkern wie CLI und Web-Version (FiFo nach § 23 EStG, Jahresfrist, Freigrenze, Gebühren in Bitcoin
  als Veräußerung des Gebührenanteils, Schenkungen/Spenden als Bestandsabgang), Reports byte-gleich zum CLI.
- Ohne Netz: Rechenkern (Pyodide), EZB-Wechselkurse und BTC-Tagesschlusskurse sind eingebaut. Das Flatpak hat kein
  Netz- und kein Dateisystem-Recht, die Android-App hat keine Internet-Berechtigung (im Manifest steht nur die von AndroidX erzeugte
  app-eigene Signatur-Berechtigung, die nichts freigibt), Screenshots gesperrt.
- CSVs und ZIPs über den Datei-Dialog, Reports über den Speichern-Dialog; Handbuch in der App („?“, Deutsch/Englisch).
- Vor dem Release internes Security-Audit (Funde behoben, siehe Repo-Historie).
