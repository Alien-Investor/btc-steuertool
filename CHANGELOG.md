# Changelog — BTC Steuertool (Apps: Linux-Desktop + Android)

Das CLI und die Web-Version haben keine eigenen Versionen; sie laufen immer auf dem Stand von `main`.
Dieses Änderungsprotokoll gilt für die App-Fassungen (Flatpak + APK), die denselben Rechenkern enthalten.

## v1.0 — 2026-10-02
- Erste Veröffentlichung als App: **Linux-Desktop (Flatpak)** und **Android (APK)**, frei und quelloffen.
- Derselbe Rechenkern wie CLI und Web-Version (FiFo nach § 23 EStG, Jahresfrist, Freigrenze, Gebühren in Bitcoin
  als Veräußerung des Gebührenanteils, Schenkungen/Spenden als Bestandsabgang), Reports byte-gleich zum CLI.
- Ohne Netz: Rechenkern (Pyodide), EZB-Wechselkurse und BTC-Tagesschlusskurse sind eingebaut. Das Flatpak hat kein
  Netz- und kein Dateisystem-Recht, die Android-App hat keine Internet-Berechtigung (im Manifest steht nur die von AndroidX erzeugte
  app-eigene Signatur-Berechtigung, die nichts freigibt), Screenshots gesperrt.
- CSVs und ZIPs über den Datei-Dialog, Reports über den Speichern-Dialog; Handbuch in der App („?“, Deutsch/Englisch).
- Vor dem Release internes Security-Audit (Funde behoben, siehe Repo-Historie).
