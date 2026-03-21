# API Reference: Gateway Client and Event Bus

Complete reference for all public APIs in the gateway client and event bus modules.

## GatewayClient (`app.agents.gateway_client`)

### Class: `GatewayClient`

#### Constructor

```python
GatewayClient(
    ws_url: str,
    http_url: str,
    reconnect_max_attempts: int = 10,
    reconnect_base_delay: float = 2.0
)
```

**Parameters:**
- `ws_url`: WebSocket URL (e.g., `ws://localhost:8080/ws`)
- `http_url`: HTTP base URL (e.g., `http://localhost:8080`)
- `reconnect_max_attempts`: Max reconnection attempts before failure
- `reconnect_base_delay`: Initial delay (seconds) for exponential backoff

#### Connection Methods

```python
async def connect() -> None
```
Opens WebSocket connection with exponential backoff retry. Raises `GatewayConnectionError` if max attempts exceeded.

```python
async def disconnect() -> None
```
Closes WebSocket connection and stops read loop.

```python
async def cleanup() -> None
```
Closes HTTP client and cleans up all resources. Call on app shutdown.

#### Message Methods

```python
async def send_message(
    msg_type: str,
    session_id: str,
    flow: str,
    payload: dict[str, Any]
) -> str
```
Send raw envelope message to gateway. Returns message ID.

#### Session Methods

```python
async def create_session(
    session_id: str,
    flow: str,
    working_dir: str | None = None,
    model: str | None = None,
    config: dict[str, Any] | None = None
) -> dict[str, Any]
```
Create new session. Waits for `session.created` response (10-second timeout).

Returns session creation response payload.

```python
async def end_session(session_id: str, flow: str) -> None
```
End a session and cleanup local queue.

#### Prompt Methods

```python
async def send_prompt(
    session_id: str,
    flow: str,
    content: str,
    attachments: list[dict[str, str]] | None = None,
    options: dict[str, Any] | None = None
) -> AsyncGenerator[dict[str, Any], None]
```
Send prompt and stream response events. Async generator yields events with:
```python
{
    "type": "stream.delta",  # or other event types
    "payload": {...},
    "sessionId": "...",
    "timestamp": "..."
}
```

Yields until `stream.end` event. Timeout: 5 minutes.

```python
async def cancel_prompt(session_id: str, flow: str) -> None
```
Cancel in-flight prompt execution.

#### Tool Methods

```python
async def approve_tool_use(
    session_id: str,
    flow: str,
    tool_use_id: str
) -> None
```
Approve a tool use request from the agent.

```python
async def reject_tool_use(
    session_id: str,
    flow: str,
    tool_use_id: str,
    reason: str = ""
) -> None
```
Reject a tool use request. Optional rejection reason.

#### Skill Methods (REST)

```python
async def register_skill(
    name: str,
    prompt: str,
    scope: str = "global",
    description: str = ""
) -> dict[str, Any]
```
Register a skill with the gateway. Returns registration response.

```python
async def attach_skill(session_id: str, skill_name: str) -> dict[str, Any]
```
Attach a skill to a session. Returns attachment response.

#### MCP Methods (REST)

```python
async def register_mcp(
    name: str,
    mcp_config: dict[str, Any]
) -> dict[str, Any]
```
Register an MCP with the gateway. Returns registration response.

```python
async def attach_mcp(session_id: str, mcp_name: str) -> dict[str, Any]
```
Attach an MCP to a session. Returns attachment response.

#### Agent Methods (REST)

```python
async def check_agent_auth(agent_name: str) -> dict[str, Any]
```
Check authentication status of an agent. Returns auth status response.

```python
async def check_health() -> dict[str, Any]
```
Check health of the gateway. Returns health response.

### Exceptions

```python
class GatewayConnectionError(Exception)
```
Raised when connection fails or is not available.

---

## EventBus (`app.streaming.event_bus`)

### Class: `EventBus`

#### Constructor

```python
EventBus(queue_size: int = 1000)
```

**Parameters:**
- `queue_size`: Maximum events per subscriber queue

#### Subscribe Method

```python
async def subscribe(workflow_id: str) -> AsyncGenerator[WorkflowEvent, None]
```
Subscribe to events for a workflow. Async generator that:
- Yields `WorkflowEvent` instances as they're published
- Auto-unsubscribes when generator closes
- Returns unique `subscriber_id` for manual unsubscribe

