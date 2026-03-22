"""User chat agent — handles user feedback during review phase."""

from __future__ import annotations

from typing import Any, AsyncGenerator

import structlog

from app.agents.base import AgentRole, session_payload_process_id
from app.agents.gateway_client import GatewayClient
from app.agents.workspace import WorkspaceManager
from app.config import settings
from app.streaming.event_bus import EventBus
from app.streaming.events import (
    AgentStreamEndEvent,
    AgentStreamStartEvent,
    UserChatResponseEvent,
)

logger = structlog.get_logger(__name__)

# Keep prompts bounded for gateway/CLI limits (report body is inlined).
_MAX_REPORT_CHARS_IN_PROMPT = 100_000
_MAX_USER_MESSAGE_CHARS = 16_000


def _build_report_scoped_prompt(
    workflow_id: str,
    report_version: str,
    report_markdown: str,
    user_message: str,
) -> str:
    """Wrap the user message with report context and strict scope (report-only discussion)."""
    body = report_markdown
    truncated = False
    if len(body) > _MAX_REPORT_CHARS_IN_PROMPT:
        body = body[:_MAX_REPORT_CHARS_IN_PROMPT]
        truncated = True

    trunc_note = (
        "\n\n[Note: Report text was truncated for the prompt. The full file is still on disk.]\n"
        if truncated
        else ""
    )

    return f"""You are assisting the user during a **review of a research report** only.

## Report under review
- Workflow: `{workflow_id}`
- Version: **{report_version}**

### Report content (markdown)
{body}
{trunc_note}

## Your role
- Discuss **only** this report: its structure, facts, gaps, tone, and what to add or change.
- Help the user **plan edits** for the **final** version (they will approve or request formal changes later).
- If the user asks something unrelated to this report, reply briefly and redirect to the report.
- Prefer **concrete, actionable** suggestions (sections, headings, or bullet lists of edits).

## User message
{user_message}
"""


class UserChatAgent(AgentRole):
    """User chat agent — maintains ongoing conversation during USER_REVIEW state."""

    def __init__(self) -> None:
        self._chat_sessions_announced: set[str] = set()

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

        msg = (message or "").strip()
        if not msg:
            return
        if len(msg) > _MAX_USER_MESSAGE_CHARS:
            msg = msg[:_MAX_USER_MESSAGE_CHARS]

        logger.info(
            "user_chat.send_message.start",
            workflow_id=workflow_id,
            session_id=session_id,
            message_length=len(msg),
        )

        # Ensure session exists (will reuse if it already does)
        wd = settings.gateway_agent_work_dir
        sess_payload = await self._ensure_session(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            working_dir=wd,
        )
        if workflow_id not in self._chat_sessions_announced:
            self._chat_sessions_announced.add(workflow_id)
            await self._emit_agent_session_active(
                event_bus,
                workflow_id,
                session_id,
                self.agent_flow,
                wd,
                self.role_name,
                process_id=session_payload_process_id(sess_payload),
            )

        try:
            report_version, report_md = workspace.get_best_report(workflow_id)
        except FileNotFoundError:
            report_version = "unknown"
            report_md = "(No report file found in the workspace yet.)"
            logger.warning(
                "user_chat.no_report_file",
                workflow_id=workflow_id,
            )

        prompt = _build_report_scoped_prompt(
            workflow_id=workflow_id,
            report_version=report_version,
            report_markdown=report_md,
            user_message=msg,
        )

        # Save user message to conversation log (raw message, not full prompt)
        await workspace.save_conversation_log(
            workflow_id,
            "user",
            {
                "role": "user",
                "content": msg,
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
            # Stream the response (full prompt includes report context; user message stored separately above)
            async for event in gateway.send_prompt(
                session_id=session_id,
                flow=self.agent_flow,
                content=prompt,
            ):
                event_type = event.get("type", "")
                payload = event.get("payload", {})

                # Collect and yield stream deltas
                if event_type == "stream.delta":
                    content = payload.get("delta", "")
                    full_response += content

                    # Dedicated chat event type so UIs route to the report chat panel (not agent stream)
                    await event_bus.publish(
                        workflow_id,
                        UserChatResponseEvent(
                            workflow_id=workflow_id,
                            content=content,
                            streaming=True,
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
