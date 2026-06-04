#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT_DIR/skills/media/youtube-shorts-trend-recraft"
DEST="${HERMES_HOME:-$HOME/.hermes}/skills/media/youtube-shorts-trend-recraft"

if [[ ! -f "$SRC/SKILL.md" ]]; then
  echo "Missing skill source: $SRC/SKILL.md" >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
if [[ -e "$DEST" ]]; then
  BACKUP="${DEST}.backup.$(date +%Y%m%d-%H%M%S)"
  mv "$DEST" "$BACKUP"
  echo "Backed up existing install to:"
  echo "$BACKUP"
  echo
fi
cp -R "$SRC" "$DEST"

echo "Installed youtube-shorts-trend-recraft to:"
echo "$DEST"
echo
echo "Recommended dependencies:"
echo "python3 -m pip install -U yt-dlp youtube-transcript-api"
