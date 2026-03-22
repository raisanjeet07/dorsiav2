"""Base agent role interface with common patterns."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import structlog

from app.agents.gateway_client import GatewayClient
from app.agents.workspace import WorkspaceManager
from app.config import settings
from app.streaming.event_bus import EventBus
from app.streaming.events import (
    AgentSessionLifecycleEvent,
    AgentStreamDeltaEvent,
    AgentStreamEndEvent,
    AgentStreamStartEvent,
)

logger = structlog.get_logger(__name__)


def session_payload_process_id(payload: dict[str, Any]) -> int | None:
    """Best-effort parse of agent subprocess PID from gateway session.created payload."""
    v = payload.get("processId") if isinstance(payload, dict) else None
    if v is None and isinstance(payload, dict):
        v = payload.get("pid")
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    return None


class AgentRole(ABC):
    """Abstract base class for agent roles in the workflow."""

    @property
    @abstractmethod
    def role_name(self) -> str:
        """Name of this role (e.g., 'researcher', 'reviewer')."""
        pass

    @property
    @abstractmethod
    def agent_flow(self) -> str:
        """Agent flow type (e.g., 'claude-code', 'gemini')."""
        pass

    @property
    def session_id_pattern(self) -> str:
        """Pattern for generating session IDs. Override if needed."""
        return f"{{workflow_id}}-{self.role_name}"

    def _build_session_id(self, workflow_id: str) -> str:
        """Build a session ID for this role.

        Args:
            workflow_id: The workflow ID.

        Returns:
            Session ID string.
        """
        return self.session_id_pattern.format(workflow_id=workflow_id)

    async def _ensure_session(
        self,
        gateway: GatewayClient,
        session_id: str,
        flow: str,
        working_dir: str | None = None,
        model: str | None = None,
        skills: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ensure a session exists with the gateway.

        Creates the session if needed, then optionally attaches skills.

        Args:
            gateway: The gateway client.
            session_id: Session ID.
            flow: Agent flow.
            working_dir: Optional working directory.
            model: Optional model name.
            skills: Optional list of skill names to attach.

        Returns:
            ``session.created`` payload from the gateway (may be empty on error).

        Raises:
            Exception: If session creation fails.
        """
        payload: dict[str, Any] = {}
        try:
            session_config: dict[str, bool] = {}
            if flow == "claude-code" and settings.gateway_claude_disable_resume:
                session_config["claudeDisableResume"] = True
            payload = await gateway.create_session(
                session_id=session_id,
                flow=flow,
                working_dir=working_dir,
                model=model,
                config=session_config if session_config else None,
            )
            logger.info(
                "session.created",
                session_id=session_id,
                flow=flow,
                role=self.role_name,
            )
        except Exception as e:
            logger.warning(
                "session.create_failed",
                session_id=session_id,
                flow=flow,
                role=self.role_name,
                error=str(e),
            )
            # Session might already exist; continue

        # Attach skills if provided
        if skills:
            for skill_name in skills:
                try:
                    await gateway.attach_skill(session_id, skill_name)
                    logger.debug(
                        "skill.attached",
                        session_id=session_id,
                        skill=skill_name,
                    )
                except Exception as e:
                    logger.warning(
                        "skill.attach_failed",
                        session_id=session_id,
                        skill=skill_name,
                        error=str(e),
                    )

        return payload

    async def _emit_agent_session_active(
        self,
        event_bus: EventBus,
        workflow_id: str,
        session_id: str,
        flow: str,
        workspace_dir: str,
        display_role: str,
        process_id: int | None = None,
    ) -> None:
        """Notify UI that a gateway session is active for this workflow phase."""
        await event_bus.publish(
            workflow_id,
            AgentSessionLifecycleEvent(
                workflow_id=workflow_id,
                role=display_role,
                session_id=session_id,
                flow=flow,
                workspace_dir=workspace_dir,
                process_id=process_id,
                status="active",
            ),
        )

    async def _stream_and_collect(
        self,
        gateway: GatewayClient,
        session_id: str,
        flow: str,
        prompt: str,
        event_bus: EventBus,
        workflow_id: str,
        role: str,
        attachments: list[dict[str, str]] | None = None,
    ) -> str:
        """Send prompt, iterate stream events, publish to event bus, and collect full response.

        Args:
            gateway: The gateway client.
            session_id: Session ID.
            flow: Agent flow.
            prompt: The prompt text.
            event_bus: Event bus for publishing events.
            workflow_id: Workflow ID for event publishing.
            role: Role name for event publishing.
            attachments: Optional attachments.

        Returns:
            Full collected response text.

        Raises:
            Exception: If streaming fails.
        """
        full_response = ""

        # Publish stream start
        await event_bus.publish(
            workflow_id,
            AgentStreamStartEvent(
                workflow_id=workflow_id,
                role=role,
                agent=flow,
                session_id=session_id,
            ),
        )

        try:
            async for event in gateway.send_prompt(
                session_id=session_id,
                flow=flow,
                content=prompt,
                attachments=attachments,
            ):
                event_type = event.get("type", "")
                payload = event.get("payload", {})

                if event_type == "error":
                    err = payload if payload else event.get("error", {})
                    err_msg = err.get("message", str(err))
                    raise RuntimeError(f"Agent error: {err_msg}")

                # Collect stream deltas
                if event_type == "stream.delta":
                    content = payload.get("content", "")
                    full_response += content

                    # Publish delta event
                    await event_bus.publish(
                        workflow_id,
                        AgentStreamDeltaEvent(
                            workflow_id=workflow_id,
                            role=role,
                            content_type="text",
                            content=content,
                        ),
                    )

            # Publish stream end
            await event_bus.publish(
                workflow_id,
                AgentStreamEndEvent(
                    workflow_id=workflow_id,
                    role=role,
                    finish_reason="stop",
                ),
            )

            logger.info(
                "stream_and_collect.complete",
                session_id=session_id,
                role=role,
                response_length=len(full_response),
            )

        except Exception as e:
            logger.exception(
                "stream_and_collect.error",
                session_id=session_id,
                role=role,
                error=str(e),
            )
            await event_bus.publish(
                workflow_id,
                AgentStreamEndEvent(
                    workflow_id=workflow_id,
                    role=role,
                    finish_reason="error",
                ),
            )
            raise

        return full_response

    @abstractmethod
    async def execute(
        self,
        workflow_id: str,
        context: dict[str, Any],
        gateway: GatewayClient,
        event_bus: EventBus,
        workspace: WorkspaceManager,
    ) -> dict[str, Any]:
        """Execute the agent for this role.

        This method should:
        1. Build the appropriate prompt
        2. Ensure a session exists with the gateway
        3. Use _stream_and_collect to send the prompt and gather response
        4. Parse the response
        5. Save artifacts to workspace
        6. Return a dict with the result

        Args:
            workflow_id: The workflow ID.
            context: Context dict with workflow inputs/state.
            gateway: The gateway client.
            event_bus: Event bus for publishing events.
            workspace: Workspace manager for saving files.

        Returns:
            Result dict specific to the agent role.

        Raises:
            Exception: If agent execution fails.
        """
        pass
