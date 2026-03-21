# Gateway Client and Event Bus Modules

This document describes the two core communication modules built for the Research Workflow Service: the **Gateway Client** for WebSocket communication with the CLI Agent Gateway, and the **Event Bus** for in-process pub/sub streaming to the UI.

## Architecture Overview

### Gateway Client (`app/agents/gateway_client.py`)

The `GatewayClient` provides a unified async/await interface to the CLI Agent Gateway running on port 8080. It handles:

- **WebSocket Connection**: Auto-reconnecting with exponential backoff (configurable max attempts and base delay)
- **Session Management**: Create, resume, and end sessions with agents (Claude Code, Gemini, etc)
- **Prompt Streaming**: Send prompts and yield events as they arrive (non-blocking)
- **Tool Control**: Approve/reject tool use requests
- **REST Integration**: Register and attach skills/MCPs, check agent auth status
- **Message Routing**: Per-session asyncio queues for demultiplexing server responses

### Event Bus (`app/streaming/event_bus.py`)

The `EventBus` is a lightweight, in-process pub/sub system with:

- **Per-Workflow Channels**: Each workflow gets its own set of subscribers
- **Multiple Subscribers**: Multiple browser tabs/UI instances can listen to the same workflow
- **Non-Blocking Publish**: Events are dropped with a warning if a queue is full
- **Auto-Cleanup**: Subscribers are unregistered when generators close
- **Singleton Pattern**: Global instance via `get_event_bus()`

### Event Models (`app/streaming/events.py`)

Pydantic models for all event types the UI can receive:

- `WorkflowStateChangedEvent` — State transitions with trigger and metadata
- `AgentStreamStartEvent` — Agent begins output
- `AgentStreamDeltaEvent` — Content chunks (text, markdown, code, JSON)
- `AgentStreamEndEvent` — Agent stream complete (with finish reason)
- `AgentStatusEvent` — Agent status (thinking, tool_use, idle, error)
- `AgentToolUseEvent` — Tool invocation details
- `ReviewCommentsEvent` — Reviewer feedback and consensus
- `ResolutionMergedEvent` — Resolver output incorporated
- `ReportUpdatedEvent` — Report artifact updated
- `UserChatResponseEvent` — User feedback/approval
- `WorkflowCompletedEvent` — Successful completion
- `WorkflowErrorEvent` — Error with recovery flag

All events have:
- `type` — discriminator for routing
- `workflow_id` — which workflow
- `timestamp` — RFC 3339 UTC time

## Usage Examples

### Basic Setup

```python
from app.agents.gateway_client import GatewayClient
from app.streaming.event_bus import get_event_bus

# Create client
gateway = GatewayClient(
    ws_url="ws://localhost:8080/ws",
    http_url="http://localhost:8080",
    reconnect_max_attempts=10,
    reconnect_base_delay=2.0,
)

# Connect
await gateway.connect()

# Get event bus
bus = get_event_bus()
```

### Sending a Prompt with Streaming

```python
import asyncio

async def research_with_streaming(workflow_id: str, prompt: str):
    """Send a prompt and stream events to the UI event bus."""

    # Create session
    session_id = f"sess-{workflow_id}"
    await gateway.create_session(
        session_id=session_id,
        flow="gemini",  # or "claude-code"
        model="gemini-2.0-pro",
        working_dir="/workspace/research",
    )

    # Send prompt and stream events
    async for event in gateway.send_prompt(
        session_id=session_id,
        flow="gemini",
        content=prompt,
    ):
        # Each event is a dict: {"type": "...", "payload": {...}}
        msg_type = event["type"]
        payload = event["payload"]

        # Emit to UI event bus
        if msg_type == "stream.delta":
            # Create event model
            ui_event = AgentStreamDeltaEvent(
                workflow_id=workflow_id,
                role="researcher",
                content=payload.get("text", ""),
            )
            await bus.publish(workflow_id, ui_event)

        elif msg_type == "agent.status":
            status = payload.get("status")
            ui_event = AgentStatusEvent(
                workflow_id=workflow_id,
                role="researcher",
                status=status,
            )
            await bus.publish(workflow_id, ui_event)

        elif msg_type == "stream.end":
            ui_event = AgentStreamEndEvent(
                workflow_id=workflow_id,
                role="researcher",
                finish_reason=payload.get("finishReason", "stop"),
            )
            await bus.publish(workflow_id, ui_event)

    # Clean up
    await gateway.end_session(session_id, "gemini")
```

### Broadcasting to UI Subscribers

```python
async def broadcast_workflow_event(workflow_id: str, from_state: str, to_state: str):
    """Publish a state change to all UI subscribers."""

    event = WorkflowStateChangedEvent(
        workflow_id=workflow_id,
        from_state=from_state,
        to_state=to_state,
        trigger="auto",
    )

    bus = get_event_bus()
    await bus.publish(workflow_id, event)
```

### Subscribing from API Route (FastAPI)

