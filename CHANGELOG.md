# Changelog — BTC Steuertool (Apps: Linux-Desktop + Android)

Das CLI und die Web-Version haben keine eigenen Versionen; sie laufen immer auf dem Stand von `main`.
Dieses Änderungsprotokoll gilt für die App-Fassungen (Flatpak + APK), die denselben Rechenkern enthalten.

## Unveröffentlicht (main)
- **Wallet-Exporte Sparrow, Electrum, Trezor Suite, Ledger Wallet/Ledger Live (neu, unbestätigt):** Transaktions-CSVs dieser Programme werden gelesen
  (das Tool erkennt das Programm an der Kopfzeile, auch ältere Exportformate). Jede Wallet ist ein eigener Bestand, bei Ledger jedes
  Konto; Überträge werden über die Transaktions-ID mit Börsen und anderen Wallets verbunden. In den Finanzamt-Dokumenten heißen sie nur
  „Sparrow-Wallet“, „Trezor-Wallet 1“ usw. Ausgänge mit Netzwerkgebühr, Überweisungen an sich selbst (nur Gebühr) und Schenkungen
  (Wort im Label) werden wie bei der BitBox gebucht. Die Formate stammen aus dem Quellcode der Programme, nicht aus echten Exporten:
  Der Steuerreport zeigt je Datei eine Warnung „Format noch nicht bestätigt“. Electrum schreibt Zeiten ohne Zeitzone (gelesen als deutsche
  Ortszeit), Lightning-Zahlungen werden gemeldet, nicht erfasst. In der App: Typ „Sparrow/Electrum/Trezor/Ledger (KYC/noKYC)“.
- Internes Release-Audit (drei Prüfer, Datenschutz/Rechnung/Robustheit) vor v1.4, alle Funde behoben: Ein Übertrag aus einer noKYC-Wallet
  in eine KYC-Wallet wird jetzt auch erkannt, wenn die Gebühr im Export fehlt oder beide Wallets gleich heißen (bisher stand der Eingang
  dann im Steuernachweis); eine Transaktion mit gleichem Betrag an zwei eigene Wallets galt fälschlich als doppelter Export; gleich benannte
  Ledger-Konten zweier Geräte, negative Beträge, Satoshi-Einheit bei Trezor und unbestätigte Ledger-Vorgänge brechen ab oder werden gemeldet
  statt still falsch gebucht; Zeiten in der doppelten Stunde der Winterzeit-Umstellung werden richtig zugeordnet.
- Zweite Audit-Runde (frische Prüfer auf die Fixes): **In der App erreichte seit v1.0 keine Fehlermeldung den Nutzer** — bei jedem
  Abbruch stand nur „Dateien wurden während der Berechnung geändert“. Jetzt erscheint die eigentliche Meldung (ohne Python-Details).
  Weitere Lücken der noKYC-Trennung geschlossen (Sammelauszahlung, Schenkung an die eigene KYC-Wallet, gleichnamige Sammelimport-Konten,
  abweichender Betrag ohne Transaktions-ID). Ein Jahr allein mit noKYC-Vorgängen erzeugt keinen leeren Steuerreport/Nachweis mehr
  (betraf auch die Beispieldaten: 2025). Dieselbe Wallet doppelt geladen wird erkannt; Ledger-Konten gleichen Namens werden über alle
  Dateien einheitlich nummeriert; die Kommandozeile zeigt Abbrüche als Meldung statt als Python-Traceback.
- Bisq: der englische Export ist jetzt an einem echten Export des Autors bestätigt (gleiche Trades auf Deutsch und Englisch exportiert,
  Ergebnis feldgleich). Der Hinweis „bitte Ergebnis prüfen“ aus v1.3 gilt für Bisq damit nicht mehr.

