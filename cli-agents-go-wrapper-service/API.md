# CLI Agent Gateway — API Reference

A WebSocket-first gateway that exposes a single unified protocol for UI clients to communicate with multiple CLI coding agents (Claude Code, Cursor, Gemini). Agent management (authentication, models, modes, skills, MCPs) is exposed exclusively over HTTP. The WebSocket channel is reserved for the prompt/streaming lifecycle.

---

## Table of Contents

1. [Transport & Connection](#1-transport--connection)
2. [Message Envelope](#2-message-envelope)
3. [HTTP Endpoints](#3-http-endpoints)
   - [3.1 Health & Discovery](#31-health--discovery)
   - [3.2 Authentication](#32-authentication)
   - [3.3 Models](#33-models)
   - [3.4 Modes](#34-modes)
   - [3.5 Skills Registry](#35-skills-registry)
   - [3.6 MCP Registry](#36-mcp-registry)
   - [3.7 Session-Level Attachment](#37-session-level-attachment)
4. [WebSocket Message Types](#4-websocket-message-types)
   - [4.1 Session Lifecycle](#41-session-lifecycle)
   - [4.2 Prompts & Streaming](#42-prompts--streaming)
   - [4.3 Tool Use](#43-tool-use)
   - [4.4 Conversation History](#44-conversation-history)
   - [4.5 Errors](#45-errors)
5. [Server-Push Events](#5-server-push-events)
6. [Agent Capabilities](#6-agent-capabilities)
7. [Skills & MCPs](#7-skills--mcps)
8. [Session Routing Rules](#8-session-routing-rules)
9. [Connection Behaviour & Limits](#9-connection-behaviour--limits)
10. [Complete Examples](#10-complete-examples)
11. [Error Code Reference](#11-error-code-reference)

---

## 1. Transport & Connection

| Property | Value |
|----------|-------|
| Default port | `8080` (override with `--port` flag or `GATEWAY_PORT` env var) |
| WebSocket endpoint | `ws://<host>:<port>/ws` |
| WebSocket subprotocol | none required |
| Message format | UTF-8 JSON text frames |
| Max inbound message | 10 MB |
| Ping/pong keepalive | server pings every ~54 s; client must respond with pong |
| Write deadline | 10 s per frame |
| Idle read timeout | 60 s (reset on each pong) |

The server accepts any Origin header (development default). Restrict origins in production via the `upgrader.CheckOrigin` function.

---

## 2. Message Envelope

Every **WebSocket** message — both client-to-server and server-to-client — uses this envelope:

```json
{
  "id":        "<uuid-v4>",
  "type":      "<message-type>",
  "sessionId": "<your-session-id>",
  "flow":      "<agent-name>",
  "replyTo":   "<request-id>",
  "timestamp": "<RFC-3339>",
  "payload":   { ... },
  "error":     { "code": "...", "message": "..." }
}
```

| Field | Direction | Required | Description |
|-------|-----------|----------|-------------|
| `id` | Both | **Yes** | Unique message ID (UUID v4). Client generates for requests; server generates for pushes. |
| `type` | Both | **Yes** | Discriminates payload. See message types below. |
| `sessionId` | Both | **Yes** | Identifies the conversation. You provide this; the gateway treats it as-is. |
| `flow` | Both | **Yes** | Agent type: `claude-code`, `cursor`, or `gemini`. **Immutable per sessionId after first use.** |
| `replyTo` | Server→Client | No | Set on responses — contains the `id` of the triggering request. |
| `timestamp` | Both | No | ISO-8601/RFC-3339. Server always sets this on outbound messages. |
| `payload` | Both | Varies | JSON object. Shape depends on `type`. Omit or send `{}` when the type has no payload. |
| `error` | Server→Client | No | Present only on `type: "error"` messages. |

The gateway rejects any inbound message missing `id`, `sessionId`, `flow`, or `type` with a `VALIDATION_ERROR`.

---

## 3. HTTP Endpoints

All HTTP responses are `Content-Type: application/json`. Error responses carry `{"error": "<message>"}` at the appropriate 4xx/5xx status.

### 3.1 Health & Discovery

---

#### `GET /health`

Liveness probe.

**Response `200`:**
```json
{ "status": "ok", "time": "2026-03-21T00:00:00Z" }
```

---

#### `GET /adapters`

Lists every registered agent adapter with its full capability set. Model lists are **not** included here — use `GET /agents/{agent}/models` for live model discovery.

**Response `200`:**
```json
[
  {
    "name": "claude-code",
    "capabilities": {
      "agentType": "claude-code",
      "supportsTools": true,
      "supportsFiles": true,
      "supportsImages": true,
      "supportsDiff": true,
      "supportsHistory": true,
      "extra": { "supportsCancel": true, "supportsToolApproval": true }
    }
  },
  {
    "name": "cursor",
    "capabilities": {
      "agentType": "cursor",
      "supportsTools": true,
      "supportsFiles": true,
      "supportsDiff": true,
      "extra": { "supportsComposer": true }
    }
  },
  {
    "name": "gemini",
    "capabilities": {
      "agentType": "gemini",
      "supportsTools": true,
      "supportsFiles": true,
      "supportsImages": true,
      "extra": { "supportsMultimodal": true, "supportsSearch": true }
    }
  }
]
```

---

### 3.2 Authentication

The gateway checks each agent's login state before creating a session. If the agent is not logged in, `session.create` returns `AUTH_REQUIRED` with a browser URL the user must visit. After login the cached state is remembered for the server's lifetime (or until explicitly invalidated).

All three agents support CLI authentication: `claude-code` via `claude auth`, `cursor` via `agent login`/`agent status`, and `gemini` via `gemini auth`.

---

#### `GET /agents/{agent}/auth`

Returns the current authentication status for the named agent. Uses the in-memory cache when available; otherwise runs a live check (`<agent> auth status`).

**Path params:** `agent` — one of `claude-code`, `cursor`, `gemini`.

**Response `200`:**
```json
{
  "agentName":     "claude-code",
  "loggedIn":      true,
  "detail":        "email@example.com (Pro subscription)",
  "checkedAt":     "2026-03-21T00:10:00Z",
  "cacheHit":      true,
  "authSupported": true
}
```

| Field | Description |
|-------|-------------|
| `loggedIn` | `true` if credentials are valid and present. |
| `detail` | Human-readable output from the CLI's auth status command (account email, org name, etc.). |
| `checkedAt` | When the status was last checked (zero value if never cached). |
| `cacheHit` | `true` if the result came from cache without running a CLI check. |
| `authSupported` | `false` for agents that have no CLI login mechanism (e.g. `cursor`). |

**Response `404`:** Unknown agent name.

---

#### `POST /agents/{agent}/auth/login`

Initiates a login flow for the named agent. The agent CLI is invoked (`<agent> auth login`) and its stdout/stderr is scanned for a browser URL. The URL is returned immediately; the login process continues in the background. When the user completes the OAuth flow in their browser, the cache is automatically updated to `loggedIn: true`.

**No request body required.**

**Response `200` — login URL returned:**
```json
{
  "agentName":     "claude-code",
  "authSupported": true,
  "url":           "https://claude.ai/oauth/authorize?...",
  "message":       "visit the URL in your browser to complete login"
}
```

**Response `200` — already logged in (login exited without prompting):**
```json
{
  "agentName":     "claude-code",
  "authSupported": true,
  "loggedIn":      true,
  "message":       "already logged in"
}
```

**Response `200` — cursor login URL returned:**
```json
{
  "agentName":     "cursor",
  "authSupported": true,
  "url":           "https://cursor.com/oauth/authorize?...",
  "message":       "visit the URL in your browser to complete login"
}
```

**Response `404`:** Unknown agent name.

**Response `500`:** Agent login command failed to start or exited with an error.

---

#### `DELETE /agents/{agent}/auth`

Invalidates the cached authentication state for the agent. The next `GET /agents/{agent}/auth` or `session.create` will run a fresh live check.

**Response `200`:**
```json
{ "invalidated": "claude-code" }
```

---

### 3.3 Models

---

#### `GET /agents/{agent}/models`

Returns the list of model IDs supported by the named agent. These are the values accepted by the `model` field in `session.create` and `prompt.send`.

**Path params:** `agent` — one of `claude-code`, `cursor`, `gemini`.

**Response `200`:**
```json
{
  "agentName": "claude-code",
  "models": ["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
  "source": "api"
}
```

The `source` field indicates how the list was built:

| `source` | Meaning |
|----------|---------|
| `"config"` | Model list came from the server config file (static override) |
| `"api"` | Fetched live from the agent's API / CLI (`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, or `agent models`) |
| `"none"` | No list available — agent will use its own built-in default |

**Per-agent resolution:**

| Agent | Source | Requires |
|-------|--------|----------|
| `claude-code` | Anthropic REST API (`/v1/models`) | `ANTHROPIC_API_KEY` env var |
| `cursor` | `agent models` CLI command | Cursor agent logged in |
| `gemini` | Google Generative AI API (`/v1beta/models`) | `GOOGLE_API_KEY` env var |

**Response `404`:** Unknown agent name.

---

### 3.4 Modes

Modes control an agent's permission level, autonomy, and sandboxing behaviour. They are agent-specific and read-only — the mode is applied at `session.create` time via the WebSocket `payload.config` field.

---

#### `GET /agents/{agent}/modes`

Returns all operating modes supported by the named agent.

**Path params:** `agent` — one of `claude-code`, `cursor`, `gemini`.

**Response `200`:**
```json
{
  "agentName": "claude-code",
  "modes": [
    { "name": "default",           "description": "Standard permission prompting", "default": true },
    { "name": "acceptEdits",       "description": "Auto-accept file edits without prompting" },
    { "name": "bypassPermissions", "description": "Skip all permission checks (--dangerously-skip-permissions)" },
    { "name": "dontAsk",           "description": "Never ask for tool confirmation" },
    { "name": "plan",              "description": "Planning mode only — reads but does not execute" },
    { "name": "auto",              "description": "Fully autonomous mode with minimal interruption" }
  ]
}
```

**Response `404`** if agent name is unrecognised.

**All agent modes:**

| Agent | Modes |
|-------|-------|
| `claude-code` | `default` ✓, `acceptEdits`, `bypassPermissions`, `dontAsk`, `plan`, `auto` |
| `cursor` | `agent` ✓, `composer` |
| `gemini` | `default` ✓, `sandbox` |

✓ = default mode

---

### 3.5 Skills Registry

Skills are named prompt fragments injected as system-prompt extensions into every prompt sent to a session. They are stored in a global in-memory registry. A skill can be **global** (available to all agents) or **agent-scoped** (only visible to sessions running that specific agent).

When a skill is attached to a Claude Code session, it is passed as `--append-system-prompt "<skill.prompt>"` on every agent spawn. Multiple attached skills produce multiple flags, applied in attachment order.

---

#### `GET /skills`

Returns every registered skill regardless of scope.

**Response `200`:**
```json
{
  "skills": [
    {
      "name": "tdd-enforcer",
      "scope": "global",
      "description": "Enforces test-driven development practices",
      "prompt": "You are a strict TDD practitioner. Always write tests before implementation."
    },
    {
      "name": "typescript-only",
      "scope": "claude-code",
      "description": "Forces TypeScript output",
      "prompt": "Always output TypeScript. Never use plain JavaScript."
    }
  ]
}
```

---

#### `POST /skills`

Registers a new skill (or replaces an existing one with the same name).

**Request body:**
```json
{
  "name":        "tdd-enforcer",
  "scope":       "global",
  "description": "Enforces TDD",
  "prompt":      "Always write tests before implementation."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **Yes** | Unique identifier for this skill. |
| `scope` | string | No | `"global"` (default) or an agent name like `"claude-code"`. |
| `description` | string | No | Human-readable summary. |
| `prompt` | string | **Yes** | The system prompt text to inject. |

**Response `201`:** The created skill object.

**Response `400`:** `{"error": "skill name must not be empty"}`

---

#### `DELETE /skills/{name}`

Removes a skill from the global registry. Already-attached sessions are **not** affected — the skill stays attached to those sessions until explicitly detached.

**Response `200`:** `{"deleted": "tdd-enforcer"}`

**Response `404`:** `{"error": "skill not found: tdd-enforcer"}`

---

#### `GET /agents/{agent}/skills`

Returns skills visible to the named agent: all global skills plus skills scoped specifically to that agent.

**Response `200`:**
```json
{
  "agentName": "claude-code",
  "skills": [
    { "name": "tdd-enforcer",   "scope": "global",      "description": "...", "prompt": "..." },
    { "name": "typescript-only","scope": "claude-code",  "description": "...", "prompt": "..." }
  ]
}
```

---

### 3.6 MCP Registry

MCP (Model Context Protocol) servers extend an agent's tool capabilities with external integrations (filesystems, GitHub, databases, etc.). Like skills, they live in a global registry and can be scoped globally or per-agent.

For Claude Code, attached MCPs are serialised into a single `--mcp-config '{"mcpServers":{...}}'` JSON argument on every prompt spawn, so they take effect immediately on the next prompt without a session restart.

---

#### `GET /mcps`

Returns every registered MCP server config.

**Response `200`:**
```json
{
  "mcps": [
    {
      "name":    "filesystem",
      "scope":   "global",
      "type":    "stdio",
      "command": "npx",
      "args":    ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    },
    {
      "name":    "github",
      "scope":   "claude-code",
      "type":    "stdio",
      "command": "npx",
      "args":    ["-y", "@modelcontextprotocol/server-github"],
      "env":     { "GITHUB_TOKEN": "ghp_xxxx" }
    }
  ]
}
```

---

#### `POST /mcps`

Registers a new MCP server config (or replaces one with the same name).

**Request body:**
```json
{
  "name":    "filesystem",
  "scope":   "global",
  "type":    "stdio",
  "command": "npx",
  "args":    ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
  "env":     {}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | **Yes** | Unique identifier. |
| `scope` | string | No | `"global"` (default) or agent name. |
| `type` | string | No | `"stdio"` (default), `"sse"`, or `"http"`. |
| `command` | string | For stdio | Binary to execute. |
| `args` | string[] | No | Arguments to the command. |
| `url` | string | For sse/http | Endpoint URL. |
| `env` | object | No | Extra environment variables. |

**Response `201`:** The created MCP config object.

**Response `400`:** `{"error": "mcp server name must not be empty"}`

---

#### `DELETE /mcps/{name}`

Removes an MCP server from the global registry. Already-attached sessions keep the MCP attached until explicitly detached.

**Response `200`:** `{"deleted": "filesystem"}`

**Response `404`:** `{"error": "mcp not found: filesystem"}`

---

#### `GET /agents/{agent}/mcps`

Returns MCP servers visible to the named agent: global MCPs plus agent-scoped ones.

**Response `200`:**
```json
{
  "agentName": "claude-code",
  "mcps": [
    { "name": "filesystem", "scope": "global",      "type": "stdio", "command": "npx", "args": [...] },
    { "name": "github",     "scope": "claude-code",  "type": "stdio", "command": "npx", "args": [...] }
  ]
}
```

---

### 3.7 Session-Level Attachment

Skills and MCPs must be **registered** in the global registry first, then **attached** to individual live sessions. Attachment is per-session and persists for the lifetime of the session (including auto-resumes after process crashes).

The list endpoints annotate each item with an `attached` boolean so clients can show current state.

---

#### `GET /sessions/{sessionId}/skills`

Lists all skills visible to the session's agent, annotated with `attached` status.

**Response `200`:**
```json
{
  "sessionId": "my-session-001",
  "skills": [
    {
      "name": "tdd-enforcer", "scope": "global", "description": "...", "prompt": "...",
      "attached": true
    },
    {
      "name": "typescript-only", "scope": "claude-code", "description": "...", "prompt": "...",
      "attached": false
    }
  ]
}
```

**Response `404`:** Session not found.

---

#### `POST /sessions/{sessionId}/skills/{skillName}`

Attaches a registered skill to the session. Idempotent — attaching the same skill twice replaces the entry.

Takes effect on the **next** `prompt.send` (no restart needed for Claude Code).

**Response `200`:**
```json
{ "attached": "tdd-enforcer", "sessionId": "my-session-001" }
```

**Response `404`:** Session or skill not found.

---

#### `DELETE /sessions/{sessionId}/skills/{skillName}`

Detaches a skill from the session. The global registry is not affected.

**Response `200`:**
```json
{ "detached": "tdd-enforcer", "sessionId": "my-session-001" }
```

**Response `404`:** Session not found or skill was not attached.

---

#### `GET /sessions/{sessionId}/mcps`

Lists all MCP servers visible to the session's agent, annotated with `attached` status.

**Response `200`:**
```json
{
  "sessionId": "my-session-001",
  "mcps": [
    {
      "name": "filesystem", "scope": "global", "type": "stdio", "command": "npx", "args": [...],
      "attached": true
    },
    {
      "name": "github", "scope": "claude-code", "type": "stdio", "command": "npx", "args": [...],
      "attached": false
    }
  ]
}
```

**Response `404`:** Session not found.

---

#### `POST /sessions/{sessionId}/mcps/{mcpName}`

Attaches a registered MCP server to the session. Takes effect on the **next** `prompt.send`.

**Response `200`:**
```json
{ "attached": "filesystem", "sessionId": "my-session-001" }
```

**Response `404`:** Session or MCP not found.

---

#### `DELETE /sessions/{sessionId}/mcps/{mcpName}`

Detaches an MCP server from the session. The global registry is not affected.

**Response `200`:**
```json
{ "detached": "filesystem", "sessionId": "my-session-001" }
```

**Response `404`:** Session not found or MCP was not attached.

---

## 4. WebSocket Message Types

### 4.1 Session Lifecycle

---

#### `session.create` → `session.created`

Creates a new agent session. If the `sessionId` already exists with the same `flow`, the existing session is returned (idempotent).

> **Authentication note:** Before starting the agent, the gateway checks login state. If not logged in, a `AUTH_REQUIRED` error is returned instead of `session.created`. Call `POST /agents/{agent}/auth/login`, complete the browser flow, then retry.

**Client sends:**
```json
{
  "id": "11111111-0000-0000-0000-000000000001",
  "type": "session.create",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": {
    "connectionMode": "spawn",
    "workingDir": "/home/user/project",
    "model": "claude-sonnet-4-6",
    "config": { "apiKey": "sk-ant-..." }
  }
}
```

| Payload field | Type | Required | Description |
|---------------|------|----------|-------------|
| `connectionMode` | string | No | `"spawn"` (default) — starts the CLI agent as a subprocess. |
| `workingDir` | string | No | Filesystem path for the agent. Defaults to server CWD. |
| `model` | string | No | Override the default model. See `GET /agents/{agent}/models`. |
| `connectAddress` | string | No | For `"connect"` mode — address of an existing agent server. |
| `config` | object | No | Agent-specific key/value config (e.g. `apiKey`). |

**Server replies:**
```json
{
  "id": "aaaaaaaa-...",
  "type": "session.created",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "replyTo": "11111111-0000-0000-0000-000000000001",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": {
    "sessionId": "my-session-001",
    "flow": "claude-code",
    "status": "created",
    "capabilities": { ... }
  }
}
```

| `status` | Meaning |
|----------|---------|
| `"created"` | New session started |
| `"existing"` | Session already running, returned as-is |
| `"resumed"` | Session existed but agent process was dead; re-spawned transparently |

**Auth failure response:**
```json
{
  "type": "error",
  "error": {
    "code": "AUTH_REQUIRED",
    "message": "AUTH_REQUIRED: agent \"claude-code\" is not logged in; visit https://claude.ai/oauth/authorize?..."
  }
}
```

---

#### `session.resume` → `session.resumed`

Re-attaches to an existing session after a WebSocket reconnect. If the agent process died, it is transparently re-spawned with the original config — including any skills and MCPs that were attached before the crash.

**Client sends:**
```json
{
  "id": "11111111-0000-0000-0000-000000000010",
  "type": "session.resume",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": {}
}
```

**Server replies:** `session.resumed` with the same shape as `session.created`.

---

#### `session.list` → `session.list.result`

Returns all sessions tracked by the server (global, not per-client).

**Client sends:**
```json
{
  "id": "22222222-0000-0000-0000-000000000001",
  "type": "session.list",
  "sessionId": "any-session-id",
  "flow": "claude-code",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": {}
}
```

**Server replies:**
```json
{
  "type": "session.list.result",
  "payload": {
    "sessions": [
      {
        "sessionId": "my-session-001",
        "flow": "claude-code",
        "status": "running",
        "createdAt": "2026-03-21T00:00:00Z",
        "workingDir": "/home/user/project"
      }
    ]
  }
}
```

---

#### `session.end` → `session.ended`

Permanently terminates and removes a session. The session **cannot** be resumed after this.

**Client sends:**
```json
{
  "id": "33333333-0000-0000-0000-000000000001",
  "type": "session.end",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": {}
}
```

**Server replies:** `session.ended` with `payload: null`.

---

### 4.2 Prompts & Streaming

---

#### `prompt.send` → streaming events

Sends a user message. No direct reply; the server emits a stream of push events (see [Section 5](#5-server-push-events)).

Skills and MCPs attached to the session are automatically applied to this prompt — no extra fields required.

**Client sends:**
```json
{
  "id": "44444444-0000-0000-0000-000000000001",
  "type": "prompt.send",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": {
    "content": "Explain how context managers work in Python.",
    "attachments": [
      {
        "type": "file",
        "name": "example.py",
        "content": "with open('file') as f:\n    data = f.read()",
        "mimeType": "text/x-python"
      }
    ],
    "options": { "effort": "high" }
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | **Yes** | The user's prompt text. |
| `attachments` | array | No | Files or images. |
| `options` | object | No | Agent-specific options. |

**Attachment fields:** `type` (`"file"` / `"image"` / `"url"`), `name`, `content` (text or base64), `mimeType`, `path`.

**Typical event sequence:**
```
stream.start
agent.status  {"status":"thinking"}
stream.delta  {"contentType":"text","content":"Context managers..."}
...
stream.end    {"finishReason":"complete","usage":{...}}
agent.status  {"status":"idle"}
```

---

#### `prompt.cancel`

Aborts an in-flight prompt. No acknowledgement sent.

```json
{
  "id": "55555555-0000-0000-0000-000000000001",
  "type": "prompt.cancel",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": {}
}
```

---

### 4.3 Tool Use

---

#### `tool.approve`

Approves a pending tool call. No reply.

```json
{
  "id": "66666666-0000-0000-0000-000000000001",
  "type": "tool.approve",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": { "toolId": "toolu_01Abc123" }
}
```

> **Claude Code** uses `--dangerously-skip-permissions`, so tools are auto-approved. `tool.approve` is forwarded but has no effect.

---

#### `tool.reject`

Rejects a pending tool call. No reply.

```json
{
  "id": "77777777-0000-0000-0000-000000000001",
  "type": "tool.reject",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": { "toolId": "toolu_01Abc123", "reason": "This command looks dangerous." }
}
```

---

### 4.4 Conversation History

---

#### `history.request` → `history.result`

Fetch conversation history. Only supported where `supportsHistory: true` (currently Claude Code only).

```json
{
  "id": "88888888-0000-0000-0000-000000000001",
  "type": "history.request",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "timestamp": "2026-03-21T00:00:00Z",
  "payload": { "limit": 20, "before": "msg-cursor-id" }
}
```

**Server replies:**
```json
{
  "type": "history.result",
  "payload": {
    "messages": [
      { "id": "msg-001", "role": "user",      "content": "...", "timestamp": "..." },
      { "id": "msg-002", "role": "assistant", "content": "...", "timestamp": "..." }
    ],
    "hasMore": false
  }
}
```

---

### 4.5 Errors

Any failure returns `type: "error"`:

```json
{
  "type": "error",
  "sessionId": "my-session-001",
  "flow": "claude-code",
  "replyTo": "<triggering-message-id>",
  "error": { "code": "FLOW_MISMATCH", "message": "..." }
}
```

See [Section 11](#11-error-code-reference) for all codes.

---

## 5. Server-Push Events

Emitted by the server during a `prompt.send` cycle without a direct client request.

| Event | When |
|-------|------|
| `stream.start` | Always first — marks beginning of response |
| `agent.status` | On state transitions: `"thinking"`, `"tool_use"`, `"idle"`, `"error"` |
| `stream.delta` | One or more content chunks; concatenate `content` to reconstruct full response |
| `stream.end` | Response complete; carries `finishReason` and `usage` |
| `stream.error` | Fatal agent error mid-stream |
| `tool.use.start` | Agent wants to invoke a tool; carries `toolId`, `toolName`, `input` |
| `tool.use.result` | Tool execution result; carries `toolId`, `output`, `isError` |
| `file.changed` / `file.created` / `file.deleted` | Agent modified a file on disk |
| `file.diff` | Agent produced a unified diff |
| `progress` | Optional progress update; carries `message` and `percentage` (0–100, `-1` = indeterminate) |

**`stream.delta` contentType values:** `"text"`, `"markdown"`, `"code"`, `"thinking"`, `"tool_input"`

**`stream.end` finishReason values:** `"complete"`, `"cancelled"`, `"error"`, `"max_tokens"`

---

## 6. Agent Capabilities

Returned in `session.created` payload and `GET /adapters`.

### Capability matrix

| Capability | claude-code | cursor | gemini |
|------------|:-----------:|:------:|:------:|
| Tools | ✓ | ✓ | ✓ |
| Files | ✓ | ✓ | ✓ |
| Images | ✓ | — | ✓ |
| Diffs | ✓ | ✓ | — |
| History | ✓ | — | — |
| Multimodal | — | — | ✓ |
| Web search | — | — | ✓ |
| Composer mode | — | ✓ | — |
| Cancel | ✓ | ✓ | ✓ |
| Tool approval | ✓ | — | ✓ |
| CLI auth | ✓ | ✓ | ✓ |

### Models

Models are fetched dynamically — use `GET /agents/{agent}/models` for the live list. No model is selected by default; if `model` is omitted from `session.create`, each agent uses its own built-in default.

---

## 7. Skills & MCPs

### Skill scope rules

| `scope` value | Visible to |
|---------------|-----------|
| `"global"` | All agents |
| `"claude-code"` | Only claude-code sessions |
| `"cursor"` | Only cursor sessions |
| `"gemini"` | Only gemini sessions |

### Skill lifecycle

```
POST /skills                           → register in global registry
POST /sessions/{id}/skills/{name}      → attach to a live session
  (next prompt.send picks it up)
DELETE /sessions/{id}/skills/{name}    → detach from session
DELETE /skills/{name}                  → remove from registry (attached sessions unaffected)
```

### MCP type values

| `type` | Transport | Required fields |
|--------|-----------|-----------------|
| `"stdio"` | Subprocess stdin/stdout | `command`, optionally `args`, `env` |
| `"sse"` | HTTP Server-Sent Events | `url` |
| `"http"` | Plain HTTP | `url` |

### How attachments work per agent

| Agent | Skills | MCPs |
|-------|--------|------|
| **claude-code** | `--append-system-prompt "<prompt>"` per skill, on every spawn | `--mcp-config '{"mcpServers":{...}}'` on every spawn |
| **cursor** | Stored; takes effect after session restart | Stored; takes effect after session restart |
| **gemini** | Stored; takes effect after session restart | Stored; takes effect after session restart |

> **Claude Code** spawns a new process per `prompt.send`, so skills and MCPs attached between prompts take effect immediately on the very next prompt — no session restart required.

### Auto-resume preservation

When an agent process crashes and is auto-resumed, all attached skills and MCPs are transferred to the new adapter instance automatically. Clients do not need to re-attach.

---

## 8. Session Routing Rules

### Rule 1 — `sessionId` + `flow` binding is immutable

The first `session.create` for a `sessionId` binds it permanently to a `flow`. All subsequent messages with that `sessionId` must use the same `flow`; mismatches return `FLOW_MISMATCH`.

### Rule 2 — Sessions are server-scoped

Sessions survive WebSocket disconnects. `session.resume` re-attaches a client to an existing session.

### Rule 3 — Auto-resume on process death

If the agent process crashes, the session is not deleted. The next `prompt.send` or `session.resume` transparently re-spawns it, preserving attached skills and MCPs.

### Rule 4 — `session.end` is permanent

`session.end` removes the session from the registry. It cannot be resumed. Subsequent messages with that `sessionId` return `SESSION_NOT_FOUND`.

### Rule 5 — `session.list` is global

Returns all sessions on the server, not just the requesting client's. `sessionId`/`flow` in the envelope are required by the validator but do not filter results.

---

## 9. Connection Behaviour & Limits

| Limit | Value |
|-------|-------|
| Max inbound WS message | 10 MB |
| Write deadline per frame | 10 s |
| Idle timeout (no pong) | 60 s |
| Client send buffer | 256 messages |
| Stdout buffer per process | 1 MB |
| HTTP server shutdown grace | 10 s |
| HTTP read timeout | 15 s |
| HTTP write timeout | 15 s |
| Auth check timeout | 10 s |
| Login URL wait timeout | 15 s |
| Background login monitor | 5 min |

---

## 10. Complete Examples

### Example A — Check auth, register a skill, attach it, send a prompt

```
# 1. Check auth status (uses cache after first call)
GET /agents/claude-code/auth
← { "loggedIn": true, "detail": "user@example.com", "cacheHit": false }

# If not logged in:
POST /agents/claude-code/auth/login
← { "url": "https://claude.ai/oauth/authorize?...", "message": "visit the URL in your browser..." }
# User opens URL → completes OAuth → cache auto-updated

# 2. Register a global skill
POST /skills
{ "name": "tdd-enforcer", "scope": "global",
  "prompt": "Always write tests before implementation." }

# 3. Create a session (via WebSocket)
→ session.create  { "sessionId": "s1", "flow": "claude-code", "payload": { "workingDir": "/project" } }
← session.created { "status": "created", "capabilities": { ... } }

# 4. Attach the skill to the session
POST /sessions/s1/skills/tdd-enforcer
← { "attached": "tdd-enforcer", "sessionId": "s1" }

# 5. Attach an MCP server
POST /mcps
{ "name": "fs", "scope": "global", "type": "stdio",
  "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/project"] }

POST /sessions/s1/mcps/fs
← { "attached": "fs", "sessionId": "s1" }

# 6. Send a prompt — skill and MCP are automatically injected
→ prompt.send { "content": "Add unit tests for the auth module." }
← stream.start
← agent.status { "status": "thinking" }
← stream.delta { "contentType": "text", "content": "I'll write the tests..." }
← stream.end   { "finishReason": "complete", "usage": { "totalCost": 0.012 } }
← agent.status { "status": "idle" }
```

### Example B — Multi-turn Claude Code conversation

```jsonc
// WebSocket messages only shown

// Create
{ "id":"req-001","type":"session.create","sessionId":"demo","flow":"claude-code",
  "payload":{"connectionMode":"spawn","workingDir":"/home/user/myproject","model":"claude-sonnet-4-6"} }
// ← session.created

// Turn 1
{ "id":"req-002","type":"prompt.send","sessionId":"demo","flow":"claude-code",
  "payload":{"content":"What files are in this directory?"} }
// ← stream.start, agent.status, tool.use.start (Bash: ls), tool.use.result,
//    stream.delta ("main.go, go.mod, README.md"), stream.end, agent.status

// Turn 2 — session continues via --resume internally
{ "id":"req-003","type":"prompt.send","sessionId":"demo","flow":"claude-code",
  "payload":{"content":"Show me the contents of main.go"} }
// ← stream.start, agent.status, tool.use.start (Read), ...

// End
{ "id":"req-099","type":"session.end","sessionId":"demo","flow":"claude-code","payload":{} }
// ← session.ended
```

### Example C — Reconnect & resume

```jsonc
// Client lost WebSocket connection; reconnects

{ "id":"req-resume","type":"session.resume","sessionId":"demo","flow":"claude-code","payload":{} }

// Server response (agent process still alive):
{ "type":"session.resumed","payload":{"status":"existing","capabilities":{...}} }

// If agent crashed, status is "resumed" — agent was re-spawned automatically,
// and all previously attached skills/MCPs are still active.
```

### Example D — Handle AUTH_REQUIRED on session.create

```jsonc
// Client attempts to create a session but agent is not logged in
→ { "type": "session.create", "sessionId": "s1", "flow": "claude-code", "payload": {} }
← { "type": "error", "error": { "code": "AUTH_REQUIRED",
    "message": "AUTH_REQUIRED: agent \"claude-code\" is not logged in; visit https://claude.ai/oauth/..." } }

// Client calls login via HTTP (not WebSocket)
POST /agents/claude-code/auth/login
← { "url": "https://claude.ai/oauth/authorize?...", "message": "visit the URL in your browser to complete login" }

// User opens URL in browser and completes OAuth
// Cache is auto-updated when CLI detects login completion

// Client retries session.create
→ { "type": "session.create", "sessionId": "s1", "flow": "claude-code", "payload": { "workingDir": "/project" } }
← { "type": "session.created", "payload": { "status": "created", ... } }
```

---

## 11. Error Code Reference

### WebSocket errors

| Code | Triggering condition |
|------|---------------------|
| `PARSE_ERROR` | Inbound message is not valid JSON |
| `VALIDATION_ERROR` | Envelope missing `id`, `sessionId`, `flow`, or `type` |
| `INVALID_PAYLOAD` | `payload` cannot be decoded for this message type |
| `UNKNOWN_TYPE` | `type` is not a recognised message type |
| `AUTH_REQUIRED` | Agent is not logged in; `message` contains browser login URL |
| `SESSION_CREATE_FAILED` | Agent failed to start (binary not found, bad config, etc.) |
| `SESSION_RESUME_FAILED` | `session.resume` for non-existent session or flow mismatch |
| `SESSION_END_FAILED` | `session.end` for a session that doesn't exist |
| `SESSION_ERROR` | Generic session-level dispatch error |
| `SESSION_NOT_FOUND` | Message references a `sessionId` that was never created |
| `FLOW_MISMATCH` | `sessionId` bound to a different `flow` |
| `PROMPT_FAILED` | Agent process error during `prompt.send` |
| `HISTORY_FAILED` | Agent does not support history, or fetch failed |

### HTTP errors

| Status | Triggering condition |
|--------|---------------------|
| `400 Bad Request` | Missing required field (`name`), invalid JSON body |
| `404 Not Found` | Unknown agent name, skill name, MCP name, or session ID |
| `405 Method Not Allowed` | Wrong HTTP method for the endpoint |
| `500 Internal Server Error` | Auth check or login command failed unexpectedly |