```python
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import json

router = APIRouter()

@router.get("/api/workflows/{workflow_id}/stream")
async def stream_workflow_events(workflow_id: str):
    """SSE endpoint for UI to subscribe to workflow events."""

    bus = get_event_bus()

    async def event_generator():
        async for event in bus.subscribe(workflow_id):
            # Serialize event to JSON
            data = serialize_event(event)
            yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )
```

### Handling Tool Approvals

```python
async def handle_tool_approval(workflow_id: str, session_id: str, flow: str, tool_use_id: str):
    """Approve a tool use request."""

    await gateway.approve_tool_use(
        session_id=session_id,
        flow=flow,
        tool_use_id=tool_use_id,
    )

    # Emit to UI
    event = AgentStatusEvent(
        workflow_id=workflow_id,
        role="researcher",
        status="idle",
        details="Tool approved and executing",
    )
    bus = get_event_bus()
    await bus.publish(workflow_id, event)
```

## Gateway Envelope Protocol

All WebSocket messages follow this structure:

```json
{
  "id": "uuid",
  "type": "message-type",
  "sessionId": "sess-123",
  "flow": "claude-code|gemini",
  "timestamp": "2026-03-21T10:30:00Z",
  "payload": { /* message-specific data */ },
  "replyTo": "uuid" /* optional, for responses */
}
```

### Client → Server Messages

| Type | Payload | Meaning |
|------|---------|---------|
| `session.create` | `{workingDir, model, ...}` | Create new session |
| `session.resume` | `{sessionId}` | Resume existing session |
| `session.end` | `{}` | End session |
| `prompt.send` | `{content, attachments, options}` | Send prompt and start streaming |
| `prompt.cancel` | `{}` | Cancel in-flight prompt |
| `tool.approve` | `{toolUseId}` | Approve tool use |
| `tool.reject` | `{toolUseId, reason}` | Reject tool use |

### Server → Client Messages

| Type | Payload | Meaning |
|------|---------|---------|
| `session.created` | `{sessionId, agentInfo}` | Session created |
| `stream.start` | `{role, model}` | Streaming began |
| `stream.delta` | `{text}` | Content chunk |
| `stream.end` | `{finishReason}` | Streaming complete |
| `agent.status` | `{status, details}` | Status change (thinking, tool_use, idle) |
| `tool.use.start` | `{toolUseId, toolName, input}` | Tool invocation started |
| `tool.use.result` | `{toolUseId, result}` | Tool completed |
| `error` | `{code, message}` | Error occurred |

## Configuration

Gateway client parameters via environment variables (loaded in `app/config.py`):

```bash
RESEARCH_GATEWAY_WS_URL=ws://localhost:8080/ws
RESEARCH_GATEWAY_HTTP_URL=http://localhost:8080
RESEARCH_GATEWAY_RECONNECT_MAX_ATTEMPTS=10
RESEARCH_GATEWAY_RECONNECT_BASE_DELAY=2.0
```

## Error Handling

### Connection Errors

```python
from app.agents.gateway_client import GatewayConnectionError

try:
    await gateway.send_prompt(...)
except GatewayConnectionError as e:
    logger.error(f"Gateway error: {e}")
    # Retry or fail gracefully
```

### Event Bus Overflows

Event bus logs warnings when queues are full and drops events. This is intentional — real-time event streams should not block the producer. The UI will simply miss some intermediate events but will see the final state.

### Timeout Handling

- Prompt streaming: 5-minute timeout
- Session creation: 10-second timeout
- HTTP requests: 30-second timeout

Timeouts raise `asyncio.TimeoutError` which should be caught and handled.

## Testing

Run tests with:

```bash
pytest tests/test_gateway_and_events.py -v
```

Key test coverage:

- Event model serialization
- EventBus subscribe/publish with multiple subscribers
- Queue full handling
- Auto-unsubscribe on generator close
- GatewayClient message envelope structure
- Singleton pattern for event bus

## Integration Checklist

- [ ] Gateway running on port 8080
- [ ] Environment variables configured
- [ ] FastAPI app imports and instantiates `GatewayClient`
- [ ] Orchestrator calls `gateway.connect()` on startup
- [ ] Orchestrator calls `gateway.cleanup()` on shutdown
- [ ] All agent prompt operations use `send_prompt()` async generator
- [ ] Events mapped from gateway payloads to `WorkflowEvent` subclasses
- [ ] Events published to `bus.publish(workflow_id, event)`
- [ ] API routes provide event subscription (SSE or WebSocket)
- [ ] Tests pass: `pytest tests/test_gateway_and_events.py`

## Files

- `app/agents/__init__.py` — Package init
- `app/agents/gateway_client.py` — WebSocket client (700+ lines)
- `app/streaming/__init__.py` — Package init
- `app/streaming/event_bus.py` — In-process pub/sub (250+ lines)
- `app/streaming/events.py` — Event models (300+ lines)
- `tests/test_gateway_and_events.py` — Comprehensive tests (450+ lines)

Total: ~1700 lines of production code plus tests.