## v1.3 — 2026-10-03
- Bisq: auch der **englische Export** wird gelesen (Spaltenköpfe „Trade ID, Date/Time, …“, Werte „Buy BTC“/„Completed“); die
  Zeitstempel der belegten englischen Länder-Einstellungen (GB, US, CA, AU, IN, NZ, DK/FI u. a.) werden erkannt, eine unbekannte
  Form bricht mit Meldung ab, statt falsch gelesen zu werden. Abgeleitet aus dem Bisq-Quellcode und gegen eine
  veröffentlichte Beispieldatei eines echten Exports geprüft, noch nicht gegen einen eigenen — bitte Ergebnis prüfen und Abweichungen melden.
- Bisq: Trades auf Altcoin-Märkten (XMR/BTC, BSQ/BTC …) werden als Veräußerung bzw. Anschaffung von BTC gemeldet statt nur stumm
  gezählt; eine Datei, die nur Verkäufe enthält, bekommt keine zweite Sammelwarnung mehr; eine BOM in der Kopfzeile (Excel) stört nicht mehr.
- **Sammelimport CoinTracking/Blockpit (neu, unbestätigt):** CSV-Exporte aus CoinTracking (Importformat, Handelsliste, Vollansicht)
  und Blockpit (aktuelles und älteres Format) werden gelesen; jedes Konto darin ist eine eigene Wallet, Ein-/Auszahlungen werden
  über die Transaktions-ID mit den BitBox-Exporten verbunden. Die Formate stammen aus der Dokumentation und veröffentlichten
  Beispieldateien, nicht aus einem echten Export: Der Steuerreport zeigt je Datei eine Warnung „Format noch nicht bestätigt“.
  Tausch BTC gegen andere Kryptowährungen, Zuflüsse (Staking, Mining …) und Bezahlungen ohne EUR-Wert im Export werden nicht
  bewertet, sondern laut gemeldet. Konten mit noKYC-Plattformen im Namen (Bisq, RoboSats …) bleiben intern.
- Oberfläche/App: die CSV-Dateien (Käufe, Verkäufe) sind jetzt byte-gleich zur Kommandozeile (Zeilenenden CRLF); bisher LF. Der GUI-Test
  vergleicht die CSV-Dateien seitdem ohne Angleichung der Zeilenenden.
- **Parser-Audit (alle Formate):** Jede Datei wird jetzt vor dem Lesen auf ihre Pflichtspalten geprüft. Bisher machte eine umbenannte
  Spalte oder eine UTF-8-Signatur (BOM, z. B. nach Speichern in Excel als „CSV UTF-8“) aus einer Spalte still „leer“: Pocket-, Bison- und
  Swissquote-Dateien gingen komplett verloren, Strike-Käufe standen mit 0 BTC im Report, Gebühren wurden 0 — ohne jede Meldung.
  Jetzt wird eine BOM überlesen, und eine fehlende oder umbenannte Pflichtspalte bricht den Lauf mit Datei, Zeile und Spalte ab. Ebenso bei Zeilen mit falscher Feldanzahl, einem nicht geschlossenen
  Anführungszeichen (verschluckte bisher den Dateirest), Zeitstempeln ohne Zeitzone, mehrdeutigen Zahlen („2,500“), Nicht-Zahlen,
  negativen Übertragsmengen und leerer Währungsspalte (Swissquote/Pocket buchten einen Fremdwährungsbetrag sonst als EUR).
  Swissquote-Dateien, die als UTF-8 gespeichert wurden, werden gelesen. Eine Datei mit Zeilen, aber ohne eine einzige Transaktion
  wird gemeldet. `manual_sales.csv` und Co. werden unabhängig von Groß-/Kleinschreibung gefunden, fremde CSVs im Hauptordner gemeldet.
  Warnungen sind auf 1.000 je Lauf gedeckelt (vorher war ihre Zahl unbegrenzt), das Log der App auf 5.000 Zeilen,
  ZIP-Inhalte auf 64 MB je Datei / 256 MB gesamt.

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
