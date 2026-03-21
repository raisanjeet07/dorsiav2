"""Final report generator agent — produces the final report incorporating all feedback."""

from __future__ import annotations

from typing import Any

import structlog

from app.agents.base import AgentRole
from app.agents.gateway_client import GatewayClient
from app.agents.workspace import WorkspaceManager
from app.config import settings
from app.streaming.event_bus import EventBus

logger = structlog.get_logger(__name__)


class ReportGeneratorAgent(AgentRole):
    """Final report generator powered by Claude Code."""

    @property
    def role_name(self) -> str:
        return "final-report"

    @property
    def agent_flow(self) -> str:
        return "claude-code"

    async def execute(
        self,
        workflow_id: str,
        context: dict[str, Any],
        gateway: GatewayClient,
        event_bus: EventBus,
        workspace: WorkspaceManager,
    ) -> dict[str, Any]:
        """Execute the final report generator.

        Produces a comprehensive final report by:
        1. Reading the current report
        2. Reading all review cycles
        3. Reading user chat conversation
        4. Incorporating all feedback with user input prioritized
        5. Saving to reports/final.md

        Args:
            workflow_id: The workflow ID.
            context: Context dict with 'report_version'.
            gateway: The gateway client.
            event_bus: Event bus for publishing events.
            workspace: Workspace manager.

        Returns:
            Dict with 'final_report_path' and 'summary' keys.

        Raises:
            Exception: If generation fails.
        """
        report_version = context.get("report_version", "draft-v1")
        user_approval_comments = context.get("user_approval_comments", "")

        logger.info(
            "final_report.execute.start",
            workflow_id=workflow_id,
            report_version=report_version,
        )

        # Gather all source materials
        current_report = workspace.get_report(workflow_id, report_version)
        user_chat_log = workspace.get_conversation_log(workflow_id, "user")

        # Build comprehensive prompt
        prompt = self._build_generation_prompt(
            current_report=current_report,
            user_comments=user_approval_comments,
            user_chat_log=user_chat_log,
            report_version=report_version,
        )

        # Ensure session
        session_id = self._build_session_id(workflow_id)
        await self._ensure_session(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            working_dir=settings.gateway_agent_work_dir,
        )

        # Stream and collect response
        final_report = await self._stream_and_collect(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            prompt=prompt,
            event_bus=event_bus,
            workflow_id=workflow_id,
            role=self.role_name,
        )

        # Save final report
        report_path = workspace.save_report(workflow_id, "final", final_report)

        # Extract a short summary
        summary = self._extract_summary(final_report)

        logger.info(
            "final_report.execute.complete",
            workflow_id=workflow_id,
            report_path=str(report_path),
            content_length=len(final_report),
        )

        return {
            "final_report_path": str(report_path),
            "summary": summary,
            "content_length": len(final_report),
        }

    def _build_generation_prompt(
        self,
        current_report: str,
        user_comments: str,
        user_chat_log: list[dict[str, Any]],
        report_version: str,
    ) -> str:
        """Build the final report generation prompt.

        Args:
            current_report: The current best version of the report.
            user_comments: User approval comments.
            user_chat_log: Conversation log with user.
            report_version: Version string (e.g., 'draft-v3').

        Returns:
            Prompt string.
        """
        chat_summary = ""
        if user_chat_log:
            chat_summary = "\nUser Feedback (from conversation):\n"
            for turn in user_chat_log[-10:]:  # Last 10 turns
                role = turn.get("role", "").capitalize()
                content = turn.get("content", "")[:200]  # First 200 chars
                chat_summary += f"- {role}: {content}\n"

        prompt = f"""You are tasked with producing the final, polished research report.

Current Report (version {report_version}):
{current_report}

User Approval Comments:
{user_comments if user_comments else "(No additional comments)"}

{chat_summary}

Instructions:
1. Use the current report as the foundation
2. Incorporate all user feedback and comments — USER FEEDBACK IS HIGHEST PRIORITY
3. Refine structure, clarity, and presentation
4. Ensure all sections are complete and well-integrated
5. Add an Executive Summary at the top
6. Maintain professional academic/research tone
7. Ensure proper formatting and structure
8. Do NOT change the fundamental findings unless specifically requested by user feedback

Produce a polished, final report in markdown format that is ready for publication."""
        return prompt

    def _extract_summary(self, report: str) -> str:
        """Extract a short summary from the report.

        Args:
            report: The full report text.

        Returns:
            A brief summary (first 500 chars or first section).
        """
        # Try to extract from Executive Summary section
        if "# Executive Summary" in report:
            start = report.find("# Executive Summary") + len("# Executive Summary")
            end = report.find("\n#", start)
            if end == -1:
                end = len(report)
            summary = report[start:end].strip()
            return summary[:500]

        # Fall back to first 500 chars
        return report[:500].strip()
