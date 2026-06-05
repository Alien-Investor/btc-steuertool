# Beispieldaten

Dieser Ordner enthält **fiktive Testdaten** zum Ausprobieren des Tools.

Alle Beträge, Daten und Adressen sind erfunden — keine echten Transaktionen.

## Testen

```bash
python src/main.py --data-dir examples/ --all
python src/main.py --data-dir examples/ --year 2024 --csv --nachweis
```

## Echte Daten

Eigene CSV-Dateien gehören in die entsprechenden Ordner im Projektverzeichnis:

```
bitbox/           ← BitBox-Exporte (KYC-Wallets)
bitbox/nokyc/     ← optionale dedizierte noKYC-Wallets (nur interner Report)
Broker/           ← Broker-Exporte (21bitcoin, Bison, Swissquote, Strike, Pocket, Bisq)
manual_buys.csv   ← optionale noKYC-Käufe (Robosats, P2P, Bargeld)
manual_sales.csv  ← optionale P2P-Verkäufe (Spalte no_kyc=ja für noKYC-Bestände)
```

Diese Ordner sind in `.gitignore` eingetragen und werden nie committed.
