# Dorsia — System Architecture

## Overview

Dorsia is a **multi-agent AI platform** built as a collection of composable microservices. The system provides a unified way to run AI coding agents (Claude Code, Cursor, Gemini) behind a single WebSocket gateway, layer declarative personas and skills on top of them, and orchestrate complex multi-step workflows like research, PRDs, and QA pipelines.

The architecture follows a **hub-and-spoke** pattern: a central CLI Agent Gateway handles all agent communication, while workflow and capability services plug in on top without any agent-specific coupling.

---

## System Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                         External Clients / UI                    │
└──────────┬─────────────────────────────────────┬─────────────────┘
           │ WebSocket / HTTP                    │ REST / WebSocket
           ▼                                     ▼
┌──────────────────────────────┐    ┌────────────────────────────────┐
│   CLI Agent Gateway          │    │   Research Workflow Service     │
│   (Go · Port 8080)           │◄───│   (Python · Port 8000)         │
│                              │    │                                │
│  · WebSocket hub             │    │  · Multi-stage orchestration   │
│  · Adapter per CLI agent     │    │  · Researcher / Reviewer /     │
│  · Session persistence       │    │    Resolver agent roles        │
│  · Auto-resume on restart    │    │  · Real-time WS event stream   │
│  · Skill & MCP registries    │    │  · PostgreSQL persistence      │
└──────────┬───────────────────┘    └────────────────────────────────┘
           │ spawns subprocess               │ HTTP queries
           ▼                                 ▼
┌──────────────────────────────┐    ┌────────────────────────────────┐
│   CLI Agents (subprocesses)  │    │   Capability Service           │
│                              │    │   (Python · Port 8100)         │
│  · claude (Claude Code)      │    │                                │
│  · gemini (Gemini CLI)       │    │  · YAML-driven personas        │
│  · agent (Cursor Agent)      │    │  · Capability chain resolution │
└──────────────────────────────┘    │  · Hot-reload file watcher     │
                                    │  · Syncs skills → Gateway      │
         ┌──────────────────────────└────────────────────────────────┘
         │ base image
         ▼
┌────────────────────────────┐      ┌────────────────────────────────┐
│   Dev Base Image           │      │   PostgreSQL 16                │
│   (Docker image)           │      │   (Port 5432)                  │
│                            │      │                                │
│  · Node 22 + npm           │      │  · Workflow state              │
│  · Go 1.24                 │      │  · Research results            │
│  · Python 3                │      │  · Agent run history           │
│  · Java 21 (Temurin)       │      └────────────────────────────────┘
│  · Claude Code CLI         │
│  · Gemini CLI              │
│  · Cursor Agent CLI        │
└────────────────────────────┘
```

---

## Services

### 1. Dev Base Image — `agent-cli-dev-base-docker`

A Docker base image that pre-installs every CLI agent and language runtime the gateway needs. The gateway's container is built on top of this image.

**What it ships:**
- Node.js 22 + `@anthropic-ai/claude-code` + `@google/gemini-cli`
- Go 1.24
- Python 3 + pip
- Eclipse Temurin JDK 21
- Cursor Agent CLI

**Why it exists:** Separates the heavy multi-tool installation from the lightweight gateway binary, keeping gateway rebuilds fast and the toolchain consistent across environments.

---

### 2. CLI Agent Gateway — `cli-agents-go-wrapper-service`

**Port:** `8080` (HTTP + WebSocket)
**Language:** Go 1.22

The central nervous system of the platform. Every AI agent interaction flows through here.

**Responsibilities:**
- Exposes a single `ws://host:8080/ws` endpoint for all clients
- Routes messages to the correct CLI agent subprocess via an **Adapter** per agent type
- Manages **sessions** with immutable `SessionID + Flow` routing keys
- **Auto-resumes** sessions after process death — no session is lost on restart
- Hosts **Skill** and **MCP** registries that the Capability Service populates
- Authenticates agents and caches auth state

**Agent Adapters:**

| Agent | Spawn Command | Auth |
|-------|--------------|------|
| Claude Code | `claude -p --output-format stream-json --verbose` | `claude auth login` |
| Gemini CLI | `gemini` | `gemini auth login` |
| Cursor Agent | `agent --agent` | `agent login` |

