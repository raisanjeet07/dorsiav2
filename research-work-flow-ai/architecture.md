# Research Workflow Service — Architecture Document

**Version:** 1.0
**Date:** 2026-03-21
**Stack:** Python 3.12 + FastAPI · PostgreSQL · WebSocket + REST
**Upstream Dependency:** CLI Agent Gateway (Go service on port 8080)

---

## 1. System Overview

The Research Workflow Service orchestrates multi-agent research workflows where:

1. A **Gemini agent** performs deep research on a topic and produces a report.
2. A **Claude Code reviewer agent** (with a custom persona + skills) reviews the report.
3. **Resolver agents** (Gemini + Claude Code with different personas) address review comments.
4. The cycle repeats until **consensus** is reached between reviewer and resolvers.
5. The report enters **user review**, where the user chats with a Claude Code agent to ask questions and request changes.
6. Once the user approves, a **final report** is generated incorporating all conversations, comments, and feedback — weighted toward user input.

All agent interactions flow through the existing **CLI Agent Gateway** (Go WebSocket service), meaning this service is a **workflow orchestrator** — it does not talk to agents directly.

```
┌──────────┐        ┌──────────────────────┐        ┌──────────────────┐
│          │  WS    │  Research Workflow    │  WS    │  CLI Agent       │
│    UI    │◄──────►│  Service (FastAPI)    │◄──────►│  Gateway (Go)    │
│          │        │                      │        │                  │
│          │  REST  │  - State Machine     │  REST  │  - Claude Code   │
│          │◄──────►│  - Orchestrator      │◄──────►│  - Gemini        │
│          │        │  - Persistence       │        │  - Cursor        │
└──────────┘        └──────────────────────┘        └──────────────────┘
                              │
                              ▼
                    ┌──────────────────┐
                    │   PostgreSQL     │
                    │   + Workspace FS │
                    └──────────────────┘
```

---

## 2. Workflow State Machine

### 2.1 States

| State | Code | Description |
|-------|------|-------------|
| **Initiated** | `INITIATED` | Workflow created, workflowId assigned, configuration validated |
| **Researching** | `RESEARCHING` | Gemini agent is performing research and generating the initial report |
| **Research Complete** | `RESEARCH_COMPLETE` | Gemini produced the report (`.md` artifact saved to workspace) |
| **Reviewing** | `REVIEWING` | Claude Code reviewer agent is reviewing the report with its persona/skills |
| **Review Complete** | `REVIEW_COMPLETE` | Reviewer produced structured review comments |
| **Resolving** | `RESOLVING` | Resolver agents (Gemini + Claude Code) are addressing review comments |
| **Resolution Complete** | `RESOLUTION_COMPLETE` | Resolvers produced answers; merged response ready |
| **Re-reviewing** | `RE_REVIEWING` | Reviewer evaluating the merged resolution against original comments |
| **Consensus Reached** | `CONSENSUS_REACHED` | Reviewer and resolvers agree; report is ready for user |
| **User Review** | `USER_REVIEW` | User is chatting with Claude Code agent, asking questions, requesting changes |
| **User Approved** | `USER_APPROVED` | User explicitly approved the report |
| **Generating Final Report** | `GENERATING_FINAL` | Agent generating final report incorporating all feedback |
| **Completed** | `COMPLETED` | Final report delivered |
| **Failed** | `FAILED` | Unrecoverable error at any stage |
| **Cancelled** | `CANCELLED` | User cancelled the workflow |

### 2.2 Transition Diagram

```
INITIATED
    │
    ▼
RESEARCHING ──────────────────────────────► FAILED
    │
    ▼
RESEARCH_COMPLETE
    │
    ▼
REVIEWING ────────────────────────────────► FAILED
    │
    ▼
REVIEW_COMPLETE
    │
    ▼
RESOLVING ────────────────────────────────► FAILED
    │
    ▼
RESOLUTION_COMPLETE
    │
    ▼
RE_REVIEWING ─────────────────────────────► FAILED
    │
    ├──── (no consensus) ──► RESOLVING     ◄── review cycle repeats
    │
    ▼
CONSENSUS_REACHED
    │
    ▼
USER_REVIEW ──────────────────────────────► FAILED
    │
    ├──── (user requests changes) ──► RESOLVING   ◄── back to resolution
    │
    ▼
USER_APPROVED
    │
    ▼
GENERATING_FINAL ─────────────────────────► FAILED
    │
    ▼
COMPLETED

Any state ──► CANCELLED  (user-initiated)
```

### 2.3 Transition Rules

| From | To | Trigger | Guard |
|------|----|---------|-------|
| `INITIATED` | `RESEARCHING` | Automatic after creation | Config valid, gateway reachable |
| `RESEARCHING` | `RESEARCH_COMPLETE` | Gemini stream ends with `finishReason: "complete"` | Report artifact exists in workspace |
| `RESEARCH_COMPLETE` | `REVIEWING` | Automatic | Report file readable |
| `REVIEWING` | `REVIEW_COMPLETE` | Claude Code reviewer stream ends | Review comments parsed |
| `REVIEW_COMPLETE` | `RESOLVING` | Automatic | At least one review comment exists |
| `RESOLVING` | `RESOLUTION_COMPLETE` | Both resolver agents complete | Merged response assembled |
| `RESOLUTION_COMPLETE` | `RE_REVIEWING` | Automatic | Merged response available |
| `RE_REVIEWING` | `CONSENSUS_REACHED` | Reviewer signals consensus | `consensus: true` in review output |
| `RE_REVIEWING` | `RESOLVING` | Reviewer has new/remaining comments | `consensus: false`, review cycle < max |
| `CONSENSUS_REACHED` | `USER_REVIEW` | Automatic | — |
| `USER_REVIEW` | `USER_APPROVED` | User sends explicit approval | — |
| `USER_REVIEW` | `RESOLVING` | User requests specific changes | Changes list provided |
| `USER_APPROVED` | `GENERATING_FINAL` | Automatic | — |
| `GENERATING_FINAL` | `COMPLETED` | Final report agent completes | Final artifact saved |
| Any | `FAILED` | Unrecoverable error | Max retries exceeded |
| Any active | `CANCELLED` | User cancels | Workflow not yet completed |

