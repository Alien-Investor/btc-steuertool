#!/usr/bin/env bash
# Baut die signierte Release-APK des BTC Steuertools: web/dist → mobile/www → Capacitor → Härtung → signierte APK → Endkontrolle.
# Voraussetzung: ~/Apps/android-build/env.sh (Toolchain) + Keystore (einmalig mobile/make-keystore.sh). Muster: Alien Pass build-apk.sh.
set -euo pipefail
cd "$(dirname "$0")"
# Release-Sperre (v1.5, Vorlage Alien Pass v1.22 / Alien Notes v1.14): alte Prüfdateien ZUERST weg, vor jeder anderen Prüfung — ein abgebrochener
# Lauf (auch am Keystore oder am Capacitor-Pin) hinterlässt keine gültige. make-release.sh lädt nur eine APK mit passender .ok hoch.
rm -f build/release/*.ok
# Gebaut wird aus einem PRIVATEN Abbild von HEAD (git worktree), nie aus dem gemeinsamen Arbeitsbaum (Release-Audit v1.5 R2-1 #1): dort liefen
# build-www.sh, icons.py, patch-signing.mjs und patch-hardening.mjs minutenlang nach der Summenbildung — eine zweite Sitzung, die eine Datei
# ändert und zurückstellt (auch „git stash … git stash pop“), bekam eine gültige .ok mit fremdem Inhalt. Darum: sauberer Stand verlangt,
# Abbild außerhalb des Repos, nur web/vendor (nicht versioniert) wird hineinkopiert und dort gegen web/vendor.sha256 aus HEAD geprüft.
REPO="$(cd .. && pwd)"
if [ "${STEUERTOOL_IM_ABBILD:-}" != 1 ] && git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  [ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ] || { echo "FEHLER: nicht committete Änderungen — gebaut wird HEAD, erst committen."; exit 1; }
  [ -d "$REPO/web/vendor" ] || { echo "FEHLER: web/vendor fehlt — web/vendor-setup.sh"; exit 1; }
  mkdir -p "$HOME/.cache/btc-steuertool-abbild"; ABB="$(mktemp -d "$HOME/.cache/btc-steuertool-abbild/apk.XXXXXX")"
  aufraeumen() { git -C "$REPO" worktree remove --force "$ABB/repo" >/dev/null 2>&1 || true; rm -rf "$ABB"; git -C "$REPO" worktree prune || true; }
  trap aufraeumen EXIT
  git -C "$REPO" worktree add -q --detach "$ABB/repo" HEAD
  cp -a "$REPO/web/vendor" "$ABB/repo/web/vendor"
  echo "Abbild von HEAD $(git -C "$ABB/repo" rev-parse --short HEAD): $ABB/repo"
  rc=0; STEUERTOOL_IM_ABBILD=1 bash "$ABB/repo/mobile/build-apk.sh" || rc=$?
  cp "$ABB/repo/mobile/gradle-build.log" gradle-build.log 2>/dev/null || true
  [ "$rc" = 0 ] || { echo "FEHLER: Build im Abbild gescheitert (rc=$rc)"; exit "$rc"; }
  F="btc-steuertool-$(sed -n 's/^VERSION_NAME=//p' "$ABB/repo/VERSION" | tr -d '[:space:]').apk"; mkdir -p build/release
  cp "$ABB/repo/mobile/build/release/$F" "$ABB/repo/mobile/build/release/$F.sha256" build/release/
  cp "$ABB/repo/mobile/build/release/$F.ok" "build/release/$F.ok"   # Prüfdatei zuletzt, nur zu genau dieser APK
  [ "$(sha256sum < "build/release/$F" | cut -d' ' -f1)" = "$(head -1 "build/release/$F.ok")" ] || { rm -f build/release/*.ok; echo "FEHLER: Kopie aus dem Abbild ≠ Prüfdatei"; exit 1; }
  echo "=== mobile/build/release/$F + .ok (aus dem Abbild von HEAD) ==="
  exit 0
fi
# ── ab hier im Abbild (oder Selbstbau ohne Git — dann kein Release-Build) ──
# Prüfsummen aller Quellen VOR dem Build (Liste: release-quellen.sh): die .ok trägt genau den Stand, aus dem gebaut wurde; ändert sich
# eine Quelle während des Builds, gibt es keine .ok
source ../release-quellen.sh
SUMS0="$(cd .. && quellen_summen apk)" || { echo "FEHLER: Quellenliste unvollständig (release-quellen.sh)"; exit 1; }
CERT_HEX="26c5e094a8b7650ca665014d0c3a8ba682b17c05f53c6cdef055d07ce984bf0b"   # Release-Zertifikat (wie make-release.sh)
source ~/Apps/android-build/env.sh
KEYPROPS="$HOME/.android-keys/steuertool-keystore.properties"
[ -f "$KEYPROPS" ] || { echo "FEHLER: $KEYPROPS fehlt (einmalig mobile/make-keystore.sh)."; exit 1; }

# Capacitor-Pin wie Alien Pass (26.09.2026): jede Abweichung stoppt, bis die Android-Schicht geprüft ist
# (Bridge.launchIntent → LinkGuard, BridgeWebViewClient.shouldInterceptRequest → CSP-Header, Start-Intent-Extras).
CAP_PIN="6.2.2"
# Release-Builds immer frisch (Release-Audit v1.5 R1 b-B1): node_modules aus dem Lock (npm prüft die Integrity jedes Pakets; Gradle kompiliert
# den Capacitor-Kern direkt aus node_modules), keine Konfiguration, die vor capacitor.config.json gelesen würde, und android/ neu erzeugt —
# ein über Wochen wiederverwendetes android/ trüge Reste, die keine Quelle beschreibt.
for c in capacitor.config.ts capacitor.config.js capacitor.config.mjs capacitor.config.cjs; do
  [ ! -e "$c" ] || { echo "FEHLER: mobile/$c vorhanden — die CLI läse sie vor capacitor.config.json. Entfernen."; exit 1; }
done
npm ci --ignore-scripts --no-audit --no-fund
lock_gleich . || { echo "FEHLER: node_modules ≠ package-lock.json nach npm ci"; exit 1; }   # Release-Audit R2-1 #2
for m in android core cli; do
  v="$(node -p "require('./node_modules/@capacitor/$m/package.json').version" 2>/dev/null || echo fehlt)"
  [ "$v" = "$CAP_PIN" ] || { echo "FEHLER: @capacitor/$m ist $v, gepinnt $CAP_PIN — erst Review der Android-Schicht, dann CAP_PIN anheben."; exit 1; }
done

./build-www.sh
rm -rf android   # eigener Befehl: links von && griffe set -e nicht (Release-Audit R2-1 #5)
[ ! -e android ] || { echo "FEHLER: android/ ließ sich nicht entfernen"; exit 1; }
npx cap add android
echo "sdk.dir=$ANDROID_HOME" > android/local.properties
npx cap sync android
# App-Icon: dasselbe Motiv wie die Desktop-App (desktop/icon.png), in alle mipmap-Dichten
python3 -P icons.py   # -P: kein Modul aus mobile/ vor der Standardbibliothek (Release-Audit R1 b-B1)
node patch-signing.mjs
node patch-hardening.mjs

( cd android && ./gradlew assembleRelease --no-daemon -q ) > gradle-build.log 2>&1 || { tail -30 gradle-build.log; echo "FEHLER: Gradle-Build"; exit 1; }
APK="android/app/build/outputs/apk/release/app-release.apk"
[ -f "$APK" ] || { echo "FEHLER: $APK fehlt"; exit 1; }
APKSUM0="$(sha256sum "$APK" | cut -d' ' -f1)"   # Hash VOR der Endkontrolle: die .ok gilt nur für genau diese Bytes

# ── Endkontrolle an der FERTIGEN APK (Manifest-Merging darf nichts einschleusen) ──
BT="$ANDROID_HOME/build-tools/34.0.0"
PERMS="$("$BT/aapt" dump permissions "$APK")"; MAN="$("$BT/aapt" dump xmltree "$APK" AndroidManifest.xml)"
# Erlaubt ist nur die AndroidX-Signatur-Permission der App selbst (DYNAMIC_RECEIVER_NOT_EXPORTED, kein Recht nach außen)
BAD="$(grep -E "^uses-permission" <<<"$PERMS" | grep -vE "name='org\.alieninvestor\.steuertool\.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION'" || true)"
[ -z "$BAD" ] || { echo "FEHLER: APK deklariert eine Berechtigung:"; echo "$BAD"; exit 1; }
grep -qE 'android:debuggable\(0x[0-9a-f]+\)=\(type 0x12\)0xffffffff' <<<"$MAN" && { echo "FEHLER: APK ist debuggable!"; exit 1; }
grep -qE 'android:allowBackup\(0x[0-9a-f]+\)=\(type 0x12\)0x0$' <<<"$MAN" || { echo "FEHLER: allowBackup nicht false!"; exit 1; }
grep -qE 'android:dataExtractionRules\(0x[0-9a-f]+\)=@0x[0-9a-f]+' <<<"$MAN" || { echo "FEHLER: dataExtractionRules fehlen!"; exit 1; }
RULES_OK=0; for x in $(unzip -Z1 "$APK" 'res/*.xml'); do D="$("$BT/aapt" dump xmltree "$APK" "$x" 2>/dev/null || true)"
  if grep -q "E: data-extraction-rules" <<<"$D" && grep -q "E: cloud-backup" <<<"$D" && grep -q "E: device-transfer" <<<"$D" && [ "$(grep -c 'domain.*="root"' <<<"$D")" -ge 2 ]; then RULES_OK=1; break; fi; done
[ "$RULES_OK" = 1 ] || { echo "FEHLER: data-extraction-rules unvollständig!"; exit 1; }
# config.xml (Ressourcenname im Release verkürzt): DisableDeploy=true, sonst kann Seiten-JS den App-Ursprung dauerhaft umlenken (Audit run-1)
DEPLOY_OK=0; for x in $(unzip -Z1 "$APK" 'res/*.xml'); do D="$("$BT/aapt" dump xmltree "$APK" "$x" 2>/dev/null || true)"
  if grep -q "E: :widget" <<<"$D" && grep -A2 'E: :preference' <<<"$D" | grep -A1 'name="DisableDeploy"' | grep -q 'value=(type 0x12)0xffffffff'; then DEPLOY_OK=1; break; fi; done
[ "$DEPLOY_OK" = 1 ] || { echo "FEHLER: DisableDeploy fehlt in der APK-config.xml!"; exit 1; }
# Bytecode: beide Plugins, CSP-Header, Speichern-Dialog (FLAG_SECURE prüft patch-hardening.mjs am erzeugten Java)
DEXTMP="$(mktemp -d)"; unzip -q -o "$APK" 'classes*.dex' -d "$DEXTMP"
DEX=""; for d in "$DEXTMP"/classes*.dex; do DEX+="$("$BT/dexdump" -d "$d" 2>/dev/null | grep -aE 'org/alieninvestor/steuertool|const-string' || true)"; done
rm -r "$DEXTMP"
for pat in 'Lorg/alieninvestor/steuertool/SaveFilePlugin;' 'Lorg/alieninvestor/steuertool/LinkGuardPlugin;' '"Content-Security-Policy"' \
           "connect-src 'self'" '"android.intent.action.CREATE_DOCUMENT"|ACTION_CREATE_DOCUMENT'; do
  grep -aEq -- "$pat" <<<"$DEX" || { echo "FEHLER: fehlt im Bytecode: $pat"; exit 1; }
done
# FLAG_SECURE im Bytecode der FERTIGEN APK, nicht nur im erzeugten Java (Release-Audit v1.5 R2-1 #1): MainActivity.onCreate lädt 8192
# (FLAG_SECURE) und übergibt genau dieses Register an Window.addFlags; keine eigene Klasse ruft Window.clearFlags
DEXTMP="$(mktemp -d)"; unzip -q -o "$APK" 'classes*.dex' -d "$DEXTMP"; MAINDEX=""; OWNDEX=""
for d in "$DEXTMP"/classes*.dex; do DD="$("$BT/dexdump" -d "$d" 2>/dev/null || true)"
  MAINDEX+="$(awk '/Class descriptor.*Lorg\/alieninvestor\/steuertool\/MainActivity;/{f=1;next} f&&/Class descriptor/{f=0} f' <<<"$DD")"
  OWNDEX+="$(awk '/Class descriptor.*Lorg\/alieninvestor\/steuertool\//{f=1;next} f&&/Class descriptor/{f=0} f' <<<"$DD")"; done
rm -rf "$DEXTMP"
OC="$(awk '/name *: .onCreate./{f=1} f&&/catches/{exit} f' <<<"$MAINDEX")"
R8192="$(grep -oE 'const/16 v[0-9]+, #int 8192' <<<"$OC" | head -1 | grep -oE 'v[0-9]+' || true)"
[ -n "$R8192" ] && grep -qE "invoke-virtual \{v[0-9]+, $R8192\}, Landroid/view/Window;\.addFlags:\(I\)V" <<<"$OC" || { echo "FEHLER: FLAG_SECURE fehlt im Bytecode von MainActivity.onCreate!"; exit 1; }
! grep -q 'Landroid/view/Window;\.clearFlags' <<<"$OWNDEX" || { echo "FEHLER: eigene Klasse ruft Window.clearFlags!"; exit 1; }
grep -q "Content-Security-Policy" android/app/src/main/assets/public/index.html || { echo "FEHLER: CSP-Meta fehlt in der eingebetteten index.html"; exit 1; }
"$BT/apksigner" verify "$APK" >/dev/null || { echo "FEHLER: Signatur ungültig"; exit 1; }
CERT="$("$BT/apksigner" verify --print-certs "$APK" 2>/dev/null | grep -m1 'SHA-256 digest' | awk '{print $NF}' || true)"
[ "$CERT" = "$CERT_HEX" ] || { echo "FEHLER: APK nicht mit dem Release-Zertifikat signiert (${CERT:-keins})"; exit 1; }
echo "APK-Endkontrolle OK (keine Berechtigung, nicht debuggable, kein Backup, SaveFile + LinkGuard, CSP, FLAG_SECURE im Bytecode)."

VNAME=$(grep '^VERSION_NAME=' ../VERSION | cut -d= -f2 | tr -d '[:space:]')
mkdir -p build/release
OUT="build/release/btc-steuertool-$VNAME.apk"
cp "$APK" "$OUT"
# Nur ein Build, der JEDE Prüfung oben bestanden hat und dessen Quellen sich nicht geändert haben, bekommt die Prüfdatei
# (1. Zeile APK-Hash, danach die Quellen-Summen; make-release.sh gleicht sie mit dem Tag ab)
[ "$(sha256sum "$APK" | cut -d' ' -f1)" = "$APKSUM0" ] && [ "$(sha256sum "$OUT" | cut -d' ' -f1)" = "$APKSUM0" ] \
  || { echo "FEHLER: APK hat sich während der Endkontrolle geändert (paralleler Build?)!"; exit 1; }
[ "$(cd .. && quellen_summen apk)" = "$SUMS0" ] || { echo "FEHLER: Quellen haben sich während des Builds geändert — neu bauen!"; exit 1; }
# Inhalt der fertigen APK gegen die Quellen VOR dem Build (Release-Audit R1 b-B1): www-Teil, vendor, index.html samt CSP, Capacitor-Dateien,
# Konfiguration, Dateimenge — dieselbe Prüfung macht make-release.sh gegen den Tag
CHK="$(mktemp -d)"; printf '%s\n' "$SUMS0" > "$CHK/quellen.sum"; unzip -q "$OUT" 'assets/*' -d "$CHK/x"
(cd .. && apk_inhalt "$CHK/x" "@$CHK/quellen.sum") || { rm -rf "$CHK"; echo "FEHLER: Inhalt der APK ≠ Quellen vor dem Build — neu bauen!"; exit 1; }
rm -rf "$CHK"
lock_gleich . || { echo "FEHLER: node_modules hat sich während des Builds geändert"; exit 1; }
( cd build/release && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
{ echo "$APKSUM0"; echo "$SUMS0"; } > "$OUT.ok"
echo "Prüfdatei: $OUT.ok ($(($(wc -l < "$OUT.ok") - 1)) Quellen)"
"$BT/apksigner" verify --print-certs "$OUT" | grep -E "SHA-256 digest" | head -1
ls -lh "$OUT"
