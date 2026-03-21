# Integration Examples

This guide shows how to integrate the Gateway Client and Event Bus modules into the orchestrator and API layers.

## 1. Startup/Shutdown in Main Application

```python
# app/main.py
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.gateway_client import GatewayClient
from app.config import settings
from app.streaming.event_bus import get_event_bus

# Global gateway client
gateway_client: GatewayClient | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle: startup and shutdown."""
    global gateway_client

    # Startup
    gateway_client = GatewayClient(
        ws_url=settings.gateway_ws_url,
        http_url=settings.gateway_http_url,
        reconnect_max_attempts=settings.gateway_reconnect_max_attempts,
        reconnect_base_delay=settings.gateway_reconnect_base_delay,
    )

    try:
        await gateway_client.connect()
        logger.info("Gateway client connected")
    except Exception as e:
        logger.error(f"Failed to connect to gateway: {e}")
        raise

    yield

    # Shutdown
    if gateway_client:
        await gateway_client.cleanup()
        logger.info("Gateway client cleaned up")


app = FastAPI(
    title="Research Workflow Service",
    lifespan=lifespan,
)


def get_gateway() -> GatewayClient:
    """Dependency for routes that need the gateway client."""
    if gateway_client is None:
        raise RuntimeError("Gateway client not initialized")
    return gateway_client
```

## 2. Orchestrator Integration

```python
# app/orchestration/orchestrator.py
import asyncio
from datetime import datetime, timezone

from app.agents.gateway_client import GatewayClient
from app.streaming.event_bus import get_event_bus
from app.streaming.events import (
    AgentStreamDeltaEvent,
    AgentStreamEndEvent,
    AgentStreamStartEvent,
    AgentStatusEvent,
    WorkflowStateChangedEvent,
)


class ResearchOrchestrator:
    """Orchestrates multi-agent research workflow."""

    def __init__(self, gateway: GatewayClient):
        self.gateway = gateway
        self.bus = get_event_bus()

    async def research_phase(
        self,
        workflow_id: str,
        research_request: str,
        researcher_agent: str = "gemini",
        researcher_model: str = "gemini-2.0-pro",
    ) -> str:
        """
        Execute the research phase: agent researches the topic.

        Returns:
            The research output text.
        """
        # Create session
        session_id = f"sess-{workflow_id}-researcher"
        await self.gateway.create_session(
            session_id=session_id,
            flow=researcher_agent,
            model=researcher_model,
            working_dir=f"/workspace/research/{workflow_id}",
        )

        # Emit state change
        await self.bus.publish(
            workflow_id,
            WorkflowStateChangedEvent(
                workflow_id=workflow_id,
                from_state="INITIATED",
                to_state="RESEARCHING",
                trigger="auto",
            ),
        )

        # Stream research output
        research_text = []
        try:
            async for event in self.gateway.send_prompt(
                session_id=session_id,
                flow=researcher_agent,
                content=research_request,
            ):
                msg_type = event["type"]
                payload = event["payload"]

                if msg_type == "stream.start":
                    await self.bus.publish(
                        workflow_id,
                        AgentStreamStartEvent(
                            workflow_id=workflow_id,
                            role="researcher",
                            agent=researcher_agent,
                            session_id=session_id,
                        ),
                    )

                elif msg_type == "stream.delta":
                    text = payload.get("text", "")
                    research_text.append(text)

                    await self.bus.publish(
                        workflow_id,
                        AgentStreamDeltaEvent(
                            workflow_id=workflow_id,
                            role="researcher",
                            content_type="text",
                            content=text,
                        ),
                    )

                elif msg_type == "agent.status":
                    status = payload.get("status", "idle")
                    await self.bus.publish(
                        workflow_id,
                        AgentStatusEvent(
                            workflow_id=workflow_id,
                            role="researcher",
                            status=status,
                            details=payload.get("details", ""),
                        ),
                    )

                elif msg_type == "tool.use.start":
                    # Could emit tool use event if desired
                    pass

                elif msg_type == "stream.end":
                    await self.bus.publish(
                        workflow_id,
                        AgentStreamEndEvent(
                            workflow_id=workflow_id,
                            role="researcher",
                            finish_reason=payload.get("finishReason", "stop"),
                        ),
                    )

        finally:
            await self.gateway.end_session(session_id, researcher_agent)

        return "".join(research_text)

    async def review_phase(
        self,
        workflow_id: str,
        research_output: str,
        reviewer_agent: str = "claude-code",
        reviewer_model: str = "claude-sonnet-4-6",
    ) -> tuple[list[str], bool]:
        """
        Execute the review phase: another agent reviews research.

        Returns:
            (list of comments, whether consensus was reached)
        """
        # Similar structure to research_phase
        # Create session, emit state change, stream output, publish events

        session_id = f"sess-{workflow_id}-reviewer"
        await self.gateway.create_session(
            session_id=session_id,
            flow=reviewer_agent,
            model=reviewer_model,
        )

        await self.bus.publish(
            workflow_id,
            WorkflowStateChangedEvent(
                workflow_id=workflow_id,
                from_state="RESEARCH_COMPLETE",
                to_state="REVIEWING",
                trigger="auto",
            ),
        )

        prompt = f"""Review the following research:

{research_output}

Provide critical feedback and identify any gaps or issues."""

        review_text = []
        async for event in self.gateway.send_prompt(
            session_id=session_id,
            flow=reviewer_agent,
            content=prompt,
        ):
            # Process similar to research phase
            if event["type"] == "stream.delta":
                text = event["payload"].get("text", "")
                review_text.append(text)
                # Emit to bus...

        await self.gateway.end_session(session_id, reviewer_agent)

        # Parse review to extract comments
        comments = ["Issue 1: ...", "Issue 2: ..."]
        consensus = len(comments) == 0  # Simplified

        return comments, consensus
```