### 2.4 Review Cycle Limits

To prevent infinite loops, the system enforces:

- **`max_review_cycles`**: Default 5. After this many REVIEWING→RESOLVING round-trips without consensus, the system force-transitions to `CONSENSUS_REACHED` with a flag `forced_consensus: true`.
- **`max_user_change_requests`**: Default 3. After this many USER_REVIEW→RESOLVING round-trips, the system notifies the user and requests explicit approval.

---

## 3. Component Architecture

### 3.1 Core Components

```
research-workflow-service/
├── app/
│   ├── main.py                    # FastAPI app, lifespan, CORS
│   ├── config.py                  # Settings (env-based via pydantic-settings)
│   │
│   ├── api/                       # HTTP + WS endpoints
│   │   ├── router.py              # Top-level router aggregation
│   │   ├── workflows.py           # REST: create, list, get, cancel workflows
│   │   ├── websocket.py           # WS: real-time streaming to UI
│   │   └── reports.py             # REST: download/view final reports
│   │
│   ├── core/                      # Domain logic
│   │   ├── state_machine.py       # State enum, transitions, guards
│   │   ├── orchestrator.py        # Main workflow engine
│   │   ├── review_cycle.py        # Review ↔ resolve loop logic
│   │   └── consensus.py           # Consensus detection logic
│   │
│   ├── agents/                    # Agent interaction layer
│   │   ├── gateway_client.py      # WebSocket client to CLI Agent Gateway
│   │   ├── base.py                # Abstract agent interface
│   │   ├── researcher.py          # Gemini research agent orchestration
│   │   ├── reviewer.py            # Claude Code reviewer agent
│   │   ├── resolver.py            # Dual-agent resolver (Gemini + Claude)
│   │   ├── user_chat.py           # Claude Code agent for user Q&A
│   │   └── report_generator.py    # Final report generation agent
│   │
│   ├── models/                    # Data models
│   │   ├── workflow.py            # Workflow, state, config models
│   │   ├── review.py              # Review comment, resolution models
│   │   ├── conversation.py        # Conversation turn models
│   │   └── report.py              # Report artifact models
│   │
│   ├── persistence/               # Storage layer
│   │   ├── database.py            # SQLAlchemy async engine + session
│   │   ├── repositories.py        # CRUD operations
│   │   └── workspace.py           # File system workspace manager
│   │
│   ├── streaming/                 # Real-time event layer
│   │   ├── event_bus.py           # In-process pub/sub for workflow events
│   │   ├── client_manager.py      # Track connected UI WebSocket clients
│   │   └── events.py              # Event type definitions
│   │
│   └── skills/                    # Skill/persona definitions
│       ├── reviewer_persona.py    # Reviewer agent persona prompt
│       ├── resolver_personas.py   # Resolver agent persona prompts
│       └── registry.py            # Register skills with gateway on startup
│
├── migrations/                    # Alembic DB migrations
├── workspace/                     # Runtime artifact storage (mounted volume)
├── tests/
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

### 3.2 Component Responsibilities

**Orchestrator** (`core/orchestrator.py`) — The brain of the system. For each workflow:
- Manages the state machine lifecycle
- Decides which agent to invoke next based on current state
- Coordinates the review cycle (tracks cycle count, detects consensus)
- Emits events to the event bus for every state transition and agent output
- Handles error recovery and retry logic

**Gateway Client** (`agents/gateway_client.py`) — Single WebSocket connection pool to the Go gateway:
- Maintains persistent WS connections (one per active agent session)
- Translates between workflow-level operations and gateway envelope protocol
- Handles session.create, prompt.send, stream events, session.end
- Manages skill/MCP attachment via gateway REST API
- Reconnect logic with exponential backoff

**Event Bus** (`streaming/event_bus.py`) — Decouples orchestration from UI delivery:
- In-process async pub/sub (per workflow channel)
- Events: state changes, agent stream deltas, review comments, user messages
- UI WebSocket handler subscribes to workflow channels
- Enables multiple UI clients to observe the same workflow

**Workspace Manager** (`persistence/workspace.py`) — Structured file storage:
- Creates per-workflow directory trees
- Saves/loads reports, conversations, review artifacts
- Provides paths for agent `workingDir` configuration

---

## 4. Agent Orchestration Detail

### 4.1 Agent Sessions Matrix

Each workflow uses multiple agent sessions through the gateway. Every session gets a deterministic `sessionId` derived from the workflowId:

| Role | Agent Flow | Session ID Pattern | Persona | Mode |
|------|-----------|-------------------|---------|------|
| Researcher | `gemini` | `{wfId}-researcher` | — (uses system prompt via skill) | `default` |
| Reviewer | `claude-code` | `{wfId}-reviewer` | Senior research analyst, critical thinker | `bypassPermissions` |
| Resolver (Gemini) | `gemini` | `{wfId}-resolver-gemini` | — | `default` |
| Resolver (Claude) | `claude-code` | `{wfId}-resolver-claude` | Domain expert, fact-checker | `bypassPermissions` |
| User Chat | `claude-code` | `{wfId}-user-chat` | Helpful research assistant | `bypassPermissions` |
| Final Report | `claude-code` | `{wfId}-final-report` | Technical writer, synthesizer | `bypassPermissions` |

### 4.2 Skill Registration Strategy

At service startup, register reusable skills with the gateway:

```python
SKILLS = [
    {
        "name": "research-reviewer",
        "scope": "claude-code",
        "description": "Senior research analyst persona for reviewing reports",
        "prompt": """You are a senior research analyst. Your role is to critically
        review research reports for: accuracy, completeness, logical consistency,
        source quality, bias, and actionable insights.

        Output your review as structured JSON:
        {
          "consensus": false,
          "overall_quality": "good|fair|poor",
          "comments": [
            {
              "id": "rev-001",
              "severity": "critical|major|minor|suggestion",
              "section": "...",
              "comment": "...",
              "recommendation": "..."
            }
          ],
          "summary": "..."
        }"""
    },
    {
        "name": "research-resolver-claude",
        "scope": "claude-code",
        "description": "Domain expert persona for resolving review comments",
        "prompt": """You are a domain expert and fact-checker. You receive review
        comments on a research report and must address each one with evidence-based
        responses. Be thorough and cite sources where possible.

        Output as structured JSON:
        {
          "resolutions": [
            {
              "comment_id": "rev-001",
              "response": "...",
              "changes_made": "...",
              "evidence": "..."
            }
          ]
        }"""
    },
    # ... additional skills
]
```

Skills are attached per-session via `POST /sessions/{sessionId}/skills/{skillName}` before the first prompt.

### 4.3 Agent Interaction Flow

Each agent interaction follows this pattern:

```
Orchestrator                    Gateway Client                    CLI Gateway
    │                               │                                │
    │  invoke_agent(role, prompt)    │                                │
    │──────────────────────────────►│                                │
    │                               │  WS: session.create            │
    │                               │───────────────────────────────►│
    │                               │  WS: session.created           │
    │                               │◄───────────────────────────────│
    │                               │                                │
    │                               │  REST: attach skills           │
    │                               │───────────────────────────────►│
    │                               │  200 OK                        │
    │                               │◄───────────────────────────────│
    │                               │                                │
    │                               │  WS: prompt.send               │
    │                               │───────────────────────────────►│
    │                               │                                │
    │   on_stream_delta(chunk)      │  WS: stream.delta              │
    │◄──────────────────────────────│◄───────────────────────────────│
    │   → event_bus.publish()       │                                │
    │                               │  WS: stream.end                │
    │   on_stream_end(result)       │◄───────────────────────────────│
    │◄──────────────────────────────│                                │
    │                               │                                │
    │  (state transition)           │                                │
    │  next_agent(...)              │                                │
