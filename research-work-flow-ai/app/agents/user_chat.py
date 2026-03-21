"""User chat agent — handles user feedback during review phase."""

from __future__ import annotations

from typing import Any, AsyncGenerator

import structlog

from app.agents.base import AgentRole
from app.agents.gateway_client import GatewayClient
from app.agents.workspace import WorkspaceManager
from app.config import settings
from app.streaming.event_bus import EventBus
from app.streaming.events import AgentStreamDeltaEvent, AgentStreamStartEvent, AgentStreamEndEvent

logger = structlog.get_logger(__name__)


class UserChatAgent(AgentRole):
    """User chat agent — maintains ongoing conversation during USER_REVIEW state."""

    @property
    def role_name(self) -> str:
        return "user-chat"

    @property
    def agent_flow(self) -> str:
        return "claude-code"

    async def send_message(
        self,
        workflow_id: str,
        message: str,
        gateway: GatewayClient,
        event_bus: EventBus,
        workspace: WorkspaceManager,
    ) -> AsyncGenerator[str, None]:
        """Send a message to the user chat agent and stream the response.

        Maintains the same session across multiple calls (stateful conversation).

        Args:
            workflow_id: The workflow ID.
            message: User message text.
            gateway: The gateway client.
            event_bus: Event bus for publishing events.
            workspace: Workspace manager.

        Yields:
            Content chunks as they arrive.

        Raises:
            Exception: If streaming fails.
        """
        session_id = self._build_session_id(workflow_id)

        logger.info(
            "user_chat.send_message.start",
            workflow_id=workflow_id,
            session_id=session_id,
            message_length=len(message),
        )

        # Ensure session exists (will reuse if it already does)
        await self._ensure_session(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            working_dir=settings.gateway_agent_work_dir,
        )

        # Save user message to conversation log
        await workspace.save_conversation_log(
            workflow_id,
            "user",
            {
                "role": "user",
                "content": message,
                "timestamp": str(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
            },
        )

        # Publish stream start
        await event_bus.publish(
            workflow_id,
            AgentStreamStartEvent(
                workflow_id=workflow_id,
                role=self.role_name,
                agent=self.agent_flow,
                session_id=session_id,
            ),
        )

        full_response = ""

        try:
            # Stream the response
            async for event in gateway.send_prompt(
                session_id=session_id,
                flow=self.agent_flow,
                content=message,
            ):
                event_type = event.get("type", "")
                payload = event.get("payload", {})

                # Collect and yield stream deltas
                if event_type == "stream.delta":
                    content = payload.get("delta", "")
                    full_response += content

                    # Publish delta event
                    await event_bus.publish(
                        workflow_id,
                        AgentStreamDeltaEvent(
                            workflow_id=workflow_id,
                            role=self.role_name,
                            content_type="text",
                            content=content,
                        ),
                    )

                    yield content

            # Publish stream end
            await event_bus.publish(
                workflow_id,
                AgentStreamEndEvent(
                    workflow_id=workflow_id,
                    role=self.role_name,
                    finish_reason="stop",
                ),
            )

            # Save assistant response to conversation log
            await workspace.save_conversation_log(
                workflow_id,
                "assistant",
                {
                    "role": "assistant",
                    "content": full_response,
                    "timestamp": str(__import__("datetime").datetime.now(__import__("datetime").timezone.utc)),
                },
            )

            logger.info(
                "user_chat.send_message.complete",
                workflow_id=workflow_id,
                session_id=session_id,
                response_length=len(full_response),
            )

        except Exception as e:
            logger.exception(
                "user_chat.send_message.error",
                workflow_id=workflow_id,
                session_id=session_id,
                error=str(e),
            )
            await event_bus.publish(
                workflow_id,
                AgentStreamEndEvent(
                    workflow_id=workflow_id,
                    role=self.role_name,
                    finish_reason="error",
                ),
            )
            raise

    async def execute(
        self,
        workflow_id: str,
        context: dict[str, Any],
        gateway: GatewayClient,
        event_bus: EventBus,
        workspace: WorkspaceManager,
    ) -> dict[str, Any]:
        """Not used for UserChatAgent — use send_message directly.

        Args:
            workflow_id: The workflow ID.
            context: Context dict.
            gateway: The gateway client.
            event_bus: Event bus.
            workspace: Workspace manager.

        Raises:
            NotImplementedError: This agent uses send_message instead.
        """
        raise NotImplementedError("Use send_message() instead of execute()")