**Key API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/ws` | WebSocket upgrade — main communication channel |
| `GET` | `/health` | Liveness probe |
| `GET` | `/adapters` | List registered adapters and capabilities |
| `GET/DELETE` | `/agents/{agent}/auth` | Auth state management |
| `GET` | `/agents/{agent}/models` | List available models |
| `GET/POST` | `/skills` | Skill registry (populated by Capability Service) |
| `GET/POST` | `/mcps` | MCP registry (populated by Capability Service) |

**WebSocket Protocol:**
All messages use a typed envelope:
```json
{
  "sessionId": "...",
  "flow":      "research-workflow",
  "type":      "prompt.send",
  "payload":   { "prompt": "..." },
  "replyTo":   "..."
}
```

---

### 3. Capability Service — `ai-capability-skills-agent-persona`

**Port:** `8100` (HTTP)
**Language:** Python 3.12, FastAPI

Manages *who* an agent is and *what it can do* via declarative YAML configuration — think Kubernetes CRDs for AI agent identity.

**Three Extension Types:**

| Kind | Purpose | Example |
|------|---------|---------|
| `Persona` | Agent identity: name, tone, behavior config, list of capabilities, output schema | `research-analyst`, `code-reviewer` |
| `Capability` | Reusable skill fragment: a prompt snippet + required MCPs + config knobs + transitive dependencies | `web-search`, `critical-thinking`, `bias-detection` |
| `AgentProfile` | How to call a backend: gateway flow, session defaults, prompt template | `gemini-researcher`, `claude-reviewer` |

**Data Flow — Persona Resolution:**
1. Client requests `GET /api/v1/extensions/resolve?persona_name=X&agent_name=Y`
2. Resolver fetches persona + agent profile from registry
3. Resolves capability chain transitively (A depends on B depends on C → all included)
4. Renders each capability's prompt snippet with any config overrides
5. Assembles final prompt via agent's template
6. Returns `ResolvedPersona` (full prompt + MCP configs)
7. Optionally syncs the resolved skill to the Gateway via HTTP

**Hot-reload:** A Watchdog file watcher monitors YAML files and live-reloads any changed extension with a 1-second debounce — no restart needed.

**Key API Endpoints:**

| Path | Purpose |
|------|---------|
| `GET/POST /api/v1/extensions/personas` | CRUD personas |
| `GET/POST /api/v1/extensions/capabilities` | CRUD capabilities |
| `GET/POST /api/v1/extensions/agents` | CRUD agent profiles |
| `GET /api/v1/extensions/resolve` | Resolve persona for agent |
| `POST /api/v1/extensions/resolve/sync` | Resolve + push to Gateway |
| `GET /api/v1/health` | Health check |
| `GET /api/v1/stats` | Registry statistics |
| `POST /api/v1/reload` | Trigger manual hot-reload |

---

### 4. Research Workflow Service — `research-work-flow-ai`

**Port:** `8000` (HTTP + WebSocket)
**Language:** Python 3.12, FastAPI, SQLAlchemy
**Database:** PostgreSQL 16 (port `5432`)

The first workflow implementation — a multi-stage research orchestrator that coordinates multiple agents through iterative research, peer review, and consensus resolution cycles.

**Workflow Stages:**

```
[Request] → Research → Review → Consensus → [Result]
                  ↑         ↓
               (iterate if reviewer rejects)
```

**Agent Roles:**

| Role | Default Agent | Responsibility |
|------|--------------|----------------|
| Researcher | Gemini | Investigate topic, synthesize findings |
| Reviewer | Claude Code | Critically review research quality |
| Resolver | Gemini + Claude Code | Break ties, produce final consensus |

**Key Features:**
- Real-time event streaming via WebSocket (`/ws/workflows/{workflow_id}`)
- Full workflow persistence in PostgreSQL (Alembic migrations)
- Automatic reconnect to Gateway with exponential backoff (up to 10 retries)
- Workspace directory management for agent artifacts
- Integrates with Capability Service to resolve researcher/reviewer personas

**Key API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/workflows` | Start a new research workflow |
| `GET` | `/workflows/{id}` | Get workflow status and results |
| `GET` | `/ws/workflows/{id}` | Subscribe to real-time workflow events |
| `GET` | `/health` | Health check |

---