```

### 4.4 Resolver Merge Strategy

When both resolver agents (Gemini + Claude) address review comments:

1. Both resolvers receive the same review comments + current report.
2. They run concurrently (parallel gateway sessions).
3. Their outputs are merged:
   - For each comment, both resolutions are compared.
   - If they agree, the response is used directly.
   - If they disagree, both perspectives are included with a note for the reviewer.
4. The merged response is sent to the reviewer in the next RE_REVIEWING cycle.

---

## 5. API Design

### 5.1 REST Endpoints

#### Workflow Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/workflows` | Create a new research workflow |
| `GET` | `/api/v1/workflows` | List all workflows (with pagination + filters) |
| `GET` | `/api/v1/workflows/{workflowId}` | Get workflow details + current state |
| `GET` | `/api/v1/workflows/{workflowId}/state` | Get detailed state info (current state, history, cycle count) |
| `POST` | `/api/v1/workflows/{workflowId}/cancel` | Cancel a running workflow |
| `GET` | `/api/v1/workflows/{workflowId}/report` | Get the current report (any stage) |
| `GET` | `/api/v1/workflows/{workflowId}/report/final` | Download the final report |
| `GET` | `/api/v1/workflows/{workflowId}/reviews` | Get all review rounds and comments |
| `GET` | `/api/v1/workflows/{workflowId}/conversations` | Get all conversation history |

#### User Review Actions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/workflows/{workflowId}/approve` | User approves the report |
| `POST` | `/api/v1/workflows/{workflowId}/request-changes` | User requests specific changes |

#### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Service health + gateway connectivity |
| `GET` | `/api/v1/config/personas` | List available agent personas |

### 5.2 Request/Response Models

#### Create Workflow

```json
// POST /api/v1/workflows
// Request:
{
  "topic": "Impact of quantum computing on cryptography in the next decade",
  "context": "Focus on post-quantum cryptography standards and migration timelines",
  "depth": "comprehensive",          // "quick" | "standard" | "comprehensive"
  "maxReviewCycles": 5,              // optional, default 5
  "outputFormat": "markdown",        // "markdown" | "pdf"
  "workspaceConfig": {
    "baseDir": "/workspace/research" // optional, default from config
  }
}

// Response 201:
{
  "workflowId": "wf-a1b2c3d4",
  "state": "INITIATED",
  "topic": "Impact of quantum computing on cryptography...",
  "createdAt": "2026-03-21T10:00:00Z",
  "websocketUrl": "/ws/workflows/wf-a1b2c3d4"
}
```

#### Get Workflow State

```json
// GET /api/v1/workflows/{workflowId}/state
// Response 200:
{
  "workflowId": "wf-a1b2c3d4",
  "currentState": "REVIEWING",
  "previousState": "RESEARCH_COMPLETE",
  "reviewCycle": 2,
  "maxReviewCycles": 5,
  "stateHistory": [
    { "state": "INITIATED", "enteredAt": "2026-03-21T10:00:00Z" },
    { "state": "RESEARCHING", "enteredAt": "2026-03-21T10:00:01Z" },
    { "state": "RESEARCH_COMPLETE", "enteredAt": "2026-03-21T10:05:32Z" },
    { "state": "REVIEWING", "enteredAt": "2026-03-21T10:05:33Z" }
  ],
  "activeSessions": [
    { "role": "reviewer", "sessionId": "wf-a1b2c3d4-reviewer", "agent": "claude-code", "status": "running" }
  ],
  "artifacts": {
    "reportPath": "/workspace/research/wf-a1b2c3d4/reports/draft-v1.md",
    "reviewPaths": ["/workspace/research/wf-a1b2c3d4/reviews/review-cycle-1.json"],
    "conversationCount": 12
  }
}
```

### 5.3 WebSocket Protocol (UI ↔ Research Service)

Connection: `ws://{host}:{port}/ws/workflows/{workflowId}`

All messages follow an envelope format:

```json
{
  "type": "<event-type>",
  "workflowId": "wf-a1b2c3d4",
  "timestamp": "2026-03-21T10:05:33Z",
  "payload": { ... }
}
```

#### Client → Server (UI sends)

| Type | Description | Payload |
|------|-------------|---------|
| `user.message` | User sends a chat message during USER_REVIEW | `{ "content": "Can you elaborate on section 3?" }` |
| `user.approve` | User approves the report | `{ "comment": "Looks good, optional final note" }` |
| `user.request_changes` | User requests changes | `{ "changes": [{ "section": "...", "request": "..." }] }` |
| `user.cancel` | User cancels the workflow | `{}` |

