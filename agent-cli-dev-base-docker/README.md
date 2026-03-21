# Agent CLI dev base (Docker)

A single image with **Node + npm**, **Cursor Agent CLI** (`agent`, **`cursor-agent`**, and a **`cursor`** symlink → `agent`), **Claude Code**, **Gemini CLI**, plus **Go** (upstream tarball), **Eclipse Temurin 21**, and **Python 3**. Processes run as **`dev`** (`uid`/`gid` **1000**).

Startup is handled by **`docker-entrypoint.sh`**, which **requires a bind-mounted workspace** by default so agents always write into a host directory you control.

## Build

```bash
docker build -t agent-cli-dev-base .
```

### Pinned versions (build args)

| Arg | Default | Purpose |
|-----|---------|---------|
| `NODE_VERSION` | `22.14.0` | [Official Node image](https://hub.docker.com/_/node) tag `NODE_VERSION-bookworm-slim` |
| `GO_VERSION` | `1.24.1` | [go.dev/dl](https://go.dev/dl/) tarball |
| `CLAUDE_CODE_VERSION` | `latest` | `@anthropic-ai/claude-code` |
| `GEMINI_CLI_VERSION` | `latest` | `@google/gemini-cli` |

## Mandatory directory mount

By default **`REQUIRE_WORKSPACE_MOUNT=1`**. The entrypoint checks that **`WORKSPACE_ROOT`** (default **`/workspace`**) is a **mount point** (e.g. `docker run -v "$PWD:/workspace"`). If it is only the image filesystem, the container **exits with an error**.

| Variable | Default | Meaning |
|----------|---------|---------|
| **`WORKSPACE_ROOT`** | `/workspace` | Project tree; must be bind-mounted when enforcement is on |
| **`AGENT_DATA_DIR`** | `/workspace/.agent-data` | Created at startup; use for agent/app state under the project mount |
| **`REQUIRE_WORKSPACE_MOUNT`** | `1` | Set to `0` only if you intentionally accept a non-mounted path (not recommended) |
| **`REQUIRE_AGENT_DATA_MOUNT`** | `0` | Set to `1` to require **`AGENT_DATA_DIR`** to be its **own** bind mount (e.g. separate host volume for cache/state) |

### `docker run` (workspace mount required)

```bash
docker run --rm -it \
  -v "$PWD:/workspace" -w /workspace \
  -e AGENT_DATA_DIR=/workspace/.agent-data \
  agent-cli-dev-base
```

### `docker compose`

From this directory, the compose file bind-mounts **`HOST_WORKSPACE`** (default **`.`**) to **`/workspace`**.

```bash
HOST_WORKSPACE="$PWD" docker compose run --rm agent-cli
```

Copy **`.env.example`** to **`.env`**, adjust values, then:

```bash
docker compose --env-file .env run --rm agent-cli
```

## API keys (configurable at start)

Pass secrets with **`-e`**, **`--env-file`**, or Compose **`environment`**. Do not commit real keys.

| Variable | When |
|----------|------|
| **`ANTHROPIC_API_KEY`** | Claude Code / Anthropic APIs |
| **`GEMINI_API_KEY`** or **`GOOGLE_API_KEY`** | Gemini CLI (either name, depending on tool) |
| **`CURSOR_API_KEY`** | Cursor headless / API usage where supported |

Optional **strict checks**: set **`REQUIRE_API_KEYS`** to a comma-separated list — **`anthropic`**, **`gemini`**, **`cursor`** — and the entrypoint exits if the matching variables are empty.

Example:

```bash
docker run --rm -it \
  -v "$PWD:/workspace" -w /workspace \
  -e REQUIRE_API_KEYS=anthropic,gemini \
  -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \
  agent-cli-dev-base
```

Optional file-based load inside the container:

| Variable | Meaning |
|----------|---------|
| **`KEYS_ENV_FILE`** | Path to a file (e.g. `export VAR=value` or `VAR=value` lines). Mount the file into the container and set this path. |

## Copy host CLI auth into the container

Use **`scripts/collect-host-cli-auth.sh`** on your **host** to gather known config directories for **Cursor** (agent + app paths), **Claude Code** (`~/.claude`), and **Gemini** (`~/.gemini` or **`GEMINI_CONFIG_DIR`**). It **does not print secrets**; it copies trees into a staging folder (or **`--archive`** tarball). **`host-cli-auth-bundle/`** is listed in **`.gitignore`**.

```bash
chmod +x scripts/collect-host-cli-auth.sh
./scripts/collect-host-cli-auth.sh --dry-run          # preview paths
./scripts/collect-host-cli-auth.sh --archive          # ./host-cli-auth-bundle + .tar.gz
```

Typical bind-mounts (read-only) so the container sees the same auth as the host:

```bash
docker run --rm -it \
  -v "$PWD:/workspace" -w /workspace \
  -v "$HOME/.claude:/home/dev/.claude:ro" \
  -v "$HOME/.gemini:/home/dev/.gemini:ro" \
  -v "$HOME/.local/share/cursor-agent:/home/dev/.local/share/cursor-agent:ro" \
  agent-cli-dev-base
```

**Limits:** OAuth / browser tokens stored only in **macOS Keychain** (or similar) are **not** files on disk and cannot be copied this way—use **`CURSOR_API_KEY`**, **`agent login`** in the container, or provider docs. **`GOOGLE_APPLICATION_CREDENTIALS`** (service account JSON) can be mounted as a file and the env var set inside the container.

## What’s installed

| Component | Notes |
|-----------|--------|
| **Node / npm** | `node:${NODE_VERSION}-bookworm-slim` |
| **Cursor Agent** | [cursor.com/install](https://cursor.com/install) — **`agent`**, **`cursor-agent`**, **`cursor`** → `agent` |
| **Claude Code** | `claude` |
| **Gemini CLI** | `gemini` |
| **Go** | `/usr/local/go` |
| **Java** | Temurin 21 |
| **Python** | `python3`, `pip3`, `venv` |

## Separate mount for agent data only

If you want agent state **outside** the repo tree, bind a host directory and point **`AGENT_DATA_DIR`** at it, then enforce:

```bash
docker run --rm -it \
  -v "$PWD:/workspace" \
  -v "$HOME/.cache/my-agent-data:/agent-data" \
  -w /workspace \
  -e AGENT_DATA_DIR=/agent-data \
  -e REQUIRE_AGENT_DATA_MOUNT=1 \
  agent-cli-dev-base
```
