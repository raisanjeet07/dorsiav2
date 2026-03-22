"""Event type definitions for the workflow event bus.

All events are Pydantic models with a type discriminator for easy serialization
and routing through the event bus.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """All possible event types the UI can receive."""

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
    AGENT_SESSION = "agent.session"


class WorkflowEvent(BaseModel):
    """Base event model with required fields for all workflow events."""

    type: str = Field(..., description="Event type discriminator")
    workflow_id: str = Field(..., description="Workflow this event belongs to")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowStateChangedEvent(WorkflowEvent):
    """Workflow state transition event."""

    type: Literal[EventType.WORKFLOW_STATE_CHANGED] = EventType.WORKFLOW_STATE_CHANGED
    from_state: str = Field(..., description="Previous state")
    to_state: str = Field(..., description="New state")
    trigger: str = Field(..., description="What caused the transition")
    review_cycle: int = Field(default=0, description="Current review cycle number")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional transition metadata")


class AgentStreamStartEvent(WorkflowEvent):
    """Agent started streaming output."""

    type: Literal[EventType.AGENT_STREAM_START] = EventType.AGENT_STREAM_START
    role: str = Field(..., description="Agent role (researcher, reviewer, resolver)")
    agent: str = Field(..., description="Agent name (claude-code, gemini)")
    session_id: str = Field(..., description="Gateway session ID")


class AgentSessionLifecycleEvent(WorkflowEvent):
    """Gateway agent session started or ended (process lifecycle for UI)."""

    type: Literal[EventType.AGENT_SESSION] = EventType.AGENT_SESSION
    role: str = Field(..., description="Logical role (researcher, reviewer, resolver-gemini, ...)")
    session_id: str = Field(..., description="Gateway session ID")
    flow: str = Field(..., description="Gateway flow / agent type (e.g. gemini, claude-code)")
    workspace_dir: str = Field(
        default="",
        description="Agent working directory on the gateway host (or workspace-file-service path)",
    )
    process_id: int | None = Field(
        default=None,
        description="OS PID of the agent subprocess when known (gateway may omit)",
    )
    status: Literal["active", "ended"] = Field(..., description="Whether the session is running or was closed")


class AgentStreamDeltaEvent(WorkflowEvent):
    """Streamed content chunk from agent."""

    type: Literal[EventType.AGENT_STREAM_DELTA] = EventType.AGENT_STREAM_DELTA
    role: str = Field(..., description="Agent role")
    content_type: Literal["text", "markdown", "code", "json"] = Field(
        default="text", description="Type of content being streamed"
    )
    content: str = Field(..., description="The content chunk")


class AgentStreamEndEvent(WorkflowEvent):
    """Agent finished streaming output."""

    type: Literal[EventType.AGENT_STREAM_END] = EventType.AGENT_STREAM_END
    role: str = Field(..., description="Agent role")
    finish_reason: Literal["stop", "length", "error", "tool_use", "cancelled"] = Field(
        ..., description="Why the stream ended"
    )


class AgentStatusEvent(WorkflowEvent):
    """Agent status changed (thinking, tool use, idle, etc)."""

    type: Literal[EventType.AGENT_STATUS] = EventType.AGENT_STATUS
    role: str = Field(..., description="Agent role")
    status: Literal["thinking", "tool_use", "idle", "error"] = Field(..., description="Current agent status")
    details: str = Field(default="", description="Status details (e.g. 'Using search tool')")


class AgentToolUseEvent(WorkflowEvent):
    """Agent invoked a tool."""

    type: Literal[EventType.AGENT_TOOL_USE] = EventType.AGENT_TOOL_USE
    role: str = Field(..., description="Agent role")
    tool_name: str = Field(..., description="Name of the tool being used")
    input: dict[str, Any] = Field(..., description="Tool input parameters")
    tool_use_id: str | None = Field(default=None, description="Unique ID for this tool use")


class ReviewCommentsEvent(WorkflowEvent):
    """Review cycle feedback from reviewer agent."""

    type: Literal[EventType.REVIEW_COMMENTS] = EventType.REVIEW_COMMENTS
    cycle: int = Field(..., description="Review cycle number")
    comments: list[str] = Field(..., description="List of review comments/issues")
    consensus: bool = Field(..., description="Whether reviewer consensus was reached")
    agent: str = Field(..., description="Which agent provided review")


class ResolutionMergedEvent(WorkflowEvent):
    """Resolver agent output has been incorporated."""

    type: Literal[EventType.RESOLUTION_MERGED] = EventType.RESOLUTION_MERGED
    cycle: int = Field(..., description="Resolution cycle number")
    resolutions: list[str] = Field(..., description="List of issues that were resolved")


class ReportUpdatedEvent(WorkflowEvent):
    """Generated report artifact was updated."""

    type: Literal[EventType.REPORT_UPDATED] = EventType.REPORT_UPDATED
    version: int = Field(..., description="Report version number")
    path: str = Field(..., description="File path to the report")
    format: Literal["markdown", "html", "pdf"] = Field(default="markdown", description="Report format")


class UserChatResponseEvent(WorkflowEvent):
    """User provided feedback or approval via chat."""

    type: Literal[EventType.USER_CHAT_RESPONSE] = EventType.USER_CHAT_RESPONSE
    content: str = Field(..., description="User's response text")
    streaming: bool = Field(default=False, description="Whether this is a streaming response")


class WorkflowCompletedEvent(WorkflowEvent):
    """Workflow execution finished successfully."""

    type: Literal[EventType.WORKFLOW_COMPLETED] = EventType.WORKFLOW_COMPLETED
    final_report_path: str = Field(..., description="Path to final report file")
    summary: str = Field(..., description="Executive summary of findings")


class WorkflowErrorEvent(WorkflowEvent):
    """Error occurred during workflow execution."""

    type: Literal[EventType.WORKFLOW_ERROR] = EventType.WORKFLOW_ERROR
    code: str = Field(..., description="Error code for categorization")
    message: str = Field(..., description="Human-readable error message")
    recoverable: bool = Field(..., description="Whether the workflow can recover from this error")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional error context")


def serialize_event(event: WorkflowEvent) -> dict[str, Any]:
    """Convert a WorkflowEvent to a serializable dictionary.

    Handles datetime serialization and preserves the event type discriminator.
    """
    data = event.model_dump(mode="json")
    # Ensure timestamp is ISO 8601 string
    if isinstance(data.get("timestamp"), str):
        pass  # Already serialized
    else:
        data["timestamp"] = event.timestamp.isoformat()
    return data
