#!/bin/bash
# Fetches DiscordGSM source files into ./discordgsm_source/ for reference and diff comparison.
# Run from the repo root on the Unraid host.
# Usage: bash scripts/fetch_discordgsm_source.sh

set -e
DEST="discordgsm_source"
CONTAINER="DiscordGSM"
APP="/usr/src/app"

mkdir -p "$DEST"

fetch() {
    local src="$1"
    local dest="$DEST/$(basename $src)"
    if docker exec "$CONTAINER" cat "$APP/$src" > "$dest" 2>/dev/null; then
        echo "✓  $src"
    else
        echo "✗  $src (not found, skipping)"
        rm -f "$dest"
    fi
}

fetch "discordgsm/main.py"
fetch "discordgsm/database.py"
fetch "discordgsm/service.py"
fetch "discordgsm/server.py"
fetch "discordgsm/gamedig.py"
fetch "discordgsm/games.csv"
fetch "discordgsm/async_utils.py"
fetch "requirements.txt"
fetch "app.py"

echo ""
echo "Done. Files saved to $DEST/"
echo "To diff against a previous snapshot: git diff -- discordgsm_source/"
