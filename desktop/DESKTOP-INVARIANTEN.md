# DESKTOP-INVARIANTEN.md — BTC Steuertool Desktop (Linux, Electron im Flatpak)

Vor jeder Änderung an `desktop/` oder an der Weiche `DESK` in `web/index.html` hier lesen. Vorlage ist die Hülle von Alien Pass
(`~/projekte/alien-pass/desktop/`, dort Audits run-6 bis run-8). Was hier nicht abweicht, gilt dort begründet.
Tests: `node desktop/verify-desktop.mjs` (echte Hülle, gepinntes Electron, Reports byte-gleich zur CLI) plus `web/test_gui.py` und
`web/test_lang.py` (Web-Version ohne Hülle). Rechte des Käfigs prüft `desktop/build-desktop.sh`.
Jeder Prüfschritt endet mit der Marke „Schritt vollständig“; fehlt sie oder endet der Schritt per Signal/Zeitlimit, ist `verify-desktop` rot
(ein still vorzeitig beendeter Schritt bliebe sonst grün, Querfund Alien Notes v1.7). Neuer Schritt = Endmarke mitgeben.

## Grundsatz
- **Ein Code, kein Fork.** Die Hülle lädt `web/dist` (Ergebnis von `web/build.sh`) unverändert. Alles Desktop-Spezifische in der GUI hängt an
  `const DESK = window.AlienDesktop || null` (Anfang des Haupt-Skripts). Ohne Hülle verhält sich die Web-Version wie vorher.
- **Engine nie in JS nachbauen.** Rechnen tut `src/` in Pyodide, wie in der Web-Version.
- **Flatpak ohne `--share=network` und ohne `--filesystem`.** Im Käfig gibt es nur `lo`, das Home ist unsichtbar. Dateien kommen nur über
  das Portal herein (Datei-Dialog, Drag&Drop über das Dokument-Portal, beides am Gerät bestätigt 02.10.2026) und gehen nur über den
  Speichern-Dialog hinaus. Chromium-Sandbox über `zypak-wrapper`, kein `--no-sandbox`.
- **Rechte-Endkontrolle zweimal** in `build-desktop.sh`: am gebauten `build/fp/metadata` vor der Installation und an der installierten App,
  exakter Soll-Vergleich (`shared=ipc;` / `sockets=wayland;fallback-x11;` / `devices=dri;`), keine Sperrliste. Neues Recht = Soll bewusst ändern.
- **Electron gepinnt** (Version + SHA-256 des Archivs in `build-desktop.sh`, derselbe Stand wie Alien Pass / Sachwert-Tresor),
  `strip: false` + `no-debuginfo`. **Fuses** wie Alien Pass (`pack.mjs`, nach dem Setzen aus dem Binary zurückgelesen),
  `WasmTrapHandlers` an (Pyodide).

## Hauptprozess (`main.js`)
- Eigenes Schema `app://steuertool`, **`supportFetchAPI:true` ist Pflicht**: ohne hängt der Pyodide-Worker beim Start (fetch auf `app://`
  scheitert still) — gemessen 02.10.2026. `standard` + `secure` wie Alien Pass.
- `serve()`: nur Dateien unter `www/`, nur bekannte Endungen. `.wasm` MUSS `application/wasm` sein (instantiateStreaming); `.py`, `.csv`,
  `.json`, `.zip`, `.whl` holt der Worker per fetch. Path-Traversal und fremde Hosts → 404 (Test).
- **CSP als Antwort-Header** (ersetzt die nginx-CSP der Web-Version): `connect-src 'self'`, **nicht `'none'`** — Pyodide holt Wasm, Stdlib
  und `src/*.py` per fetch vom eigenen Ursprung. Nach außen sperren zusätzlich Käfig, toter Proxy, `host-resolver-rules` und der
  `webRequest`-Filter. `'unsafe-inline'` bleibt, weil die GUI Inline-Skript und `onclick` nutzt (wie im Web).
