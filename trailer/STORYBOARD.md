# App-Trailer BTC Steuertool – Storyboard (Stand 2026-10-02)

Wortloser Trailer für die App-Karte auf apps.html, DE + EN aus einem Schnitt, Muster der App-Trailer (Vorlage `~/projekte/alien-notes/trailer/`,
Regeln in Obsidian `wissen/app-trailer.md`). Sechster App-Trailer. **Nur 16:9**, kein Short.
Kernbotschaft (Autor 02.10.2026): **Steuerdaten müssen nicht auf fremde Server, alles bleibt lokal bei dir.**

## Eckdaten

| | 16:9-Master |
|---|---|
| Länge | 57,2 s, 1920×1080, 25 fps |
| Ton | `musik/steuertool-web-bett.wav` (120-s-Schnitt von `youtube-videos-automatik/btc-steuertool-web/audio/background_01.wav`, Suno-Instrumental des Steuertool-Tutorials), 1 s Fade-in, 3 s Fade-out, loudnorm −16 LUFS |
| Bild | Screenshots v1.1 aus `web/dist` mit Android-Optik (Capacitor-Stub), Beispieldaten aus `examples/`, 412×880 bei 3× (`make_shots.py`) |
| Sprache | Karten DE/EN, App-Oberfläche über `?lang=`; die Reports selbst bleiben deutsch (Finanzamt-Dokumente) |

## Szenenliste

| Nr. | Dauer | Bild | Karte DE | Karte EN |
|---|---|---|---|---|
| 1 | 4,5 s | Motiv (Icon, Glow) | **Wem gibst du deine Steuerdaten?** | **Who gets your tax data?** |
| 2 | 5,5 s | Motiv | Cloud-Steuertools wollen jede Transaktion auf ihrem Server. | Cloud tax tools want every transaction on their server. |
| 3 | 5 s | Dropzone | Das BTC Steuertool rechnet auf deinem Gerät. Kein Upload, kein Konto, keine Telemetrie. | BTC Steuertool calculates on your device. No upload, no account, no telemetry. |
| 4 | 5 s | Start (App-Kopf, Datenschutz-Leiste) | Die App hat nicht einmal eine Internet-Berechtigung. | The app does not even have an internet permission. |
| 5 | 4,4 s | Dateiliste (erkannte Broker, noKYC orange) | CSV-Exporte rein, die App erkennt jeden Broker am Inhalt | Drop in CSV exports, every broker detected by its content |
| 6 | 4,4 s | Steuerreport 2024 | FiFo mit Jahresfrist nach Kalenderdatum und Freigrenze | FiFo with the one-year holding period and the exemption limit |
| 7 | 4,4 s | Abschnitt „Gebühren in Bitcoin“ + Schenkungen | Gebühren in Bitcoin als Veräußerung, Schenkungen als Abgang | Fees paid in bitcoin as disposals, gifts as outflows |
| 8 | 4,4 s | Steuernachweis 2024 | Formaler Steuernachweis fürs Finanzamt | Formal tax evidence for the German tax office |
| 9 | 4,4 s | noKYC intern (Warnkopf) | noKYC strikt getrennt, nie in den Unterlagen fürs Finanzamt | noKYC kept strictly apart, never in the tax office documents |
| 10 | 4,4 s | Speichern-Knöpfe | Alle Reports als ZIP speichern | Save all reports as one ZIP |
| 11 | 4,4 s | Handbuch („?“) | Handbuch in der App, Deutsch und Englisch | In-app guide in German and English |
| 12 | 5,5 s | Motiv | Derselbe Rechenkern wie CLI und Web-Version. Open Source. Auch als Flatpak für Linux. | Same calculation core as the CLI and the web version. Open source. Also a Flatpak for Linux. |
| 13 | 5 s | Titelbild „BTC Steuertool“ | — | — |
| 14 | 5 s | Endkarte, QR | **Deine Steuerdaten bleiben bei dir.** Kostenlos und Open Source. Zap Store, Obtainium oder direkt als APK. | **Your tax data stays with you.** Free and open source. Zap Store, Obtainium or directly as an APK. |

QR: DE `https://alien-investor.org/btc-steuertool.html#app`, EN `https://alien-investor.org/en/btc-steuertool.html#app`
(Matrix-Vergleich gegen die Soll-URL 1369/1369, 02.10.2026). Im Bild keine Plattform- oder Hosternamen (Regel seit 01.10.2026).

## Ablauf

```bash
web/build.sh && python3 -m http.server 8741 --directory web/dist &
cd trailer && python3 make_shots.py && python3 make_frames.py && python3 make_cards.py
./build_trailer.sh de && ./build_trailer.sh en && python3 make_thumbs.py
python3 embed_website.py <ID_DE> <ID_EN>        # nach dem Upload
```
`out/`, `musik/`, `shots/`, `frames/`, `cards/`, `thumbs/` sind gitignored.