## Service Communication

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Research Workflow | Gateway | WebSocket | Send prompts, receive agent events |
| Research Workflow | Gateway | HTTP | Query adapters, manage skills |
| Research Workflow | Capability Service | HTTP | Resolve researcher/reviewer personas |
| Capability Service | Gateway | HTTP | Sync resolved skills and MCPs |
| External Client / UI | Gateway | WebSocket | Direct agent interaction |
| External Client / UI | Research Workflow | HTTP + WebSocket | Start workflows, stream results |

---

## Environment Variables

### Gateway (`cli-agents-go-wrapper-service`)

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Claude Code API key (required) |
| `GOOGLE_API_KEY` | — | Gemini API key (required) |
| `CURSOR_API_KEY` | — | Cursor API key (optional) |
| `GATEWAY_HOST` | `0.0.0.0` | Listen address |
| `GATEWAY_PORT` | `8080` | Listen port |
| `AGENT_WORK_DIR` | `/workspace` | Agent working directory |

### Capability Service (`CAPS_` prefix)

| Variable | Default | Description |
|----------|---------|-------------|
| `CAPS_PORT` | `8100` | Listen port |
| `CAPS_GATEWAY_HTTP_URL` | `http://gateway:8080` | Gateway URL for syncing |
| `CAPS_GATEWAY_SYNC_ON_STARTUP` | `true` | Sync skills on boot |
| `CAPS_HOT_RELOAD_ENABLED` | `true` | Watch YAML files for changes |
| `CAPS_PERSIST_API_EXTENSIONS` | `true` | Save API-created extensions to disk |
| `CAPS_LOG_LEVEL` | `INFO` | Log verbosity |

### Research Workflow (`RESEARCH_` prefix)

| Variable | Default | Description |
|----------|---------|-------------|
| `RESEARCH_DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@postgres:5432/research_workflows` | PostgreSQL connection |
| `RESEARCH_GATEWAY_WS_URL` | `ws://gateway:8080/ws` | Gateway WebSocket URL |
| `RESEARCH_GATEWAY_HTTP_URL` | `http://gateway:8080` | Gateway HTTP URL |
| `RESEARCH_CAPABILITY_SERVICE_URL` | `http://capability-service:8100` | Capability Service URL |
| `RESEARCH_WORKSPACE_BASE_DIR` | `/workspace/research` | Agent artifact storage |
| `RESEARCH_RESEARCHER_AGENT` | `gemini` | Default researcher adapter |
| `RESEARCH_REVIEWER_AGENT` | `claude-code` | Default reviewer adapter |
| `RESEARCH_LOG_LEVEL` | `INFO` | Log verbosity |

---

## Future Workflows

The research workflow is the first of several planned domain-specific workflow services. Each one connects to the same Gateway and Capability Service as a standalone microservice:

| Workflow | Status | Purpose |
|----------|--------|---------|
| Research Workflow | **Live** | Topic research, review, consensus |
| PRD Workflow | Planned | Product requirements authoring and review |
| Development Workflow | Planned | Code generation, review, iteration |
| QA & Release Workflow | Planned | Testing, validation, release notes |
| Knowledge Center Workflow | Planned | Documentation, knowledge extraction |

Each new workflow follows the same pattern:
1. Accept a domain-specific task request via REST
2. Connect to the Gateway via WebSocket to drive CLI agents
3. Optionally resolve personas from the Capability Service
4. Persist state and stream events back to the client
5. Deploy as an independent container with its own database if needed

---

## Port Reference

| Service | Port | Protocol |
|---------|------|----------|
| Gateway | `8080` | HTTP + WebSocket |
| Capability Service | `8100` | HTTP |
| Research Workflow | `8000` | HTTP + WebSocket |
| PostgreSQL | `5432` | TCP |

---

## Repository Structure

```
dorsiav2/
├── SYSTEM.md                          # This document
├── docker-compose.yml                 # Unified compose for all services
├── .env.example                       # Root environment variable template
│
├── agent-cli-dev-base-docker/         # Base Docker image (multi-tool dev container)
├── cli-agents-go-wrapper-service/     # CLI Agent Gateway (Go)
├── ai-capability-skills-agent-persona/# Capability & Persona Service (Python)
└── research-work-flow-ai/             # Research Workflow Orchestrator (Python)
```
