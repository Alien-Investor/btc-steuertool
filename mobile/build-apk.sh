#!/usr/bin/env bash
# Baut die signierte Release-APK des BTC Steuertools: web/dist → mobile/www → Capacitor → Härtung → signierte APK → Endkontrolle.
# Voraussetzung: ~/Apps/android-build/env.sh (Toolchain) + Keystore (einmalig mobile/make-keystore.sh). Muster: Alien Pass build-apk.sh.
set -euo pipefail
cd "$(dirname "$0")"
source ~/Apps/android-build/env.sh
KEYPROPS="$HOME/.android-keys/steuertool-keystore.properties"
[ -f "$KEYPROPS" ] || { echo "FEHLER: $KEYPROPS fehlt (einmalig mobile/make-keystore.sh)."; exit 1; }

# Capacitor-Pin wie Alien Pass (26.09.2026): jede Abweichung stoppt, bis die Android-Schicht geprüft ist
# (Bridge.launchIntent → LinkGuard, BridgeWebViewClient.shouldInterceptRequest → CSP-Header, Start-Intent-Extras).
CAP_PIN="6.2.2"
[ -d node_modules ] || npm ci --no-audit --no-fund
for m in android core cli; do
  v="$(node -p "require('./node_modules/@capacitor/$m/package.json').version" 2>/dev/null || echo fehlt)"
  [ "$v" = "$CAP_PIN" ] || { echo "FEHLER: @capacitor/$m ist $v, gepinnt $CAP_PIN — erst Review der Android-Schicht, dann CAP_PIN anheben."; exit 1; }
done

./build-www.sh
[ -d android ] || npx cap add android
echo "sdk.dir=$ANDROID_HOME" > android/local.properties
npx cap sync android
# App-Icon: dasselbe Motiv wie die Desktop-App (desktop/icon.png), in alle mipmap-Dichten
python3 icons.py
node patch-signing.mjs
node patch-hardening.mjs

( cd android && ./gradlew assembleRelease --no-daemon -q ) > gradle-build.log 2>&1 || { tail -30 gradle-build.log; echo "FEHLER: Gradle-Build"; exit 1; }
APK="android/app/build/outputs/apk/release/app-release.apk"

# ── Endkontrolle an der FERTIGEN APK (Manifest-Merging darf nichts einschleusen) ──
BT="$ANDROID_HOME/build-tools/34.0.0"
PERMS="$("$BT/aapt" dump permissions "$APK")"; MAN="$("$BT/aapt" dump xmltree "$APK" AndroidManifest.xml)"
# Erlaubt ist nur die AndroidX-Signatur-Permission der App selbst (DYNAMIC_RECEIVER_NOT_EXPORTED, kein Recht nach außen)
BAD="$(echo "$PERMS" | grep -E "^uses-permission" | grep -vE "name='org\.alieninvestor\.steuertool\.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION'" || true)"
[ -z "$BAD" ] || { echo "FEHLER: APK deklariert eine Berechtigung:"; echo "$BAD"; exit 1; }
echo "$MAN" | grep -qE 'android:debuggable\(0x[0-9a-f]+\)=\(type 0x12\)0xffffffff' && { echo "FEHLER: APK ist debuggable!"; exit 1; }
echo "$MAN" | grep -qE 'android:allowBackup\(0x[0-9a-f]+\)=\(type 0x12\)0x0$' || { echo "FEHLER: allowBackup nicht false!"; exit 1; }
echo "$MAN" | grep -qE 'android:dataExtractionRules\(0x[0-9a-f]+\)=@0x[0-9a-f]+' || { echo "FEHLER: dataExtractionRules fehlen!"; exit 1; }
RULES_OK=0; for x in $(unzip -Z1 "$APK" 'res/*.xml'); do D="$("$BT/aapt" dump xmltree "$APK" "$x" 2>/dev/null || true)"
  if echo "$D" | grep -q "E: data-extraction-rules" && echo "$D" | grep -q "E: cloud-backup" && echo "$D" | grep -q "E: device-transfer" && [ "$(echo "$D" | grep -c 'domain.*="root"')" -ge 2 ]; then RULES_OK=1; break; fi; done
[ "$RULES_OK" = 1 ] || { echo "FEHLER: data-extraction-rules unvollständig!"; exit 1; }
# Bytecode: beide Plugins, CSP-Header, Speichern-Dialog (FLAG_SECURE prüft patch-hardening.mjs am erzeugten Java)
DEXTMP="$(mktemp -d)"; unzip -q -o "$APK" 'classes*.dex' -d "$DEXTMP"
DEX=""; for d in "$DEXTMP"/classes*.dex; do DEX+="$("$BT/dexdump" -d "$d" 2>/dev/null | grep -aE 'org/alieninvestor/steuertool|const-string' || true)"; done
rm -r "$DEXTMP"
for pat in 'Lorg/alieninvestor/steuertool/SaveFilePlugin;' 'Lorg/alieninvestor/steuertool/LinkGuardPlugin;' '"Content-Security-Policy"' \
           "connect-src 'self'" '"android.intent.action.CREATE_DOCUMENT"|ACTION_CREATE_DOCUMENT'; do
  grep -aEq -- "$pat" <<<"$DEX" || { echo "FEHLER: fehlt im Bytecode: $pat"; exit 1; }
done
grep -q "Content-Security-Policy" android/app/src/main/assets/public/index.html || { echo "FEHLER: CSP-Meta fehlt in der eingebetteten index.html"; exit 1; }
"$BT/apksigner" verify "$APK" >/dev/null || { echo "FEHLER: Signatur ungültig"; exit 1; }
echo "APK-Endkontrolle OK (keine Berechtigung, nicht debuggable, kein Backup, SaveFile + LinkGuard, CSP)."

VNAME=$(grep '^VERSION_NAME=' ../VERSION | cut -d= -f2 | tr -d '[:space:]')
mkdir -p build/release
OUT="build/release/btc-steuertool-$VNAME.apk"
cp "$APK" "$OUT"
( cd build/release && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
"$BT/apksigner" verify --print-certs "$OUT" | grep -E "SHA-256 digest" | head -1
ls -lh "$OUT"
