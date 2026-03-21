#!/usr/bin/env bash
# Verify that all CLI agents are installed and (optionally) authenticated.
# Exit 0 = all OK, exit 1 = something missing or unauthenticated.
#
# Usage:
#   verify-agents.sh              # check binaries only
#   verify-agents.sh --auth       # also check auth config files
#   verify-agents.sh --verbose    # print details
set -euo pipefail

CHECK_AUTH=0
VERBOSE=0
for arg in "$@"; do
  case "$arg" in
    --auth) CHECK_AUTH=1 ;;
    --verbose|-v) VERBOSE=1 ;;
  esac
done

ERRORS=0

check_bin() {
  local name="$1"
  if command -v "$name" &>/dev/null; then
    [[ "$VERBOSE" -eq 1 ]] && echo "  OK  $name → $(command -v "$name")"
  else
    echo "  FAIL  $name not found in PATH" >&2
    ERRORS=$((ERRORS + 1))
  fi
}

check_auth_file() {
  local agent="$1" path="$2"
  if [[ -f "$path" ]]; then
    [[ "$VERBOSE" -eq 1 ]] && echo "  OK  $agent auth: $path exists"
  else
    echo "  WARN  $agent: $path not found (agent may not be authenticated)" >&2
    ERRORS=$((ERRORS + 1))
  fi
}

echo "=== CLI Agent Verification ==="
echo ""
echo "Binaries:"
check_bin claude
check_bin gemini
check_bin agent         # cursor-agent binary
check_bin cursor-agent
check_bin cursor
check_bin node
check_bin npm
check_bin go
check_bin java
check_bin python3

if [[ "$CHECK_AUTH" -eq 1 ]]; then
  echo ""
  echo "Authentication:"
  HOME="${HOME:-/home/dev}"

  # Claude Code
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    [[ "$VERBOSE" -eq 1 ]] && echo "  OK  Claude Code: ANTHROPIC_API_KEY is set in env"
  else
    check_auth_file "Claude Code" "${HOME}/.claude/.credentials.json"
  fi

  # Gemini CLI
  if [[ -n "${GEMINI_API_KEY:-}" || -n "${GOOGLE_API_KEY:-}" ]]; then
    [[ "$VERBOSE" -eq 1 ]] && echo "  OK  Gemini CLI: API key is set in env"
  else
    check_auth_file "Gemini CLI" "${HOME}/.gemini/settings.json"
  fi

  # Cursor Agent
  if [[ -n "${CURSOR_API_KEY:-}" ]]; then
    [[ "$VERBOSE" -eq 1 ]] && echo "  OK  Cursor Agent: CURSOR_API_KEY is set in env"
  else
    check_auth_file "Cursor Agent" "${HOME}/.local/share/cursor-agent/config.json"
  fi
fi

echo ""
if [[ "$ERRORS" -gt 0 ]]; then
  echo "Result: ${ERRORS} issue(s) found."
  exit 1
else
  echo "Result: All checks passed."
  exit 0
fi