## 3. API Routes for Event Subscription (Server-Sent Events)

```python
# app/api/workflows.py
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.main import get_gateway
from app.streaming.event_bus import get_event_bus
from app.streaming.events import serialize_event

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("/{workflow_id}/stream")
async def stream_workflow_events(workflow_id: str) -> StreamingResponse:
    """
    Server-Sent Events endpoint for real-time workflow updates.

    Clients subscribe with:
    ```
    const eventSource = new EventSource(`/api/workflows/${id}/stream`);
    eventSource.onmessage = (e) => {
        const event = JSON.parse(e.data);
        // Handle event
    };
    ```
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        bus = get_event_bus()

        async for event in bus.subscribe(workflow_id):
            # Serialize to JSON
            data = serialize_event(event)
            # Format as SSE
            yield f"data: {json.dumps(data)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
    )


@router.post("/{workflow_id}/approve-tool")
async def approve_tool(
    workflow_id: str,
    session_id: str,
    flow: str,
    tool_use_id: str,
    gateway: GatewayClient = Depends(get_gateway),
) -> dict:
    """Approve a tool use request from the agent."""

    await gateway.approve_tool_use(
        session_id=session_id,
        flow=flow,
        tool_use_id=tool_use_id,
    )

    # Optionally emit status event to subscribers
    bus = get_event_bus()
    from app.streaming.events import AgentStatusEvent

    await bus.publish(
        workflow_id,
        AgentStatusEvent(
            workflow_id=workflow_id,
            role="researcher",
            status="idle",
            details="Tool approved, executing...",
        ),
    )

    return {"status": "approved"}


@router.post("/{workflow_id}/reject-tool")
async def reject_tool(
    workflow_id: str,
    session_id: str,
    flow: str,
    tool_use_id: str,
    reason: str = "",
    gateway: GatewayClient = Depends(get_gateway),
) -> dict:
    """Reject a tool use request."""

    await gateway.reject_tool_use(
        session_id=session_id,
        flow=flow,
        tool_use_id=tool_use_id,
        reason=reason,
    )

    return {"status": "rejected"}
```

