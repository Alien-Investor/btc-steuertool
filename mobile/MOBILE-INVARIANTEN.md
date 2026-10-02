# MOBILE-INVARIANTEN.md — BTC Steuertool Android (Capacitor)

Vor jeder Änderung an `mobile/` oder an der Weiche `DROID` in `web/index.html` hier lesen. Vorlage ist Alien Pass
(`~/projekte/alien-pass/`: `build-apk.sh`, `patch-hardening.mjs`, `patch-signing.mjs`), Schwester-Hülle ist `desktop/`
(`desktop/DESKTOP-INVARIANTEN.md`). Was dort begründet ist, gilt hier sinngemäß.

## Grundsatz
- **Ein Code, kein Fork.** Die APK enthält `web/dist` unverändert (Ergebnis von `web/build.sh`), `mobile/build-www.sh` setzt nur das
  CSP-Meta-Tag ein. Alles Android-Spezifische in der GUI hängt an `DROID` (gleiche Schnittstelle wie `DESK`: `saveFile(name, bytes)`),
  gemeinsames App-Verhalten an `SHELL = DESK || DROID`, der App-Kopf an `html.app` (frühes Skript im `<head>`).
- **Engine nie in JS nachbauen.** Pyodide läuft im Web-Worker wie im Web — am Gerät gemessen 02.10.2026: Rechenkern 1–2 s, Berechnen sofort.
- **`mobile/android/` ist generiert** (gitignored, `npx cap add android` + `cap sync`). Jede Änderung an Android-Dateien gehört in
  `patch-hardening.mjs` / `patch-signing.mjs` / `icons.py`, nie direkt nach `android/`.
- **Capacitor gepinnt** (`6.2.2`, exakt in `package.json`, `CAP_PIN` in `build-apk.sh`, Stand wie Alien Pass). Anheben nur nach Review von
  `Bridge.launchIntent` (LinkGuard hängt daran), `BridgeWebViewClient.shouldInterceptRequest` (CSP-Header) und `WebViewLocalServer`
  (`.wasm` muss `application/wasm` bleiben).

## Härtung (`patch-hardening.mjs`, Endkontrolle in `build-apk.sh` an der FERTIGEN APK)
- **Keine Berechtigung**, auch nicht INTERNET. Erlaubt ist nur die AndroidX-Signatur-Permission der App selbst. Pyodide, Stdlib, `src/*.py`
  und die Kurstabellen kommen aus der APK über Capacitors lokalen Server (`https://localhost`).
- `allowBackup=false` + `dataExtractionRules` (root-Ausschluss Cloud und Gerät-zu-Gerät), nicht debuggable.
- **FLAG_SECURE** (Steuerzahlen, Bestände). Keine `confirm()`/`alert()` in der GUI verwenden — Systemdialoge erben FLAG_SECURE nicht.
- WebView enger als Capacitor-Standard: keine Geolocation, keine Fenster per JS, `allowFileAccess=false`.
- **CSP doppelt:** Meta-Tag (Seite, ab dem ersten Byte) + Antwort-Header über den eigenen `BridgeWebViewClient` (gilt auch für den Worker,
  das Meta-Tag nicht). Inhalt = `CSP` aus `desktop/main.js`, `connect-src 'self'` (Pyodide fetcht vom eigenen Ursprung), `'unsafe-inline'`
  wie Desktop/Web (GUI-Inline-Skript; Capacitor injiziert seine Brücke ebenfalls inline).
- **LinkGuard** (Plugin, `shouldOverrideLoad`): keine Navigation weg von `https://localhost`. Nach außen nur die Liste `LINKS` und ein `mailto`
  an `MAIL` mit höchstens `subject`/`body` und ≤ `MAIL_MAX` Zeichen — beides **aus `desktop/main.js` gelesen** (eine Liste für Flatpak und APK).
  Neuer Link in der GUI = Eintrag in `desktop/main.js` `LINKS` + Desktop-Test; die APK übernimmt ihn beim nächsten Build.
- **SaveFile** (Plugin, einzige Brücke): `save({name, data(base64)})` → Android-Speichern-Dialog (SAF `ACTION_CREATE_DOCUMENT`), Name
  `^[\w.-]{1,120}\.(txt|csv|zip)$`, ≤ 50 MB, Schreiben mit `"wt"` (überschreibt sauber). Abbruch → `{saved:false}` → GUI meldet nichts.
- Import bleibt `<input type=file multiple>` ohne `accept` (Capacitor-Dateiauswahl, Mehrfachauswahl + ZIP am Gerät bestätigt 02.10.2026).

## Weiche in `web/index.html`
- `html.app`: App-Kopf wie Alien Pass / Tresor / Notes (Sprache links, „?“ rechts, Logo mittig), Website-Leiste (Zentrale, BETA) aus,
  Darstellung Neon/Soft als Leiste im Fuß. Gilt für Flatpak und APK.
- `SHELL`: Titel ohne „im Browser“, Knöpfe „…speichern“, Downloads (auch Beispieldaten-ZIP) über `saveFile`.
- `DROID`: Privacy-Text `privacyDroid`, Dropzone „antippen“ statt „ziehen“ (`dzLeadTouch`/`dzTryTouch`), Bug-Report-Version „Android“.

## Bauen, Testen, Release
- Keystore einmalig: `mobile/make-keystore.sh` → `~/.android-keys/steuertool-release.jks` + `steuertool-keystore.properties` (chmod 600,
  Passwort nie ausgeben). Zertifikat SHA-256 `26c5e094a8b7650ca665014d0c3a8ba682b17c05f53c6cdef055d07ce984bf0b`.
- Bauen: `mobile/build-apk.sh` → `mobile/build/release/btc-steuertool-<VERSION_NAME>.apk` + `.sha256`.
- Version: `VERSION` im Repo-Root, `VERSION_CODE` **je Release hochzählen** (sonst kein Update bei Android/Obtainium).
- Gerätetest (kein adb): APK in `~/Sync/sachwert-tresor/`, Beispieldaten → „Alle Dateien speichern (ZIP)“ in den Sync-Ordner,
  dann am Rechner gegen die CLI-Referenz vergleichen (`--all --nachweis --csv`). 02.10.2026: 18/18 Dateien byte-gleich.
- Release über Skill `app-release` (Android-Zweig) gemeinsam mit dem Flatpak.
