#!/usr/bin/env bash
# Enforces bind mounts, validates API keys, and pre-configures agent auth on first run.
set -euo pipefail

WORKSPACE_ROOT="${WORKSPACE_ROOT:-/workspace}"
AGENT_DATA_DIR="${AGENT_DATA_DIR:-${WORKSPACE_ROOT}/.agent-data}"

# 1 = require ${WORKSPACE_ROOT} to be a bind mount (recommended default)
REQUIRE_WORKSPACE_MOUNT="${REQUIRE_WORKSPACE_MOUNT:-1}"
# 1 = require ${AGENT_DATA_DIR} to be its own bind mount (e.g. dedicated host volume)
REQUIRE_AGENT_DATA_MOUNT="${REQUIRE_AGENT_DATA_MOUNT:-0}"

# Optional: path to a shell file with KEY=value lines (also use docker --env-file)
KEYS_ENV_FILE="${KEYS_ENV_FILE:-}"

# Optional: comma-separated keys to require at startup: anthropic, gemini, cursor
# Example: REQUIRE_API_KEYS=anthropic,gemini
REQUIRE_API_KEYS="${REQUIRE_API_KEYS:-}"

# 1 = write API keys into each agent's config dir so they're "logged in"
# without passing env vars to every subprocess.  Default: on.
AUTO_LOGIN_AGENTS="${AUTO_LOGIN_AGENTS:-1}"

# ── Load env file ────────────────────────────────────────────────────
if [[ -n "${KEYS_ENV_FILE}" ]]; then
  if [[ ! -f "${KEYS_ENV_FILE}" ]]; then
    echo "error: KEYS_ENV_FILE is set but not found: ${KEYS_ENV_FILE}" >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "${KEYS_ENV_FILE}"
  set +a
fi

# ── Helpers ──────────────────────────────────────────────────────────
is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

log() { echo "[entrypoint] $*"; }

# ── Workspace mount check ───────────────────────────────────────────
if is_true "${REQUIRE_WORKSPACE_MOUNT}"; then
  if ! mountpoint -q "${WORKSPACE_ROOT}" 2>/dev/null; then
    echo "error: ${WORKSPACE_ROOT} must be a bind-mounted host directory (mandatory)." >&2
    echo "  Example: docker run -v \"\$PWD:${WORKSPACE_ROOT}\" -w ${WORKSPACE_ROOT} ..." >&2
    exit 1
  fi
fi

# ── Agent data mount check ──────────────────────────────────────────
if is_true "${REQUIRE_AGENT_DATA_MOUNT}"; then
  if ! mountpoint -q "${AGENT_DATA_DIR}" 2>/dev/null; then
    echo "error: ${AGENT_DATA_DIR} must be a bind mount when REQUIRE_AGENT_DATA_MOUNT=1." >&2
    echo "  Example: -v \"\$HOME/.cache/my-agent-data:${AGENT_DATA_DIR}\"" >&2
    exit 1
  fi
fi

mkdir -p "${AGENT_DATA_DIR}"

# ── API key requirement checks ──────────────────────────────────────
if [[ -n "${REQUIRE_API_KEYS}" ]]; then
  IFS=',' read -ra _req <<< "${REQUIRE_API_KEYS}"
  for _k in "${_req[@]}"; do
    _k="${_k//[[:space:]]/}"
    [[ -z "${_k}" ]] && continue
    case "${_k}" in
      anthropic|claude)
        if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
          echo "error: ANTHROPIC_API_KEY is required (REQUIRE_API_KEYS includes ${_k})." >&2
          exit 1
        fi
        ;;
      gemini|google)
        if [[ -z "${GEMINI_API_KEY:-}" && -z "${GOOGLE_API_KEY:-}" ]]; then
          echo "error: GEMINI_API_KEY or GOOGLE_API_KEY is required (REQUIRE_API_KEYS includes ${_k})." >&2
          exit 1
        fi
        ;;
      cursor)
        if [[ -z "${CURSOR_API_KEY:-}" ]]; then
          echo "error: CURSOR_API_KEY is required (REQUIRE_API_KEYS includes ${_k})." >&2
          exit 1
        fi
        ;;
      *)
        echo "error: unknown REQUIRE_API_KEYS token: ${_k} (use anthropic, gemini, cursor)" >&2
        exit 1
        ;;
    esac
  done
