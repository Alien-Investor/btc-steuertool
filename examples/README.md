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
bitbox/       ← BitBox-Exporte
Broker/       ← Broker-Exporte (21bitcoin, Bison, Swissquote, Strike, Pocket)
manual_sales.csv  ← optionale P2P-Verkäufe
```

Diese Ordner sind in `.gitignore` eingetragen und werden nie committed.