**Example:**
```python
async for event in bus.subscribe("wf-123"):
    print(f"Got event: {event.type}")
```

#### Publish Method

```python
async def publish(workflow_id: str, event: WorkflowEvent) -> None
```
Publish event to all subscribers of a workflow. Non-blocking:
- If a queue is full, event is dropped with warning
- No exception raised on queue full

#### Unsubscribe Method

```python
async def unsubscribe(workflow_id: str, subscriber_id: str) -> None
```
Manually unsubscribe a specific subscriber. Usually called automatically.

#### Introspection Methods

```python
async def get_subscriber_count(workflow_id: str) -> int
```
Get number of active subscribers for a workflow.

```python
async def get_stats() -> dict[str, int]
```
Get EventBus statistics:
```python
{
    "workflows": 5,  # Number of workflows with subscribers
    "total_subscribers": 12  # Total subscribers across all workflows
}
```

### Module-Level Functions

```python
def get_event_bus() -> EventBus
```
Get or create the global EventBus singleton. Lazily initializes.

```python
def set_event_bus(bus: EventBus) -> None
```
Set the global EventBus singleton. Use for testing.

---

## Events (`app.streaming.events`)

### Base Class: `WorkflowEvent`

All events inherit from this Pydantic model:

```python
class WorkflowEvent(BaseModel):
    type: str  # Event type discriminator
    workflow_id: str  # Which workflow
    timestamp: datetime  # UTC, auto-generated
```

### Event Models

#### `WorkflowStateChangedEvent`
```python
WorkflowStateChangedEvent(
    workflow_id: str,
    from_state: str,
    to_state: str,
    trigger: str,
    review_cycle: int = 0,
    metadata: dict[str, Any] = {}
)
```

#### `AgentStreamStartEvent`
```python
AgentStreamStartEvent(
    workflow_id: str,
    role: str,
    agent: str,
    session_id: str
)
```

#### `AgentStreamDeltaEvent`
```python
AgentStreamDeltaEvent(
    workflow_id: str,
    role: str,
    content_type: Literal["text", "markdown", "code", "json"] = "text",
    content: str
)
```

#### `AgentStreamEndEvent`
```python
AgentStreamEndEvent(
    workflow_id: str,
    role: str,
    finish_reason: Literal["stop", "length", "error", "tool_use", "cancelled"]
)
```

#### `AgentStatusEvent`
```python
AgentStatusEvent(
    workflow_id: str,
    role: str,
    status: Literal["thinking", "tool_use", "idle", "error"],
    details: str = ""
)
```

#### `AgentToolUseEvent`
```python
AgentToolUseEvent(
    workflow_id: str,
    role: str,
    tool_name: str,
    input: dict[str, Any],
    tool_use_id: str | None = None
)
```

#### `ReviewCommentsEvent`
```python
ReviewCommentsEvent(
    workflow_id: str,
    cycle: int,
    comments: list[str],
    consensus: bool,
    agent: str
)
```

#### `ResolutionMergedEvent`
```python
ResolutionMergedEvent(
    workflow_id: str,
    cycle: int,
    resolutions: list[str]
)
```

#### `ReportUpdatedEvent`
```python
ReportUpdatedEvent(
    workflow_id: str,
    version: int,
    path: str,
    format: Literal["markdown", "html", "pdf"] = "markdown"
)
```

#### `UserChatResponseEvent`
```python
UserChatResponseEvent(
    workflow_id: str,
    content: str,
    streaming: bool = False
)
```

#### `WorkflowCompletedEvent`
```python
WorkflowCompletedEvent(
    workflow_id: str,
    final_report_path: str,
    summary: str
)
```

#### `WorkflowErrorEvent`
```python
WorkflowErrorEvent(
    workflow_id: str,
    code: str,
    message: str,
    recoverable: bool,
    details: dict[str, Any] = {}
)
```

### Enums