#### Server → Client (UI receives)

| Type | Description | Payload |
|------|-------------|---------|
| `workflow.state_changed` | State transition occurred | `{ "from": "RESEARCHING", "to": "RESEARCH_COMPLETE", "reviewCycle": 0 }` |
| `agent.stream_start` | An agent started producing output | `{ "role": "researcher", "agent": "gemini", "sessionId": "..." }` |
| `agent.stream_delta` | Incremental content from an agent | `{ "role": "researcher", "contentType": "text", "content": "chunk..." }` |
| `agent.stream_end` | Agent finished producing output | `{ "role": "researcher", "finishReason": "complete" }` |
| `agent.status` | Agent status change | `{ "role": "reviewer", "status": "thinking" }` |
| `agent.tool_use` | Agent is using a tool | `{ "role": "reviewer", "toolName": "Read", "input": {...} }` |
| `review.comments` | Review comments produced | `{ "cycle": 1, "comments": [...], "consensus": false }` |
| `resolution.merged` | Merged resolution ready | `{ "cycle": 1, "resolutions": [...] }` |
| `report.updated` | Report artifact was updated | `{ "version": "draft-v2", "path": "..." }` |
| `user_chat.response` | Claude responds to user's chat message | `{ "content": "Section 3 covers...", "streaming": true }` |
| `workflow.completed` | Workflow finished | `{ "finalReportPath": "...", "summary": "..." }` |
| `workflow.error` | Error occurred | `{ "code": "AGENT_TIMEOUT", "message": "...", "recoverable": true }` |

---

## 6. Database Schema

### 6.1 Tables

```sql
-- Core workflow tracking
CREATE TABLE workflows (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id     VARCHAR(50) UNIQUE NOT NULL,    -- human-readable ID (wf-xxxx)
    topic           TEXT NOT NULL,
    context         TEXT,
    depth           VARCHAR(20) DEFAULT 'standard',
    current_state   VARCHAR(30) NOT NULL DEFAULT 'INITIATED',
    previous_state  VARCHAR(30),
    review_cycle    INTEGER DEFAULT 0,
    max_review_cycles INTEGER DEFAULT 5,
    forced_consensus BOOLEAN DEFAULT FALSE,
    output_format   VARCHAR(20) DEFAULT 'markdown',
    workspace_path  TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- State transition audit log
CREATE TABLE state_transitions (
    id              BIGSERIAL PRIMARY KEY,
    workflow_id     VARCHAR(50) REFERENCES workflows(workflow_id),
    from_state      VARCHAR(30),
    to_state        VARCHAR(30) NOT NULL,
    trigger         VARCHAR(100),                    -- what caused the transition
    metadata        JSONB,                           -- extra context
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Agent sessions linked to workflows
CREATE TABLE agent_sessions (
    id              BIGSERIAL PRIMARY KEY,
    workflow_id     VARCHAR(50) REFERENCES workflows(workflow_id),
    session_id      VARCHAR(100) NOT NULL,           -- gateway session ID
    role            VARCHAR(30) NOT NULL,             -- researcher, reviewer, resolver-gemini, etc.
    agent_flow      VARCHAR(20) NOT NULL,             -- claude-code, gemini
    status          VARCHAR(20) DEFAULT 'created',    -- created, running, completed, failed
    persona_skill   VARCHAR(50),                      -- skill name attached
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ
);

-- Review rounds
CREATE TABLE review_rounds (
    id              BIGSERIAL PRIMARY KEY,
    workflow_id     VARCHAR(50) REFERENCES workflows(workflow_id),
    cycle           INTEGER NOT NULL,
    reviewer_session VARCHAR(100),
    consensus       BOOLEAN DEFAULT FALSE,
    overall_quality VARCHAR(20),
    summary         TEXT,
    raw_output      JSONB,                           -- full reviewer output
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Individual review comments
CREATE TABLE review_comments (
    id              BIGSERIAL PRIMARY KEY,
    review_round_id BIGINT REFERENCES review_rounds(id),
    comment_id      VARCHAR(50) NOT NULL,             -- rev-001, etc.
    severity        VARCHAR(20),                      -- critical, major, minor, suggestion
    section         TEXT,
    comment         TEXT NOT NULL,
    recommendation  TEXT,
    resolved        BOOLEAN DEFAULT FALSE,
    resolution      JSONB                             -- resolver's response
);

-- Conversation turns (all agent interactions)
CREATE TABLE conversation_turns (
    id              BIGSERIAL PRIMARY KEY,
    workflow_id     VARCHAR(50) REFERENCES workflows(workflow_id),
    session_id      VARCHAR(100),
    role            VARCHAR(30) NOT NULL,              -- which agent role
    direction       VARCHAR(10) NOT NULL,              -- 'inbound' (prompt) or 'outbound' (response)
    content         TEXT NOT NULL,
    content_type    VARCHAR(20) DEFAULT 'text',
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Report artifacts
CREATE TABLE report_artifacts (
    id              BIGSERIAL PRIMARY KEY,
    workflow_id     VARCHAR(50) REFERENCES workflows(workflow_id),
    version         VARCHAR(30) NOT NULL,              -- draft-v1, draft-v2, final
    file_path       TEXT NOT NULL,
    artifact_type   VARCHAR(20) DEFAULT 'report',      -- report, review, resolution
    size_bytes      BIGINT,
    checksum        VARCHAR(64),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_workflows_state ON workflows(current_state);
CREATE INDEX idx_state_transitions_workflow ON state_transitions(workflow_id);
CREATE INDEX idx_conversation_turns_workflow ON conversation_turns(workflow_id);
CREATE INDEX idx_review_rounds_workflow ON review_rounds(workflow_id);
```

---

## 7. Workspace File Structure

Each workflow gets an isolated directory tree:

```
workspace/
└── {workflowId}/
    ├── config.json                    # Workflow configuration snapshot
    ├── reports/
    │   ├── draft-v1.md                # Initial research output (Gemini)
    │   ├── draft-v2.md                # After first resolution cycle
    │   ├── draft-v3.md                # After second cycle...
    │   └── final.md                   # Final approved report
    ├── reviews/
    │   ├── cycle-1/
    │   │   ├── review.json            # Reviewer's structured comments
    │   │   ├── resolution-gemini.json # Gemini resolver output
    │   │   ├── resolution-claude.json # Claude resolver output
    │   │   └── merged-resolution.json # Merged response sent to reviewer
    │   ├── cycle-2/
    │   │   └── ...
    │   └── cycle-N/
    ├── conversations/
    │   ├── researcher.jsonl           # Gemini research conversation log
    │   ├── reviewer.jsonl             # All reviewer interactions
    │   ├── resolver-gemini.jsonl      # Gemini resolver conversations
    │   ├── resolver-claude.jsonl      # Claude resolver conversations
    │   └── user-chat.jsonl            # User Q&A session
    └── metadata/
        ├── state-history.json         # Full state transition log
        └── timeline.json              # Timestamped event timeline
```

The `workingDir` passed to each gateway `session.create` is set to the workflow's workspace directory, so agents can read/write files within it.

---

## 8. Streaming Architecture

### 8.1 Event Flow (Agent → UI)

```
CLI Agent ──stdout──► Gateway ──WS──► Gateway Client ──async──► Event Bus ──async──► UI WS Handler ──WS──► Browser
                                          │
                                          ▼
                                    Orchestrator
                                    (state transitions,
                                     next agent decision)
                                          │
                                          ▼
                                    Persistence
                                    (DB + workspace)
```

Every `stream.delta` from the gateway is:
1. Forwarded to the event bus immediately (for real-time UI).
2. Accumulated in a buffer for the orchestrator (for state transition decisions).
3. Appended to the conversation log (for persistence).

### 8.2 UI WebSocket Connection Lifecycle

```
Browser                          Research Service
   │                                    │
   │  WS connect /ws/workflows/{id}     │
   │───────────────────────────────────►│
   │                                    │  Subscribe to event bus channel
   │                                    │  Load current state from DB
   │  workflow.state_changed            │
   │◄───────────────────────────────────│  (send current state as first message)
   │                                    │
   │  agent.stream_delta (continuous)   │
   │◄───────────────────────────────────│  (forwarded from agent in real-time)
   │                                    │
   │  user.message                      │
   │───────────────────────────────────►│  (only valid in USER_REVIEW state)
   │                                    │  → forward to user-chat agent session
   │  user_chat.response (streaming)    │
   │◄───────────────────────────────────│
   │                                    │
   │  user.approve                      │
   │───────────────────────────────────►│  → trigger state transition
   │  workflow.state_changed            │
   │◄───────────────────────────────────│
```

### 8.3 Multiple Client Support

Multiple browser tabs/devices can observe the same workflow:
- Each WS connection subscribes to the same event bus channel.
- Only one client can send `user.message` at a time (first-writer-wins with a lightweight lock).
- State changes and agent output are broadcast to all subscribers.

---

## 9. Prompt Construction

### 9.1 Research Prompt (Gemini)

```
Topic: {topic}
Context: {context}
Depth: {depth}

Perform comprehensive research on the above topic. Your output should be a
well-structured markdown report saved to ./reports/draft-v1.md with:
- Executive summary
- Key findings organized by theme
- Evidence and sources for each finding
- Analysis and implications
- Recommendations (if applicable)
- Areas of uncertainty or debate

Be thorough, balanced, and cite sources where possible.
```

### 9.2 Review Prompt (Claude Code Reviewer)

```
Review the research report at ./reports/draft-v{N}.md

Evaluate for: accuracy, completeness, logical consistency, source quality,
potential bias, clarity, and actionable insights.

{If cycle > 1: "Previous review comments and resolutions are in ./reviews/cycle-{N-1}/.
Focus on whether the resolutions adequately addressed your previous concerns."}

Output your review as JSON to stdout following the schema defined in your skill.
Set "consensus": true if the report meets quality standards.
```

### 9.3 Resolution Prompt (Resolvers)

```
The following review comments were raised about the research report at
./reports/draft-v{N}.md:

{review_comments_json}

Address each comment with evidence-based responses. Where changes to the report
are warranted, make them directly in the file and save an updated version as
./reports/draft-v{N+1}.md.

Output your resolutions as JSON to stdout following the schema in your skill.
```

### 9.4 Final Report Prompt

```
Generate the final version of the research report. Consider ALL of the following:

1. The current report at ./reports/draft-v{latest}.md
2. All review cycles in ./reviews/
3. The user conversation at ./conversations/user-chat.jsonl
4. User approval comments: {user_approval_comment}

WEIGHTING: User feedback and requests take highest priority, followed by
reviewer consensus points, then resolver additions.

Save the final report to ./reports/final.md. Include:
- All substantive content from the research
- Addressed points from every review cycle
- Any modifications requested by the user
- A brief methodology note at the end summarizing the review process
```

---

## 10. Error Handling & Recovery

### 10.1 Error Categories

| Category | Example | Recovery |
|----------|---------|----------|
| **Transient** | Gateway WS disconnect, agent timeout | Auto-retry with backoff (3 attempts) |
| **Agent Failure** | Agent process crash mid-stream | Resume session via gateway, re-send prompt |
| **Gateway Down** | Gateway service unreachable | Queue operations, retry, notify UI |
| **Consensus Deadlock** | Max cycles reached | Force consensus, flag for user |
| **User Timeout** | No user response in USER_REVIEW | Notify via WS, keep session alive for 24h |
| **Permanent** | Invalid config, unsupported agent | Transition to FAILED with error detail |

### 10.2 Retry Policy

```python
RETRY_CONFIG = {
    "max_attempts": 3,
    "base_delay_seconds": 2,
    "max_delay_seconds": 30,
    "exponential_base": 2,
    "retryable_errors": [
        "AGENT_TIMEOUT",
        "SESSION_RESUME_FAILED",
        "GATEWAY_DISCONNECT",
        "PROMPT_FAILED",
    ]
}
```

### 10.3 Graceful Shutdown

On SIGINT/SIGTERM:
1. Stop accepting new workflows.
2. For each active workflow, send `session.end` to all gateway sessions.
3. Persist current state to DB with `interrupted: true` metadata.
4. On restart, scan for interrupted workflows and offer resume.

