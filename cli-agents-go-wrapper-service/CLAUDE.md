# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**CLI Agent Gateway** — a WebSocket-based gateway that provides a unified protocol for UI clients to communicate with multiple CLI coding agents (Claude Code, Cursor, Gemini). It acts as a translation layer between a standard envelope protocol and each agent's native stdin/stdout format.

## Commands

```bash
make build        # Build binary to ./bin/cli-agent-gateway (stripped)
make build-aw     # Build WebSocket test client to ./bin/aw
make run          # Build and run on port 8080
make run-dev      # Run with go run (no build step, faster iteration)
make test         # go test ./... -v
make tidy         # go mod tidy
make clean        # Remove ./bin
make build-all    # Cross-compile for macOS arm64/amd64, Linux, Windows
```

### Logging

- **Default:** JSON logs to **stdout** only (Docker: `docker compose logs gateway`).
- **File (optional):** set **`GATEWAY_LOG_FILE`** or **`--log-file path`** — same JSON lines are **tee’d** to the file and stdout. Parent directories are created automatically.
- **Repo root Compose:** `docker-compose.yml` mounts **`./logs/gateway`** and sets `GATEWAY_LOG_FILE=/var/log/gateway/gateway.log` so the host file is **`logs/gateway/gateway.log`** (see repo **`logs/README.md`**).
- **Workspace file service (optional):** set **`GATEWAY_WORKSPACE_FILE_SERVICE_URL`** (e.g. `http://localhost:8090` or `http://workspace-file-service:8090` in Compose). On every **`session.create`**, the gateway **`GET`s** **`/api/v1/sessions/{sessionId}`**, which **ensures** the session directory exists and returns **`workspace_path`**; the gateway sets **`workingDir`** to that path (overrides client `workingDir`). The gateway process must see that path on disk — in Compose, **`./dorsia-workspace`** is bind-mounted at **`/data/workspaces`** on both the gateway and workspace-file-service containers. Session IDs must satisfy workspace-file-service rules (letters, digits, `.`, `_`, `-` only).
- **User prompts:** each adapter logs **`prompt`** (via **`internal/agent.PromptForLog`**, truncated ~8k runes) on **`send_prompt`** / **`send_prompt.persistent`** / **`send_prompt.one_shot`** together with **`prompt_chars`** — do not drop when refactoring stdin.

Running a single test:
```bash
go test ./internal/session/... -run TestYourTestName -v
```

### Terminal client (`aw`)

With the gateway running (`make run-dev`), exercise the same WebSocket protocol from the shell:

```bash
make build-aw
./bin/aw -a claude -s wf-1 "Summarize the README"
./bin/aw -a gemini -f research -s wf-2 "What is 2+2?"   # session id = research-wf-2
./bin/aw -a claude-code -s wf-3 "hello"                 # full adapter name as -a
```

Flags: `-a` agent/adapter (required; maps to gateway `flow`), `-f` optional use case / workflow (prefixes session id as `<f>-<s>`), `-u` WebSocket URL (default `ws://localhost:8080/ws`), `-w` working dir for `session.create`, `--no-create` if the session already exists, `--json` raw envelopes, `-q` stdout-only assistant text (no stderr activity log), `-v` verbose stderr (full tool I/O). Default: assistant `text`/`markdown`/`code` deltas on **stdout**; adapter activity (`stream.start`, `thinking` deltas, tools, `stream.end` with usage) on **stderr** with timestamps.

### Claude Code (persistent stdin/stdout)

Default: one **`claude`** process per session: `--print --output-format stream-json --input-format stream-json` with **stdin** NDJSON user lines (see `internal/agent/claudecode/stream_input.go`) and **stdout** stream-json until each `result`.

If stderr reports **“Session ID … already in use”**, the gateway **stops** that subprocess and **retries** spawn (brief delay); after a second failure it may assign a **new** Claude session UUID and retry once more.

Session id: **`agent.AdapterSessionUUID(sessionId, flow)`** — deterministic **UUID v5–style hash** (SHA-1 by default) of the routing key, so the same gateway `sessionId` + `flow` always maps to the same Claude `--session-id`. Optional **`GATEWAY_ADAPTER_SESSION_SHA256=1`** uses SHA-256 instead (different IDs). Override: `config.claudeSessionId`.

**One-shot (opt-in):** `CLAUDE_CODE_DISABLE_RESUME=1` or `config.claudeDisableResume: true` — subprocess per prompt with `-p` (no persistent proc).

### Gemini / Cursor

Same pattern: **one subprocess per session**, prompts via **stdin** (`gemini --output-format stream-json -y`, `agent --agent`), streaming read per `prompt.send`.

### WebSocket hub

- **One in-flight `prompt.send` per session** (`session.PromptLock`).
- **Streaming events** carry **`replyTo`** = the inbound `prompt.send` envelope **`id`**.
- **Outbound queue** blocks (no silent drops); larger buffer (4096).
- **`prompt.cancel`**: cancels the per-prompt context and calls **`Adapter.CancelPrompt`** (stops the subprocess where implemented).