#### `EventType`
```python
class EventType(str, Enum):
    WORKFLOW_STATE_CHANGED = "workflow.state_changed"
    AGENT_STREAM_START = "agent.stream_start"
    AGENT_STREAM_DELTA = "agent.stream_delta"
    AGENT_STREAM_END = "agent.stream_end"
    AGENT_STATUS = "agent.status"
    AGENT_TOOL_USE = "agent.tool_use"
    REVIEW_COMMENTS = "review.comments"
    RESOLUTION_MERGED = "resolution.merged"
    REPORT_UPDATED = "report.updated"
    USER_CHAT_RESPONSE = "user.chat_response"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_ERROR = "workflow.error"
```

### Utility Functions

```python
def serialize_event(event: WorkflowEvent) -> dict[str, Any]
```
Convert a `WorkflowEvent` to a JSON-serializable dict. Handles datetime serialization.

**Example:**
```python
event = AgentStreamDeltaEvent(...)
data = serialize_event(event)
json_str = json.dumps(data)  # Safe to serialize
```

---

## Configuration

Environment variables (with `RESEARCH_` prefix in `app/config.py`):

```python
gateway_ws_url: str = "ws://localhost:8080/ws"
gateway_http_url: str = "http://localhost:8080"
gateway_reconnect_max_attempts: int = 10
gateway_reconnect_base_delay: float = 2.0
```

Load via `from app.config import settings` and access with `settings.gateway_ws_url`, etc.

---

## Type Hints and Imports

### Importing Gateway Client

```python
from app.agents.gateway_client import GatewayClient, GatewayConnectionError
```

### Importing Event Bus

```python
from app.streaming.event_bus import EventBus, get_event_bus, set_event_bus
```

### Importing Events

```python
from app.streaming.events import (
    WorkflowEvent,
    WorkflowStateChangedEvent,
    AgentStreamStartEvent,
    AgentStreamDeltaEvent,
    AgentStreamEndEvent,
    AgentStatusEvent,
    AgentToolUseEvent,
    ReviewCommentsEvent,
    ResolutionMergedEvent,
    ReportUpdatedEvent,
    UserChatResponseEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    EventType,
    serialize_event,
)
```

### Python Version

All modules require Python 3.11+ and use:
- Type hints with `from __future__ import annotations`
- Match statements (if applicable)
- Async/await patterns
- Pydantic v2 models

---

## Error Handling

### Gateway Errors

```python
from app.agents.gateway_client import GatewayConnectionError

try:
    await gateway.send_prompt(...)
except GatewayConnectionError as e:
    # Handle connection loss
    logger.error(f"Gateway error: {e}")

except asyncio.TimeoutError:
    # Prompt timeout (5 min)
    logger.error("Prompt timed out")
```

### Event Bus Errors

Event bus logs to structlog:
- `publish.queue_full` — Subscriber queue full, event dropped
- `publish.unexpected_error` — Unexpected error during publish
- `_read_loop.invalid_json` — Malformed JSON from gateway
- `_read_loop.no_queue` — No subscriber for session

---

## Logging

All modules use structlog. Key log events:

### Gateway Client
- `gateway_client.initialized` — Client created
- `gateway_client.connected` — WebSocket connected
- `gateway_client.reconnect_attempt` — Retry in progress
- `send_message` — Message sent
- `send_prompt.sent` — Prompt sent
- `send_prompt.complete` — Stream finished
- `create_session.success` — Session created
- `gateway_client.disconnected` — Connection closed

### Event Bus
- `publish.no_subscribers` — No subscribers for workflow
- `publish.queue_full` — Subscriber queue overflow
- `unsubscribe.workflow_cleanup` — Workflow deleted (no more subscribers)

Configure structlog in your app for JSON output or custom formats.

---

## Testing

All components have comprehensive test coverage in `tests/test_gateway_and_events.py`.

Run tests:
```bash
pytest tests/test_gateway_and_events.py -v
pytest tests/test_gateway_and_events.py::TestEventBus -v
pytest tests/test_gateway_and_events.py::TestGatewayClient -v
```

Key test classes:
- `TestEventTypes` — Event model creation and serialization
- `TestEventBus` — Subscribe, publish, cleanup, overflow
- `TestGatewayClient` — Initialization, messages, connection

---

## Version and Compatibility

- **Python**: 3.11+
- **Pydantic**: v2.7.0+
- **websockets**: 12.0+
- **httpx**: 0.27.0+
- **structlog**: 24.2.0+

All dependencies are in `pyproject.toml`.