---

## 11. Configuration

```python
# Environment-based via pydantic-settings
class Settings(BaseSettings):
    # Service
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Gateway connection
    gateway_ws_url: str = "ws://localhost:8080/ws"
    gateway_http_url: str = "http://localhost:8080"
    gateway_reconnect_max_attempts: int = 10

    # Database
    database_url: str = "postgresql+asyncpg://user:pass@localhost:5432/research_workflows"

    # Workspace
    workspace_base_dir: str = "/workspace/research"

    # Workflow defaults
    default_max_review_cycles: int = 5
    default_depth: str = "standard"
    agent_prompt_timeout_seconds: int = 300
    user_review_timeout_hours: int = 24

    # Agent defaults
    researcher_model: str = ""          # use agent default
    reviewer_model: str = "claude-sonnet-4-6"
    resolver_claude_model: str = "claude-sonnet-4-6"

    class Config:
        env_prefix = "RESEARCH_"
```

---

## 12. Deployment

### 12.1 Docker Compose

```yaml
version: "3.9"
services:
  research-service:
    build: .
    ports:
      - "8000:8000"
    environment:
      RESEARCH_GATEWAY_WS_URL: ws://gateway:8080/ws
      RESEARCH_GATEWAY_HTTP_URL: http://gateway:8080
      RESEARCH_DATABASE_URL: postgresql+asyncpg://postgres:postgres@db:5432/research
      RESEARCH_WORKSPACE_BASE_DIR: /workspace
    volumes:
      - workspace:/workspace
    depends_on:
      - db
      - gateway

  gateway:
    image: cli-agent-gateway:latest
    ports:
      - "8080:8080"
    environment:
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      GOOGLE_API_KEY: ${GOOGLE_API_KEY}

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: research
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  workspace:
  pgdata:
```

---

## 13. Key Design Decisions

**Why PostgreSQL over Redis/SQLite?**
The workflow involves structured relational data (workflows → review rounds → comments → resolutions) with audit requirements. PostgreSQL handles this natively, supports JSONB for flexible metadata, and scales beyond single-node when needed.

**Why orchestrator-as-client (not embedded agents)?**
All agents run through the gateway. This service never spawns CLI processes directly. This means: single point of agent management, shared session/skill/MCP infrastructure, and the gateway handles process lifecycle, auth, and reconnection.

**Why dual resolvers (Gemini + Claude)?**
Different models have different strengths. Gemini excels at web research and source finding; Claude excels at code analysis and logical reasoning. Running both in parallel and merging gives higher-quality resolutions. The merge strategy also surfaces disagreements for the reviewer.

**Why file-based workspace + DB?**
Agents interact with the file system (they read/write markdown files, use tools like Read/Write). The workspace gives agents a natural working directory. The DB tracks workflow state, relationships, and enables queries that file-scanning can't do efficiently.

**Why in-process event bus (not Kafka/Redis Streams)?**
For a single-node deployment, an in-process async pub/sub avoids infrastructure complexity. If horizontal scaling is needed later, this can be swapped for Redis Pub/Sub with minimal interface changes.

---

## 14. Extensibility Module — Agents, Personas & Capabilities

The system is designed to be extended without code changes. New agents, personas, skills, and capabilities are defined declaratively via YAML configuration and loaded at startup (or hot-reloaded at runtime). This module is a **standalone, reusable package** that can be imported by any workflow service — not just the research workflow.

### 14.1 Extension Architecture

```
extensions/                              # Standalone Python package
├── __init__.py
├── loader.py                            # YAML discovery, validation, loading
├── registry.py                          # In-memory registry with lookup/query
├── models.py                            # Pydantic models for all extension types
├── sync.py                              # Syncs extensions → CLI Agent Gateway
├── resolver.py                          # Resolves composed capabilities at runtime
├── hot_reload.py                        # File watcher for live config changes
│
├── schemas/                             # JSON Schema for validation
│   ├── persona.schema.json
│   ├── capability.schema.json
│   └── agent_profile.schema.json
│
└── defaults/                            # Built-in extensions (ship with the system)
    ├── personas/
    │   ├── research-reviewer.yaml
    │   ├── domain-expert.yaml
    │   ├── fact-checker.yaml
    │   └── technical-writer.yaml
    ├── capabilities/
    │   ├── web-research.yaml
    │   ├── code-analysis.yaml
    │   └── citation-validation.yaml
    └── agents/
        ├── claude-code.yaml
        └── gemini.yaml
```

User/project extensions live in a separate directory:

```
config/extensions/                       # User-defined (project-specific)
├── personas/
│   ├── medical-reviewer.yaml
│   └── legal-analyst.yaml
├── capabilities/
│   └── compliance-check.yaml
└── agents/
    └── custom-llm.yaml
```

### 14.2 Persona Definition (YAML Schema)

A persona defines **who** the agent is — its identity, behavioral instructions, and output expectations.

```yaml
# config/extensions/personas/medical-reviewer.yaml
apiVersion: v1
kind: Persona
metadata:
  name: medical-reviewer
  description: "Board-certified medical research reviewer"
  tags: [medical, research, review]
  author: "team"
  version: "1.0.0"

spec:
  # Core identity
  identity: |
    You are a board-certified medical researcher with 20+ years of experience
    in clinical research methodology. You review research reports with the rigor
    expected of a peer-reviewed journal submission.

  # Behavioral instructions
  behavior:
    tone: professional
    criticalThinking: high
    evidenceRequirement: strict       # strict | moderate | relaxed
    biasDetection: true
    outputLanguage: english

  # What the persona checks for (used by the orchestrator for routing)
  reviewDimensions:
    - accuracy
    - methodology
    - statistical_validity
    - ethical_considerations
    - clinical_relevance
    - source_quality

  # Output schema the persona must follow
  outputSchema:
    format: json
    template: |
      {
        "consensus": false,
        "overall_quality": "good|fair|poor",
        "methodology_score": 0,
        "comments": [
          {
            "id": "rev-001",
            "severity": "critical|major|minor|suggestion",
            "dimension": "one of reviewDimensions",
            "section": "...",
            "comment": "...",
            "evidence_required": "...",
            "recommendation": "..."
          }
        ],
        "summary": "..."
      }

  # Composable capabilities this persona uses (resolved at runtime)
  capabilities:
    - citation-validation
    - statistical-analysis

  # Skills to register with the gateway (auto-registered on load)
  gatewaySkill:
    scope: claude-code                  # or "global" or "gemini"
    # The prompt is auto-assembled from identity + behavior + outputSchema
    # Override with explicit prompt if needed:
    # promptOverride: "..."
```

