#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$ROOT_DIR/skills/media/attract-signal"
TARGET="${1:-hermes}"

if [[ ! -f "$SRC/SKILL.md" ]]; then
  echo "Missing skill source: $SRC/SKILL.md" >&2
  exit 1
fi

install_one() {
  local name="$1"
  local dest="$2"

  mkdir -p "$(dirname "$dest")"
  if [[ -e "$dest" ]]; then
    local backup="${dest}.backup.$(date +%Y%m%d-%H%M%S)"
    mv "$dest" "$backup"
    echo "Backed up existing $name install to:"
    echo "$backup"
    echo
  fi
  cp -R "$SRC" "$dest"
  echo "Installed attract-signal for $name:"
  echo "$dest"
  echo
}

case "$TARGET" in
  hermes)
    install_one "Hermes" "${HERMES_HOME:-$HOME/.hermes}/skills/attract-signal"
    ;;
  codex)
    install_one "Codex" "${CODEX_HOME:-$HOME/.codex}/skills/attract-signal"
    ;;
  claude)
    install_one "Claude" "$HOME/.claude/skills/attract-signal"
    ;;
  all)
    install_one "Hermes" "${HERMES_HOME:-$HOME/.hermes}/skills/attract-signal"
    install_one "Codex" "${CODEX_HOME:-$HOME/.codex}/skills/attract-signal"
    install_one "Claude" "$HOME/.claude/skills/attract-signal"
    ;;
  *)
    echo "Usage: ./install.sh [hermes|codex|claude|all]" >&2
    exit 2
    ;;
esac

echo "Recommended dependencies:"
echo "python3 -m pip install -U yt-dlp youtube-transcript-api"
echo
echo "Optional Reddit Intelligence semantic routing:"
echo "python3 -m pip install 'openai>=2,<3'"
echo
echo "Optional Google publishing:"
echo "brew install openclaw/tap/gogcli && gog auth status"
