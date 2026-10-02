#!/bin/sh
# zypak leitet Chromiums Sandbox auf Flatpaks eigenen Käfig um — kein --no-sandbox nötig
exec zypak-wrapper /app/main/electron "$@"
