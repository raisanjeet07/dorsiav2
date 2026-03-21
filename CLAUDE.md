# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## System Overview

Dorsia is a **multi-agent AI platform** composed of independently deployable microservices. The architecture separates a stable **agent access layer** (gateway + capability service, both running on the dev-base image) from **domain workflow services** (research, and future PRD/development/QA/knowledge-center workflows). Each new workflow service is an independent microservice that plugs into the same gateway and capability service without coupling to other workflows.

**`workspace-file-service`** (Go, port **8090**) — Assigns a filesystem directory per `session_id` (1:1), exposes JSON APIs for **workspace path** resolution and **`GET /files/...`** for browsing/downloading artifacts. Session data lives under **`dorsia-workspace/`** at the repo root (env `WORKSPACE_FILE_ROOT`); **service logs** use optional `WORKSPACE_FILE_LOG_FILE` (separate from workspaces). See **`workspace-file-service/README.md`**.

## Root Commands

```bash
make up          # Build everything and start all services (docker compose up --build)
make start       # Start without rebuilding
make down        # Stop all services, preserve volumes
make clean       # Stop and wipe all volumes (destructive)
make build-base  # Build dev-base image (prerequisite before building gateway)
make build       # Build all service images
make logs        # Tail logs from all services
make ps          # Show running containers and health status
```

## Service logs (host)

With Docker Compose, the gateway appends structured logs to **`logs/gateway/gateway.log`** (and still prints to container stdout). Local `go run` / `make run-dev` only writes to stdout unless you set **`GATEWAY_LOG_FILE`** or **`--log-file`**. Details: **`logs/README.md`**.

## Service Architecture

### Layer 1 — Agent Access Foundation (runs on dev-base image)

**`agent-cli-dev-base-docker`** — Base Docker image that pre-installs every CLI agent and runtime: Node 22, Go 1.24, Python 3, Java 21 (Temurin), Claude Code CLI, Gemini CLI, Cursor Agent. The gateway container is built on top of this image; separating the toolchain from the binary keeps gateway rebuilds fast.

**`cli-agents-go-wrapper-service`** (Go, port 8080) — WebSocket gateway. Every agent interaction flows through here. Spawns CLI agents (claude, gemini, agent) as subprocesses, translates between a typed envelope protocol and each agent's stdin/stdout JSON format. Key properties:
- `SessionID + Flow` is an **immutable routing key** — cannot be changed after binding
- **Auto-resume**: process death does not delete a session; the next `prompt.send` transparently re-spawns the agent using stored `StartOptions`
- Adapters self-register via `init()` — no main-package coupling
- Hosts Skill and MCP registries that the Capability Service populates
- See `cli-agents-go-wrapper-service/CLAUDE.md` for detailed internals

**`ai-capability-skills-agent-persona`** (Python/FastAPI, port 8100) — Also runs in the dev-base environment. Manages *who* an agent is and *what it can do* via declarative YAML. Three extension kinds: `Persona` (identity, capability list, output schema), `Capability` (reusable prompt fragment + required MCPs + transitive dependencies), `AgentProfile` (how to call a backend: gateway flow, session defaults, prompt template). Resolution is transitive — requesting persona X automatically pulls in all dependent capabilities. Hot-reloads YAML files with a 1-second debounce; no restart needed.

### Layer 2 — Domain Workflow Services (independent microservices)

**`research-work-flow-ai`** (Python/FastAPI, port 8000) — First workflow implementation. Orchestrates multi-agent research via a 13-state state machine:
```
INITIATED → RESEARCHING → RESEARCH_COMPLETE → REVIEWING → REVIEW_COMPLETE
→ RESOLVING → RESOLUTION_COMPLETE → RE_REVIEWING → CONSENSUS_REACHED
→ USER_REVIEW → USER_APPROVED → GENERATING_FINAL → COMPLETED
```
Agent roles: Researcher (Gemini by default), Reviewer (Claude Code by default), Resolver (both). Persists all state and agent outputs to PostgreSQL. Streams real-time events to clients over WebSocket.

### Planned Future Workflows (same pattern as research)
- PRD Workflow
- Development Workflow
- QA & Release Workflow
- Knowledge Center Workflow

Each new workflow service: accepts domain-specific task via REST → connects to gateway via WebSocket → optionally resolves personas from Capability Service → persists state → streams events over WebSocket to clients.

## Service Communication

| From | To | How |
|------|----|-----|
| Research Workflow | Gateway | WebSocket `ws://gateway:8080/ws` — sends prompts, receives agent events |
| Research Workflow | Capability Service | HTTP — resolve researcher/reviewer personas |
| Capability Service | Gateway | HTTP — sync resolved skills and MCPs on startup and after YAML changes |
| Future Workflows | Gateway + Capability Service | Same pattern as research workflow |

## Per-Service Development Commands

### Gateway (Go)
```bash
cd cli-agents-go-wrapper-service
make run-dev     # go run (faster iteration, no build step)
make test        # go test ./... -v
make build       # build binary to ./bin/cli-agent-gateway
# Single test:
go test ./internal/session/... -run TestYourTestName -v
```

### Research Workflow (Python)
```bash
cd research-work-flow-ai
make setup       # pip install with dev dependencies
make run         # start FastAPI app
make dev         # run with RESEARCH_DEBUG=true
make test        # pytest
make lint        # ruff check + format check
make format      # auto-fix linting
make migrate     # alembic upgrade head
make migrate-new # create new migration
make db          # start local postgres container
make db-reset    # wipe and restart postgres
```

### Capability Service (Python)
```bash
cd ai-capability-skills-agent-persona
# See that service's CLAUDE.md for commands
```

## Adding a New Workflow Service

Follow the pattern established by `research-work-flow-ai`:
1. FastAPI app with `WORKFLOW_*`-prefixed env vars
2. Connect to gateway via WebSocket for all agent interactions
3. Call Capability Service HTTP API to resolve personas (optional but recommended)
4. Persist state + stream events over WebSocket to clients
5. Add service to root `docker-compose.yml` with health checks
6. Add `make` targets to root Makefile

## Key Environment Variables

```bash
# Gateway
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
GATEWAY_PORT=8080
# GATEWAY_WORKSPACE_FILE_SERVICE_URL=http://localhost:8090  # optional: provision workingDir per sessionId
# CLAUDE_CODE_DISABLE_RESUME=1   # optional one-shot; omit for Claude session_id + --resume
# GATEWAY_ADAPTER_SESSION_SHA256=1  # optional: SHA-256 instead of SHA-1 for AdapterSessionUUID (different IDs)

# Capability Service (CAPS_ prefix)
CAPS_GATEWAY_HTTP_URL=http://gateway:8080
CAPS_HOT_RELOAD_ENABLED=true

# Research Workflow (RESEARCH_ prefix)
RESEARCH_DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/research_workflows
RESEARCH_GATEWAY_WS_URL=ws://gateway:8080/ws
RESEARCH_CAPABILITY_SERVICE_URL=http://capability-service:8100
RESEARCH_RESEARCHER_AGENT=gemini
RESEARCH_REVIEWER_AGENT=claude-code
# RESEARCH_GATEWAY_CLAUDE_DISABLE_RESUME=true   # optional one-shot (default false)
```

Copy `.env.example` at the root for a full template.
