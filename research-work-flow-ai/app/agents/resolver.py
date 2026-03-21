"""Dual resolver agents — Gemini and Claude address review feedback."""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.agents.base import AgentRole
from app.agents.gateway_client import GatewayClient
from app.agents.workspace import WorkspaceManager
from app.config import settings
from app.streaming.event_bus import EventBus

logger = structlog.get_logger(__name__)


class ResolverAgent(AgentRole):
    """Resolver agent base — produces resolutions for review comments."""

    @property
    def role_name(self) -> str:
        return "resolver"

    @property
    def agent_flow(self) -> str:
        # Overridden by subclasses
        raise NotImplementedError


class GeminiResolverAgent(ResolverAgent):
    """Gemini resolver agent."""

    @property
    def agent_flow(self) -> str:
        return "gemini"

    async def execute(
        self,
        workflow_id: str,
        context: dict[str, Any],
        gateway: GatewayClient,
        event_bus: EventBus,
        workspace: WorkspaceManager,
    ) -> dict[str, Any]:
        """Resolve review comments using Gemini.

        Args:
            workflow_id: The workflow ID.
            context: Context with 'report_version', 'review_comments', 'cycle'.
            gateway: The gateway client.
            event_bus: Event bus.
            workspace: Workspace manager.

        Returns:
            Dict with 'resolutions' and 'agent' keys.
        """
        report_version = context.get("report_version", "draft-v1")
        review_comments = context.get("review_comments", [])
        cycle = context.get("review_cycle", 1)

        logger.info(
            "gemini_resolver.execute.start",
            workflow_id=workflow_id,
            cycle=cycle,
            comment_count=len(review_comments),
        )

        # Read current report
        report_content = workspace.get_report(workflow_id, report_version)

        # Build resolution prompt
        prompt = self._build_resolution_prompt(report_content, review_comments)

        # Ensure session
        session_id = f"{workflow_id}-resolver-gemini"
        await self._ensure_session(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            working_dir=settings.gateway_agent_work_dir,
        )

        # Stream and collect
        response = await self._stream_and_collect(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            prompt=prompt,
            event_bus=event_bus,
            workflow_id=workflow_id,
            role="resolver-gemini",
        )

        # Parse resolutions
        resolutions = self._parse_resolutions(response)

        logger.info(
            "gemini_resolver.execute.complete",
            workflow_id=workflow_id,
            resolution_count=len(resolutions),
        )

        return {
            "resolutions": resolutions,
            "agent": "gemini",
            "response_preview": response[:500],
        }

    def _build_resolution_prompt(
        self, report_content: str, review_comments: list[dict[str, Any]]
    ) -> str:
        """Build the resolution prompt.

        Args:
            report_content: The current report text.
            review_comments: List of review comments to address.

        Returns:
            Prompt string.
        """
        comments_text = "\n".join(
            [
                f"- {c.get('severity', 'major').upper()}: {c.get('comment')} "
                f"[Recommendation: {c.get('recommendation', 'N/A')}]"
                for c in review_comments
            ]
        )

        prompt = f"""You are tasked with revising a research report to address specific review comments.

Review Comments to Address:
{comments_text}

Current Report:
{report_content}

Please provide resolutions for each comment in JSON format:

{{
  "resolutions": [
    {{
      "comment_id": "<id from review>",
      "action": "<what revision was made>",
      "revised_section": "<the revised text, if applicable>",
      "status": "<resolved|partial|deferred>"
    }},
    ...
  ]
}}

Return ONLY valid JSON."""
        return prompt

    def _parse_resolutions(self, response: str) -> list[dict[str, Any]]:
        """Parse resolutions from response.

        Args:
            response: The response text.

        Returns:
            List of resolution dicts.
        """
        try:
            start_idx = response.find("{")
            end_idx = response.rfind("}") + 1
            if start_idx >= 0 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                data = json.loads(json_str)
                return data.get("resolutions", [])
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("gemini_resolver.parse_error", error=str(e))
        return []


class ClaudeResolverAgent(ResolverAgent):
    """Claude resolver agent."""

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
        """Resolve review comments using Claude Code.

        Args:
            workflow_id: The workflow ID.
            context: Context with 'report_version', 'review_comments', 'cycle'.
            gateway: The gateway client.
            event_bus: Event bus.
            workspace: Workspace manager.

        Returns:
            Dict with 'resolutions' and 'agent' keys.
        """
        report_version = context.get("report_version", "draft-v1")
        review_comments = context.get("review_comments", [])
        cycle = context.get("review_cycle", 1)

        logger.info(
            "claude_resolver.execute.start",
            workflow_id=workflow_id,
            cycle=cycle,
            comment_count=len(review_comments),
        )

        # Read current report
        report_content = workspace.get_report(workflow_id, report_version)

        # Build resolution prompt
        prompt = self._build_resolution_prompt(report_content, review_comments)

        # Ensure session
        session_id = f"{workflow_id}-resolver-claude"
        await self._ensure_session(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            working_dir=settings.gateway_agent_work_dir,
        )

        # Stream and collect
        response = await self._stream_and_collect(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            prompt=prompt,
            event_bus=event_bus,
            workflow_id=workflow_id,
            role="resolver-claude",
        )

        # Parse resolutions
        resolutions = self._parse_resolutions(response)

        logger.info(
            "claude_resolver.execute.complete",
            workflow_id=workflow_id,
            resolution_count=len(resolutions),
        )

        return {
            "resolutions": resolutions,
            "agent": "claude-code",
            "response_preview": response[:500],
        }

    def _build_resolution_prompt(
        self, report_content: str, review_comments: list[dict[str, Any]]
    ) -> str:
        """Build the resolution prompt.

        Args:
            report_content: The current report text.
            review_comments: List of review comments to address.

        Returns:
            Prompt string.
        """
        comments_text = "\n".join(
            [
                f"- {c.get('severity', 'major').upper()}: {c.get('comment')} "
                f"[Recommendation: {c.get('recommendation', 'N/A')}]"
                for c in review_comments
            ]
        )

        prompt = f"""You are tasked with revising a research report to address specific review comments.

Review Comments to Address:
{comments_text}

Current Report:
{report_content}

Please provide resolutions for each comment in JSON format:

{{
  "resolutions": [
    {{
      "comment_id": "<id from review>",
      "action": "<what revision was made>",
      "revised_section": "<the revised text, if applicable>",
      "status": "<resolved|partial|deferred>"
    }},
    ...
  ]
}}

Return ONLY valid JSON."""
        return prompt

    def _parse_resolutions(self, response: str) -> list[dict[str, Any]]:
        """Parse resolutions from response.

        Args:
            response: The response text.

        Returns:
            List of resolution dicts.
        """
        try:
            start_idx = response.find("{")
            end_idx = response.rfind("}") + 1
            if start_idx >= 0 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                data = json.loads(json_str)
                return data.get("resolutions", [])
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("claude_resolver.parse_error", error=str(e))
        return []
