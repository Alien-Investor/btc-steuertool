#!/usr/bin/env bash
# Veröffentlicht das BTC Steuertool im Nostr Zap Store.
# DU führst das selbst aus (per `! bash publish-zapstore.sh`), damit der Signer (SIGN_WITH) und der Upload zu
# cdn.zapstore.dev + Relays NICHT durch Claudes Bash-Wächter laufen. Während des Laufs: Amber-Push am Handy bestätigen.
# Signer: eigene .env im Repo (gitignored), sonst der bewährte Bunker aus Alien Pass — ein frisch erzeugter Bunker
# hängt beim ersten Kontakt gern (Lehre Alien Notes 24.09.2026, Skill app-release).
set -euo pipefail
cd "$(dirname "$0")"

ENVF=".env"; [ -f "$ENVF" ] || ENVF="$HOME/projekte/alien-pass/.env"
[ -f "$ENVF" ] || { echo "FEHLER: keine .env mit SIGN_WITH=bunker://… gefunden"; exit 1; }
set -a; source "$ENVF"; set +a
case "${SIGN_WITH:-}" in
  bunker://*) ;;
  *) echo "FEHLER: SIGN_WITH in $ENVF ist kein bunker://-String"; exit 1;;
esac

echo "→ Starte zsp publish (Signer aus $ENVF, Amber-Push gleich bestätigen)…"
exec ~/.local/bin/zsp publish zapstore.yaml --quiet --skip-preview --skip-certificate-linking "$@"