### 14.3 Capability Definition (YAML Schema)

A capability defines **what** an agent can do — a reusable skill fragment that can be composed into personas or attached independently.

```yaml
# config/extensions/capabilities/citation-validation.yaml
apiVersion: v1
kind: Capability
metadata:
  name: citation-validation
  description: "Validates citations and references in research documents"
  tags: [research, citations, validation]
  version: "1.0.0"

spec:
  # The prompt fragment injected when this capability is active
  prompt: |
    When reviewing content, validate all citations and references:
    - Check that claims have supporting references
    - Flag unsupported assertions
    - Note when sources are outdated (>5 years for fast-moving fields)
    - Identify potential circular references
    - Verify source credibility (peer-reviewed > preprint > blog)

  # Which agent types support this capability
  compatibleAgents:
    - claude-code
    - gemini

  # MCP servers this capability needs (auto-attached to sessions)
  requiredMcps:
    - name: web-search
      type: stdio
      command: npx
      args: ["-y", "@modelcontextprotocol/server-web-search"]
      onlyIf: agent == "claude-code"    # conditional attachment

  # Dependencies on other capabilities
  dependsOn: []

  # Configuration knobs (overridable per-persona or per-workflow)
  config:
    maxSourceAge:
      type: integer
      default: 5
      description: "Max age in years before a source is flagged as outdated"
    requirePeerReview:
      type: boolean
      default: true
      description: "Whether to require peer-reviewed sources"
```

### 14.4 Agent Profile Definition (YAML Schema)

An agent profile defines **how** to interact with a specific agent backend — its connection settings, supported modes, and defaults.

```yaml
# config/extensions/agents/claude-code.yaml
apiVersion: v1
kind: AgentProfile
metadata:
  name: claude-code
  description: "Claude Code CLI agent via gateway"
  version: "1.0.0"

spec:
  # Gateway flow name (maps to CLI Agent Gateway's flow field)
  gatewayFlow: claude-code

  # Default session configuration
  defaults:
    mode: bypassPermissions
    model: claude-sonnet-4-6
    connectionMode: spawn

  # Supported modes (informational — actual modes come from gateway)
  supportedModes:
    - default
    - bypassPermissions
    - auto
    - plan

  # How personas are applied to this agent
  personaApplication:
    method: skill                        # skill | systemPrompt | appendPrompt
    # "skill" → register as gateway skill, attach per-session
    # "systemPrompt" → inject via --append-system-prompt
    # "appendPrompt" → prepend to every prompt.send content

  # How capabilities are applied
  capabilityApplication:
    skills: merge                        # merge all capability prompts into persona skill
    mcps: attach                         # attach each capability's MCPs individually

  # Agent-specific prompt wrapping
  promptTemplate: |
    {persona_prompt}

    {capability_prompts}

    IMPORTANT: Follow the output schema exactly. Output valid JSON only.

  # Health check configuration
  healthCheck:
    endpoint: /agents/claude-code/auth
    field: loggedIn
    expectedValue: true
```

```yaml
# config/extensions/agents/custom-ollama.yaml  — EXAMPLE: adding a new agent type
apiVersion: v1
kind: AgentProfile
metadata:
  name: ollama-local
  description: "Local Ollama model (not via gateway — direct HTTP)"
  version: "1.0.0"

spec:
  # No gatewayFlow — this agent uses a custom adapter
  adapter: http-completion
  endpoint: http://localhost:11434/api/generate

  defaults:
    model: llama3.1:70b
    temperature: 0.7

  personaApplication:
    method: systemPrompt               # injected as system message in API call

  capabilityApplication:
    skills: merge
    mcps: none                          # local model doesn't support MCPs

  promptTemplate: |
    {persona_prompt}

    {capability_prompts}
```

### 14.5 How It All Composes Together

At runtime, when the orchestrator needs to invoke an agent role (e.g., "reviewer"), the resolution chain is:

```
1. Workflow config specifies:     role: reviewer → persona: medical-reviewer

2. Registry resolves persona:     medical-reviewer.yaml
   ├── identity prompt
   ├── behavior rules
   ├── outputSchema
   └── capabilities: [citation-validation, statistical-analysis]

3. Registry resolves capabilities: citation-validation.yaml, statistical-analysis.yaml
   ├── prompt fragments
   ├── requiredMcps
   └── config values (with overrides from persona or workflow)

4. Registry resolves agent:        claude-code.yaml (from persona's gatewaySkill.scope)
   ├── session defaults (mode, model)
   ├── personaApplication method
   └── promptTemplate

5. Assembler builds the final skill:
   ┌─────────────────────────────────────────────────┐
   │  promptTemplate                                  │
   │  ├── {persona_prompt} = identity + behavior      │
   │  ├── {capability_prompts} = joined cap prompts   │
   │  └── outputSchema appended                       │
   └─────────────────────────────────────────────────┘

6. Gateway sync:
   ├── POST /skills  → register assembled skill
   ├── POST /mcps    → register required MCPs
   ├── session.create with agent defaults
   ├── POST /sessions/{id}/skills/{name}
   └── POST /sessions/{id}/mcps/{name}
```

**Visual:**

