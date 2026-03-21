#!/usr/bin/env bash
# Collect Cursor Agent, Claude Code, and Gemini CLI auth/config from the host into a folder
# (or tarball) you can bind-mount or copy into a container. Does not print secret values.
#
# Usage:
#   ./scripts/collect-host-cli-auth.sh [--output DIR] [--dry-run] [--archive]
#   OUTPUT=./bundle ./scripts/collect-host-cli-auth.sh
#
# Notes:
# - macOS Keychain / Windows Credential Manager tokens cannot be exported; use API keys or
#   re-run `agent login` / `claude auth login` / `gemini` login inside the container if needed.
set -euo pipefail

OUTPUT="${OUTPUT:-./host-cli-auth-bundle}"
DRY_RUN=0
ARCHIVE=0

usage() {
  sed -n '1,20p' "$0" | tail -n +2
  echo "Options: --output|-o DIR   Staging directory (default: ./host-cli-auth-bundle)"
  echo "         --dry-run         List sources only; do not copy"
  echo "         --archive         After copy, create DIR.tar.gz next to DIR"
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help) usage ;;
    --output | -o)
      OUTPUT="${2:?}"
      shift 2
      ;;
    --dry-run) DRY_RUN=1; shift ;;
    --archive) ARCHIVE=1; shift ;;
    *) echo "Unknown option: $1" >&2; usage 1 ;;
  esac
done

HOME="${HOME:?}"
UNAME=$(uname -s)

dest_name() {
  # ~/.local/share/foo -> local__share__foo
  local p="$1"
  local rel="${p#"$HOME"/}"
  rel="${rel#/}"
  if [[ -z "$rel" ]]; then
    echo "home"
    return
  fi
  echo "$rel" | tr '/ ' '__'
}

# Cursor Agent / Cursor IDE — browser login + API key flows store data under these (varies by OS)
CURSOR_PATHS=(
  "$HOME/.local/share/cursor-agent"
  "$HOME/.cursor"
  "$HOME/.config/cursor"
)
if [[ "$UNAME" == "Darwin" ]]; then
  CURSOR_PATHS+=(
    "$HOME/Library/Application Support/Cursor"
    "$HOME/Library/Application Support/Cursor Nightly"
  )
fi

# Claude Code — see https://docs.claude.com — ~/.claude (may include .credentials.json on Linux)
CLAUDE_PATHS=( "$HOME/.claude" )

# Gemini CLI — ~/.gemini (settings, .env); override with GEMINI_CONFIG_DIR on host if set
if [[ -n "${GEMINI_CONFIG_DIR:-}" ]]; then
  GEMINI_PATHS=( "$GEMINI_CONFIG_DIR" )
else
  GEMINI_PATHS=( "$HOME/.gemini" )
fi

mkdir_p() {
  if [[ "$DRY_RUN" -eq 1 ]]; then return 0; fi
  mkdir -p "$1"
}

copy_one() {
  local bucket="$1" src="$2"
  local base dest
  base="$(dest_name "$src")"
  dest="$OUTPUT/$bucket/$base"
  if [[ ! -e "$src" ]]; then
    return 1
  fi
  echo "  $src  ->  $dest"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  mkdir_p "$(dirname "$dest")"
  rm -rf "$dest"
  cp -a "$src" "$dest"
}

write_manifest() {
  local mf="$OUTPUT/MANIFEST.txt"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    mf=$(mktemp)
  fi
  {
    echo "Collected: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "Host: $(hostname -f 2>/dev/null || hostname)  OS: $UNAME"
    echo "User home: $HOME"
    echo ""
    echo "Environment (names only — values never logged by this script):"
    for v in CURSOR_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY GOOGLE_APPLICATION_CREDENTIALS GEMINI_CONFIG_DIR; do
      if [[ -n "${!v:-}" ]]; then
        echo "  $v=***set***"
      else
        echo "  $v=<unset>"
      fi
    done
    echo ""
    echo "Mount examples (adjust paths):"
    echo "  docker run ... -v \"$OUTPUT/cursor:/host/cursor:ro\" ..."
    echo "  docker run ... -v \"$HOME/.claude:/home/dev/.claude:ro\" ..."
  } >"$mf"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    cat "$mf"
    rm -f "$mf"
  else
    echo "Wrote $mf"
  fi
}

echo "Staging directory: $OUTPUT"
mkdir_p "$OUTPUT"

echo ""
echo "=== Cursor (agent / IDE config) ==="
found=0
for p in "${CURSOR_PATHS[@]}"; do
  if [[ -e "$p" ]]; then
    found=1
    copy_one cursor "$p" || true
  fi
done
if [[ "$found" -eq 0 ]]; then
  echo "  (no known Cursor paths found)"
fi

echo ""
echo "=== Claude Code (~/.claude) ==="
found=0
for p in "${CLAUDE_PATHS[@]}"; do
  if [[ -e "$p" ]]; then
    found=1
    copy_one claude "$p" || true
  fi
done
if [[ "$found" -eq 0 ]]; then
  echo "  (no ~/.claude directory found)"
fi

echo ""
echo "=== Gemini CLI (~/.gemini or GEMINI_CONFIG_DIR) ==="
found=0
for p in "${GEMINI_PATHS[@]}"; do
  if [[ -e "$p" ]]; then
    found=1
    copy_one gemini "$p" || true
  fi
done
if [[ "$found" -eq 0 ]]; then
  echo "  (no Gemini config directory found)"
fi

echo ""
write_manifest

if [[ "$ARCHIVE" -eq 1 && "$DRY_RUN" -eq 0 ]]; then
  tar -czf "${OUTPUT}.tar.gz" -C "$(dirname "$OUTPUT")" "$(basename "$OUTPUT")"
  echo "Created ${OUTPUT}.tar.gz"
fi

echo ""
echo "Done. Treat $OUTPUT as sensitive; do not commit it."
