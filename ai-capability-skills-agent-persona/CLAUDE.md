# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run the service
capability-service
# or
uvicorn src.main:app --reload --port 8100

# Tests
pytest tests/
pytest tests/test_resolver.py -v
pytest tests/ --cov=src

# Lint & format
ruff check src/ tests/
ruff format src/ tests/

# Type check
mypy src/

# Docker
docker-compose up
```

Run a single test: `pytest tests/test_api.py -k "test_health" -v`

## Architecture

This is a FastAPI microservice that manages AI agent **personas**, **capabilities**, and **agent profiles** via declarative YAML specs. It resolves and assembles these into prompts + MCP configs, then syncs them to a CLI Agent Gateway.

### Three Extension Types (Kubernetes-style YAML with `kind`/`apiVersion`/`metadata`/`spec`)

- **Persona** — WHO the agent is: identity, behavior config (tone, critical-thinking, bias-detection), review dimensions, a list of capability names, output schema, and gateway skill config. `assemble_prompt()` builds the full identity + behavior + resolved capability prompts.
- **Capability** — Reusable skill fragments: a prompt snippet injected into a persona, compatible agents, required MCPs, and config knobs. Capabilities can depend on other capabilities (transitive resolution). `render_prompt(config_overrides)` applies overrides.
- **AgentProfile** — HOW to call an agent backend: gateway flow name, adapter endpoint, session defaults, prompt template with `{persona_prompt}` placeholder, and MCP filters. `is_gateway_agent` indicates CLI Agent Gateway routing.

### Data Flow: Resolution

`PersonaResolver.resolve(persona_name, agent_name, config_overrides)` → `ResolvedPersona`:
1. Fetch persona + agent profile from `ExtensionRegistry`
2. Resolve capability chain transitively, filter by agent compatibility
3. Render capability prompts with config overrides
4. Build final prompt via agent's template
5. Collect MCPs required by capabilities, filtered by agent's allowed MCPs
6. Return `ResolvedPersona` (prompt, mcp_configs, metadata)

`GatewaySync.sync(resolved)` pushes the resolved skill + MCPs to the CLI Agent Gateway over HTTP.

### Key Components

| Component | Location | Role |
|---|---|---|
| `ExtensionRegistry` | `src/registry/extension_registry.py` | Thread-safe (RLock) in-memory store for all 3 extension types; CRUD, tag filtering, capability chain resolution |
| `ExtensionLoader` | `src/loader/yaml_loader.py` | Discovers & parses YAML files from directories; validates via Pydantic |
| `PersonaResolver` | `src/resolver/persona_resolver.py` | Composes persona + capabilities + agent into `ResolvedPersona` |
| `GatewaySync` | `src/sync/gateway_sync.py` | HTTP client (httpx) pushing skills/MCPs to CLI Agent Gateway |
| `ExtensionWatcher` | `src/watcher/hot_reload.py` | Watchdog-based file watcher with 1s debounce; upserts changed extensions live |
| `ExtensionPersistence` | `src/persistence.py` | Saves API-created extensions as YAML to `config/extensions/` |
| `Settings` | `src/config.py` | Pydantic settings; all env vars prefixed `CAPS_` |

### Directory Layout

- `defaults/` — Built-in personas, capabilities, and agent profiles (shipped with the service)
- `config/extensions/` — User-created extensions persisted by the API (mounted as a volume in Docker)
- `src/api/` — REST endpoints: `personas.py`, `capabilities.py`, `agents.py`, `resolve.py`, `system.py`
- `src/models/` — Pydantic models for the 3 extension types plus `ResolvedPersona`/`ResolvedMcp`

### API Base Path

All CRUD endpoints: `/api/v1/extensions/{personas|capabilities|agents}`

Resolution: `GET /api/v1/extensions/resolve?persona_name=X&agent_name=Y` or `POST /resolve/sync` to also push to gateway.

System: `GET /api/v1/health`, `GET /api/v1/stats`, `POST /api/v1/reload`

### Configuration

Key `CAPS_` env vars:
- `CAPS_PORT` (default 8100), `CAPS_DEBUG`, `CAPS_LOG_LEVEL`
- `CAPS_DEFAULTS_DIR` — path to built-in extensions
- `CAPS_EXTENSIONS_DIR` — path to user-persisted extensions
- `CAPS_GATEWAY_HTTP_URL` — CLI Agent Gateway URL
- `CAPS_GATEWAY_SYNC_ON_STARTUP` — auto-sync on boot
- `CAPS_HOT_RELOAD_ENABLED` — watch YAML files for changes