```
┌─────────────┐   ┌──────────────────┐   ┌─────────────────┐
│   Workflow   │   │    Persona       │   │  Agent Profile  │
│   Config     │──►│  medical-reviewer│──►│  claude-code    │
│              │   │                  │   │                 │
│ role:reviewer│   │  capabilities:   │   │  mode, model    │
│ persona: ... │   │  ├─ citation-val │   │  prompt template│
└─────────────┘   │  └─ stat-analysis│   └────────┬────────┘
                  └────────┬─────────┘            │
                           │                      │
                  ┌────────▼─────────┐            │
                  │  Capability      │            │
                  │  Resolver        │◄───────────┘
                  │                  │
                  │  Merges prompts, │
                  │  MCPs, configs   │
                  └────────┬─────────┘
                           │
                  ┌────────▼─────────┐
                  │  Gateway Sync    │
                  │                  │
                  │  → register skill│
                  │  → register MCPs │
                  │  → create session│
                  │  → attach all    │
                  └──────────────────┘
```

### 14.6 Workflow-Level Persona Overrides

When creating a workflow, users can override which personas are used and tweak capability configs:

```json
// POST /api/v1/workflows
{
  "topic": "CRISPR gene therapy safety profile",
  "depth": "comprehensive",
  "agentConfig": {
    "researcher": {
      "agent": "gemini",
      "persona": null,
      "capabilities": ["web-research"]
    },
    "reviewer": {
      "agent": "claude-code",
      "persona": "medical-reviewer",
      "capabilityOverrides": {
        "citation-validation": {
          "maxSourceAge": 3,
          "requirePeerReview": true
        }
      }
    },
    "resolvers": [
      {
        "agent": "gemini",
        "persona": "domain-expert",
        "capabilities": ["web-research", "citation-validation"]
      },
      {
        "agent": "claude-code",
        "persona": "fact-checker"
      }
    ],
    "userChat": {
      "agent": "claude-code",
      "persona": "research-assistant"
    },
    "finalReport": {
      "agent": "claude-code",
      "persona": "technical-writer"
    }
  }
}
```

### 14.7 REST APIs for Extension Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/extensions/personas` | List all loaded personas |
| `GET` | `/api/v1/extensions/personas/{name}` | Get persona detail (resolved with capabilities) |
| `POST` | `/api/v1/extensions/personas` | Register a new persona (YAML body) |
| `PUT` | `/api/v1/extensions/personas/{name}` | Update a persona |
| `DELETE` | `/api/v1/extensions/personas/{name}` | Remove a persona |
| `GET` | `/api/v1/extensions/capabilities` | List all capabilities |
| `POST` | `/api/v1/extensions/capabilities` | Register a new capability |
| `GET` | `/api/v1/extensions/agents` | List all agent profiles |
| `POST` | `/api/v1/extensions/agents` | Register a new agent profile |
| `POST` | `/api/v1/extensions/reload` | Hot-reload all extensions from disk |
| `GET` | `/api/v1/extensions/resolve` | Preview: resolve a persona+agent combo (dry-run) |

### 14.8 Extension Loading & Hot-Reload

```python
# Startup sequence:
# 1. Scan defaults/ directory → load built-in extensions
# 2. Scan config/extensions/ directory → load user extensions (overrides built-ins by name)
# 3. Validate all YAML against JSON schemas
# 4. Resolve dependency graph (capabilities referenced by personas)
# 5. Sync gateway skills & MCPs (register but don't attach yet)
# 6. Watch config/extensions/ for changes (optional hot-reload)

# Hot-reload behavior:
# - File created/modified → validate → upsert in registry → re-sync gateway
# - File deleted → remove from registry (active sessions unaffected)
# - Invalid YAML → log error, skip (do not break running extensions)
# - Circular dependencies → log error, skip affected extensions
```

### 14.9 Extension Package as Reusable Module

The `extensions/` package is designed to be imported independently:

```python
# In any other workflow service:
from extensions import ExtensionRegistry, GatewaySync

registry = ExtensionRegistry(
    defaults_dir="./extensions/defaults",
    user_dir="./config/extensions",
)
registry.load_all()

# Resolve a persona for use
resolved = registry.resolve_persona(
    persona_name="medical-reviewer",
    agent_name="claude-code",
    capability_overrides={"citation-validation": {"maxSourceAge": 3}}
)

# resolved.skill_prompt  → assembled prompt text
# resolved.mcps          → list of MCP configs to attach
# resolved.session_config → mode, model, workingDir defaults

# Sync to gateway
sync = GatewaySync(gateway_http_url="http://localhost:8080")
await sync.register_skill(resolved.skill_name, resolved.skill_prompt, resolved.scope)
for mcp in resolved.mcps:
    await sync.register_mcp(mcp)
```

### 14.10 Built-in Personas (Ship with System)

| Persona | Agent | Use Case |
|---------|-------|----------|
| `research-reviewer` | claude-code | Reviews research reports for quality, accuracy, completeness |
| `domain-expert` | claude-code | Resolves review comments with deep domain knowledge |
| `fact-checker` | claude-code | Verifies factual claims against sources |
| `technical-writer` | claude-code | Generates polished final reports |
| `research-assistant` | claude-code | Answers user questions about the research |
| `web-researcher` | gemini | Performs broad web research on a topic |
| `data-analyst` | gemini | Analyzes data and produces statistical insights |

### 14.11 Updated Directory Structure

```
research-workflow-service/
├── app/                               # FastAPI application (unchanged)
│   ├── agents/
│   │   ├── gateway_client.py
│   │   ├── base.py
│   │   └── ...
│   └── ...
│
├── extensions/                        # ← NEW: Standalone reusable package
│   ├── __init__.py                    # ExtensionRegistry, GatewaySync exports
│   ├── loader.py                      # YAML file discovery and parsing
│   ├── registry.py                    # In-memory registry with CRUD + query
│   ├── models.py                      # Pydantic: Persona, Capability, AgentProfile
│   ├── resolver.py                    # Compose persona + capabilities + agent
│   ├── sync.py                        # Push to CLI Agent Gateway REST/WS
│   ├── hot_reload.py                  # watchdog-based file watcher
│   ├── schemas/
│   │   ├── persona.schema.json
│   │   ├── capability.schema.json
│   │   └── agent_profile.schema.json
│   └── defaults/                      # Built-in extensions
│       ├── personas/
│       ├── capabilities/
│       └── agents/
│
├── config/
│   └── extensions/                    # User-defined extensions
│       ├── personas/
│       ├── capabilities/
│       └── agents/
│
├── pyproject.toml                     # extensions as optional dependency group
└── ...
```
