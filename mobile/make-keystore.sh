#!/usr/bin/env bash
# Erzeugt EINMALIG den Release-Keystore der Android-App (Muster Alien Pass finish-build.sh). Das Passwort entsteht lokal per openssl,
# wird nie ausgegeben und liegt nur in ~/.android-keys/steuertool-keystore.properties (chmod 600). Verlust = keine Updates mehr möglich.
set -euo pipefail
source ~/Apps/android-build/env.sh
KEYDIR="$HOME/.android-keys"; JKS="$KEYDIR/steuertool-release.jks"; PROPS="$KEYDIR/steuertool-keystore.properties"
[ -f "$JKS" ] && { echo "✓ Keystore existiert bereits: $JKS"; exit 0; }
mkdir -p "$KEYDIR"; chmod 700 "$KEYDIR"
KSPASS="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-28)"; export KSPASS
"$JAVA_HOME/bin/keytool" -genkeypair -keystore "$JKS" -alias steuertool -keyalg RSA -keysize 4096 -validity 10000 \
  -storepass:env KSPASS -keypass:env KSPASS -dname "CN=Alien Investor, OU=BTC Steuertool, O=Alien Investor, C=DE" >/dev/null 2>&1
( umask 077; printf 'storeFile=%s\nstorePassword=%s\nkeyAlias=steuertool\nkeyPassword=%s\n' "$JKS" "$KSPASS" "$KSPASS" > "$PROPS" )
unset KSPASS
chmod 600 "$JKS" "$PROPS"
echo "✓ Keystore + steuertool-keystore.properties angelegt (chmod 600). NIE committen, Backup wie die anderen App-Schlüssel."