- **Links:** keine Navigation, keine neuen Fenster. Nur die feste Liste `LINKS` (exakter URL-Vergleich, keine Präfixe) und `mailto:` an
  genau `kontakt@alien-investor.org` mit höchstens `subject`/`body`, ohne `#`-Fragment und ≤ 8000 Zeichen (kaputte %-Kodierung = ungültig,
  `mailOk` wirft nie) gehen per `shell.openExternal` an den System-Browser
  bzw. das Mailprogramm (OpenURI-Portal, kein Flatpak-Recht nötig). Neuer Link in der GUI = Eintrag in `LINKS` + Test.
  **`LINKS`, `MAIL`/`MAIL_MAX` und `CSP` liest auch die APK** (`mobile/patch-hardening.mjs`, per Regex) — Form der drei Zeilen beibehalten,
  sonst bricht der APK-Build mit Fehler ab (gewollt, nie still).
- **Link-Bremse auf monotoner Uhr:** `openOutside` lässt höchstens einen Link je Sekunde durch, gemessen mit `performance.now()` und
  `lastOut=-Infinity` — nie `Date.now()` (zurückgestellte Systemuhr legte den Link still, Querfund Alien Pass v1.18). Der Harness ruft
  die Handler direkt auf (`app.emit('web-contents-created',…)`, Chromium kanonisiert URLs sonst vorher) und prüft die Bremse mit
  einem um 1 h zurückgestellten `Date.now`.
- **Brücke = genau `saveFile(name, bytes)`.** Name `^[\w.-]{1,120}\.(txt|csv|zip)$`, nur `Uint8Array`, ≤ 50 MB, Aufruf nur vom obersten Frame
  der eigenen Seite. Speichern-Dialog (Portal), atomar über `atomic.js`; Rückfall auf direktes Schreiben nur für ein NEUES Ziel.
  Temp-Datei mit Zufallsnamen, `O_EXCL|O_NOFOLLOW` (kein Umlenken über einen vorbereiteten Symlink, kein Sperren durch Absturz-Reste).
  Browser-Downloads bleiben gesperrt (`will-download`).
- Verweigert `--remote-debugging-*`, nur eine Instanz, Berechtigungen alle aus, Rechtschreibprüfung aus, kein Menü, DevTools aus.
- Kein Datenspeicher: die App legt keine Nutzerdaten ab. `localStorage` hält nur Sprache und Darstellung.

## Weiche in `web/index.html`
- `downloadBlob` → `DESK.saveFile` (Speichern-Dialog), Knöpfe heißen am Desktop „speichern“ statt „herunterladen“.
- Eigene Download-Links (`a[download]`, Beispieldaten-ZIP) laufen am Desktop über denselben Weg (delegierter Klick-Handler, weil
  `applyLang` die Dropzone neu schreibt).
- App-Kopf (`html.app`, Flatpak + APK): Sprache links, „?“ rechts wie Alien Pass, Website-Leiste aus, Darstellung Neon/Soft im Fuß.
- Privacy-Strip mit Desktop-Text (`privacyDesk`, kein „Code kommt vom Server“), „← Zentrale“ ausgeblendet, Bug-Report nennt „Desktop“.
- Handbuch („?“-Knopf, Overlay, DE/EN) liegt offline in der GUI — gilt für Web, Desktop und APK gleich.

## Release
`VERSION` im Repo-Root: `VERSION_NAME` (App-Version, auch Kurstabellen-Update im Januar) und `DESKTOP_REV` (nur reiner Electron-Neubau,
ergibt `-rN` im Dateinamen). Bundle + `SHA256SUMS` in `desktop/build/release/`, der Autor signiert `SHA256SUMS` mit dem Release-Schlüssel
`100F9E25BFAEA807DBC357D750C0D78583BFCB81`. Update beim Nutzer = deinstallieren + installieren (Daten gibt es keine).
Pflege-Takt wie die anderen Apps: Electron-Neubau spätestens alle ~5 Monate. Ablauf: Skill `app-release`, Desktop-Zweig.
