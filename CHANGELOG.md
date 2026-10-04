# Changelog — BTC Steuertool (Apps: Linux-Desktop + Android)

Das CLI und die Web-Version haben keine eigenen Versionen; sie laufen immer auf dem Stand von `main`.
Dieses Änderungsprotokoll gilt für die App-Fassungen (Flatpak + APK), die denselben Rechenkern enthalten.

## Unveröffentlicht (main)
- **Versionsnummer in der App:** klein im Fuß („v1.4“; die Web-Version zeigt „Web · Stand <Datum>“, weil sie immer den aktuellen
  Stand ausliefert). Die Version steht auch im Bug-Report und in der Diagnose.
- **Desktop: Spenden- und Handbuch-Links bleiben auch nach dem Zurückstellen der Systemuhr klickbar.** Die Sperre gegen
  Fensterfluten (höchstens ein Link je Sekunde) rechnete mit der Systemuhr; wurde sie zurückgestellt (Zeitabgleich, Aufwachen
  mit falscher Uhrzeit), öffnete kein Link mehr, bis die Uhr den alten Stand wieder erreichte. Jetzt läuft die Sperre auf
  einer Uhr, die nie zurückspringt.

## v1.4 — 2026-10-03
- **Neu: Wallet-Exporte aus Sparrow, Electrum, Trezor Suite und Ledger Wallet (früher Ledger Live).** Das Programm wird an
  der Kopfzeile erkannt, auch bei älteren Versionen. Jede Wallet ist ein eigener Bestand, bei Ledger jedes Konto. Überträge
  zu Börsen und anderen Wallets verbindet die App über die Transaktions-ID; Netzwerkgebühren und Überweisungen an sich selbst
  werden wie bei der BitBox gebucht, Schenkungen am Wort im Label (nicht bei Ledger, dessen Export kein Label hat). In den
  Finanzamt-Dokumenten heißen sie nur „Sparrow-Wallet“, „Trezor-Wallet 1“ usw. Die Formate stammen aus dem Quellcode der
  Programme und sind noch nicht an echten Exporten bestätigt; der Steuerreport weist je Datei darauf hin. Electrum-Zeiten
  (ohne Zeitzone) gelten als deutsche Ortszeit; Lightning-Zahlungen werden gemeldet, nicht erfasst. In der App: Typ
  „Sparrow/Electrum/Trezor/Ledger (KYC/noKYC)“.
- **Neu: Diagnose für Bug-Reports.** Im Dialog „Bug melden“ erstellt die App auf Wunsch eine Diagnose: erkannte Dateitypen,
  Zeilenzahl, Aufbau der ersten Zeile nicht erkannter Dateien (nur bekannte Spaltennamen) und die Meldungen der letzten
  Berechnung. Dateinamen, Beträge, Tagesdaten, Adressen und Wallet-Namen werden geschwärzt, Jahreszahlen und Zeilennummern
  bleiben stehen; Dateien, die noKYC sein können, werden nur gezählt. Du siehst die Diagnose vor dem Senden vollständig.
  „Log speichern“ sichert das volle Log nur für dich.
- **Fehlermeldungen kommen an:** Seit v1.2 zeigte die App bei jedem Abbruch nur „Dateien oder Einstufung wurden während der Berechnung
  geändert“. Jetzt erscheint die eigentliche Meldung.
- **noKYC-Trennung verschärft:** Kommen noKYC-Coins in einer KYC-Wallet an, bricht die Berechnung jetzt auch ab, wenn die
  Gebühr im Export fehlt, beide Wallets gleich heißen, bei Sammelauszahlungen, Schenkungen an die eigene Wallet,
  gleichnamigen Sammelimport-Konten und abweichendem Betrag ohne Transaktions-ID. Ein Jahr nur mit noKYC-Vorgängen erzeugt
  keinen leeren Steuerreport und Nachweis mehr (betraf auch die Beispieldaten, 2025).
- **Doppelt geladene Wallets** (Jahres- und Gesamtexport, dieselbe Wallet in BitBoxApp und Sparrow) werden erkannt.
- **Robuster:** Lädt der Rechenkern nicht, meldet die App das nach spätestens zwei Minuten (vor allem Web-Version), ein neuer
  Versuch klappt ohne Neuladen. `transfer_zuordnung.csv` aus Excel (Windows-1252) wird gelesen.
- **Bisq:** Der englische Export ist an einem echten Export bestätigt; der Prüfhinweis aus v1.3 entfällt.

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