fi

# ── Auto-login: write API keys into agent config directories ────────
# This makes agents "pre-logged-in" so callers (gateway, workflow services)
# don't need to pass env vars to every spawned subprocess.
#
# Skip if HOST_CLI_AUTH_DIR is mounted (user already injected host configs).
if is_true "${AUTO_LOGIN_AGENTS}"; then
  HOST_CLI_AUTH_DIR="${HOST_CLI_AUTH_DIR:-}"

  # ─── Claude Code ───────────────────────────────────────────────
  if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    CLAUDE_DIR="${HOME}/.claude"
    # Don't overwrite if host config was mounted in
    if [[ -z "${HOST_CLI_AUTH_DIR}" ]] || [[ ! -d "${CLAUDE_DIR}/.credentials.json" ]]; then
      mkdir -p "${CLAUDE_DIR}"
      # Claude Code reads ANTHROPIC_API_KEY from env at runtime, but also
      # checks ~/.claude/.credentials.json.  Write a minimal credentials file
      # so it works even when env isn't forwarded to subprocesses.
      cat > "${CLAUDE_DIR}/.credentials.json" <<CEOF
{
  "apiKey": "${ANTHROPIC_API_KEY}",
  "source": "docker-entrypoint-auto-login"
}
CEOF
      chmod 600 "${CLAUDE_DIR}/.credentials.json"
      log "Claude Code: credentials written to ${CLAUDE_DIR}/.credentials.json"
    fi
  fi

  # ─── Gemini CLI ────────────────────────────────────────────────
  _gemini_key="${GEMINI_API_KEY:-${GOOGLE_API_KEY:-}}"
  if [[ -n "${_gemini_key}" ]]; then
    GEMINI_DIR="${HOME}/.gemini"
    if [[ -z "${HOST_CLI_AUTH_DIR}" ]] || [[ ! -f "${GEMINI_DIR}/settings.json" ]]; then
      mkdir -p "${GEMINI_DIR}"
      # Gemini CLI reads GEMINI_API_KEY from env, but also reads ~/.gemini/settings.json
      cat > "${GEMINI_DIR}/settings.json" <<GEOF
{
  "selectedAuthType": "api-key",
  "apiKey": "${_gemini_key}",
  "source": "docker-entrypoint-auto-login"
}
GEOF
      chmod 600 "${GEMINI_DIR}/settings.json"
      log "Gemini CLI: API key written to ${GEMINI_DIR}/settings.json"
    fi
  fi

  # ─── Cursor Agent ──────────────────────────────────────────────
  if [[ -n "${CURSOR_API_KEY:-}" ]]; then
    CURSOR_CONFIG_DIR="${HOME}/.local/share/cursor-agent"
    if [[ -z "${HOST_CLI_AUTH_DIR}" ]] || [[ ! -f "${CURSOR_CONFIG_DIR}/config.json" ]]; then
      mkdir -p "${CURSOR_CONFIG_DIR}"
      cat > "${CURSOR_CONFIG_DIR}/config.json" <<CUEOF
{
  "apiKey": "${CURSOR_API_KEY}",
  "source": "docker-entrypoint-auto-login"
}
CUEOF
      chmod 600 "${CURSOR_CONFIG_DIR}/config.json"
      log "Cursor Agent: API key written to ${CURSOR_CONFIG_DIR}/config.json"
    fi
  fi

  log "Auto-login complete."
fi

exec "$@"