## 4. WebSocket Alternative for Event Subscription

```python
# app/api/websocket.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/workflows/{workflow_id}")
async def websocket_workflow_events(websocket: WebSocket, workflow_id: str):
    """WebSocket endpoint for real-time workflow updates."""

    await websocket.accept()
    bus = get_event_bus()

    try:
        async for event in bus.subscribe(workflow_id):
            # Serialize and send
            data = serialize_event(event)
            await websocket.send_json(data)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception(f"WebSocket error for {workflow_id}: {e}")
        await websocket.close(code=1011, reason="Internal error")
```

## 5. Error Handling and Retry Logic

```python
# app/agents/retry_strategy.py
import asyncio
from typing import TypeVar, Callable, Any

logger = structlog.get_logger(__name__)

T = TypeVar("T")


async def with_retry(
    func: Callable[..., T],
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    **kwargs,
) -> T:
    """
    Execute an async function with exponential backoff retry.

    Args:
        func: Async function to call
        max_attempts: Maximum number of attempts
        base_delay: Initial delay between retries (seconds)
        *args, **kwargs: Arguments to pass to func

    Returns:
        Result of func

    Raises:
        The last exception if all attempts fail
    """
    last_error = None

    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "retry.attempt",
                    func=func.__name__,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "retry.exhausted",
                    func=func.__name__,
                    max_attempts=max_attempts,
                    error=str(e),
                )

    raise last_error


# Usage:
async def research_with_retry(gateway, workflow_id, prompt):
    async def do_research():
        return await orchestrator.research_phase(workflow_id, prompt)

    return await with_retry(
        do_research,
        max_attempts=3,
        base_delay=2.0,
    )
```

## 6. Graceful Degradation for Gateway Outage

```python
# app/agents/fallback.py
from app.agents.gateway_client import GatewayConnectionError
from app.streaming.events import WorkflowErrorEvent


async def safe_send_prompt(
    gateway: GatewayClient,
    workflow_id: str,
    session_id: str,
    flow: str,
    prompt: str,
    bus,
):
    """Send prompt with graceful error handling."""

    try:
        async for event in gateway.send_prompt(
            session_id=session_id,
            flow=flow,
            content=prompt,
        ):
            yield event

    except GatewayConnectionError as e:
        logger.error(f"Gateway connection lost: {e}")

        # Emit error event to UI subscribers
        await bus.publish(
            workflow_id,
            WorkflowErrorEvent(
                workflow_id=workflow_id,
                code="GATEWAY_UNAVAILABLE",
                message="Connection to agent gateway lost",
                recoverable=True,
                details={"error": str(e)},
            ),
        )
        raise

    except asyncio.TimeoutError:
        logger.error("Agent response timed out")

        await bus.publish(
            workflow_id,
            WorkflowErrorEvent(
                workflow_id=workflow_id,
                code="AGENT_TIMEOUT",
                message="Agent did not respond within timeout",
                recoverable=True,
                details={"timeout_seconds": 300},
            ),
        )
        raise
```

## Summary

Key integration points:

1. **Initialization**: Create `GatewayClient` in app lifespan, store as dependency
2. **Orchestrator**: Use `send_prompt()` async generator to stream events
3. **Event Mapping**: Convert gateway events to `WorkflowEvent` subclasses
4. **Publishing**: Emit events via `bus.publish(workflow_id, event)`
5. **API Exposure**: Provide SSE or WebSocket endpoints for client subscription
6. **Error Handling**: Catch `GatewayConnectionError` and `TimeoutError`
7. **Cleanup**: Call `gateway.cleanup()` on shutdown

All provided modules include proper logging via structlog and comprehensive docstrings.