### Docker

```bash
make docker-build                                    # Build image cli-agent-gateway:latest
make docker-run ANTHROPIC_API_KEY=sk-ant-... \
                GOOGLE_API_KEY=AIza...               # Run on port 8080
make docker-stop
make docker-push IMAGE=ghcr.io/org/cli-agent-gateway TAG=v1.0.0
```

### Deploy

```bash
# Local background process
make deploy-local    # starts binary, writes PID to ./bin/*.pid
make stop-local

# Remote Linux server via SSH (installs as a systemd service)
make build-all
make deploy DEPLOY_HOST=your-server.com \
            ANTHROPIC_API_KEY=sk-ant-... \
            GOOGLE_API_KEY=AIza...
# Logs: journalctl -u cli-agent-gateway -f
```

## Architecture

### Core Abstraction: Adapter Interface (`internal/agent/adapter.go`)

Every CLI agent implements `Adapter`:
- `Start()` / `Stop()` — spawn/connect and teardown
- `SendPrompt()` — write to agent stdin, stream output back via `EventSink`
- `CancelPrompt()` / `ApproveToolUse()` / `RejectToolUse()` — interactive control
- `GetHistory()` / `IsRunning()` / `Capabilities()` — introspection

Adapters self-register via `init()` into a global registry (no main-package coupling). `baseadapter.go` provides reusable context/cancel plumbing.

### Protocol (`internal/protocol/`)

Envelope-based design — all WebSocket messages share a common wrapper:
- `SessionID` + `Flow` form an **immutable routing key** (once bound, cannot change for that session)
- `Type` discriminates payload (e.g., `prompt.send`, `stream.delta`, `tool.approve`)
- `Payload` is raw JSON for forward compatibility
- `ReplyTo` links responses to requests

### Session Manager (`internal/session/manager.go`)

3-case resolution on every request:
1. **New session** → create adapter, spawn process, store `StartOptions`
2. **Existing session, matching flow** → return session; auto-resume if process died
3. **Flow mismatch** → reject (immutable binding)

**Auto-resume**: process death does not delete the session. The next `prompt.send` transparently re-spawns the agent using stored `StartOptions`.

### WebSocket Hub (`internal/ws/hub.go`)

- Each UI client has dedicated read/write goroutines
- Hub validates envelopes, resolves sessions, dispatches to adapter
- `clientSink` bridges adapter events back to the client's write channel

### Process Manager (`internal/process/manager.go`)

Subprocess wrapper: spawns CLI agents, wires stdin/stdout/stderr with 1 MB buffers, provides `ReadLines()` / `ReadStderrLines()` channels, detects process exit.

### Agent Adapters

| Agent | Spawn command | Tool approval | Auth CLI | Model listing |
|-------|--------------|---------------|----------|---------------|
| Claude Code | `claude -p --output-format stream-json --verbose` | auto (--dangerously-skip-permissions) | `claude auth status/login` | Anthropic REST API (`ANTHROPIC_API_KEY`) |
| Cursor | `agent --agent` | n/a | `agent status` / `agent login` | `agent models` CLI |
| Gemini | `gemini [--sandbox]` | `yes`/`no` on stdin | `gemini auth status/login` | Google Generative AI API (`GOOGLE_API_KEY`) |

All emit newline-delimited JSON events on stdout that adapters parse and translate to protocol envelopes.

**Optional adapter interfaces** (in `internal/agent/adapter.go`):
- `Authenticator` — `CheckAuth(ctx)` + `Login(ctx)` — implemented by all three adapters
- `ModelLister` — `ListModels(ctx)` — implemented by all three adapters
- Auth state is cached in `internal/auth/manager.go` for the server lifetime; invalidated via `DELETE /agents/{agent}/auth`

### Configuration (`internal/config/config.go`)

Load order: hard-coded defaults → JSON file (`--config`) → env vars (`GATEWAY_HOST`, `GATEWAY_PORT`).

Per-agent overrides in config JSON:
```json
{
  "agents": {
    "claude-code": { "command": "claude", "models": ["claude-opus-4-6", "claude-sonnet-4-6"], "env": {}, "extraArgs": [] }
  }
}
```

### HTTP Routes (`cmd/server/main.go`)

- `GET /ws` — WebSocket upgrade
- `GET /health` — liveness probe
- `GET /adapters` — list registered adapters and their capabilities

Graceful shutdown: SIGINT/SIGTERM → stop all sessions → 10-second HTTP drain.

## Data Flow (prompt → response)

1. UI sends `prompt.send` envelope over WebSocket
2. Hub validates, resolves/auto-resumes session
3. Hub calls `adapter.SendPrompt(ctx, prompt, sink)`
4. Adapter writes prompt to agent stdin
5. Adapter reads JSON events from stdout, translates → protocol types
6. Adapter emits via `EventSink` (e.g., `TypeStreamDelta`, `TypeToolUseStart`)
7. Sink enqueues protocol envelopes to client's write channel
8. Write pump marshals and sends over WebSocket
