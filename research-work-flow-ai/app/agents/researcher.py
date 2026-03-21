"""Gemini research agent — produces initial research report."""

from __future__ import annotations

from typing import Any

import structlog

from app.agents.base import AgentRole
from app.agents.gateway_client import GatewayClient
from app.agents.workspace import WorkspaceManager
from app.config import settings
from app.streaming.event_bus import EventBus

logger = structlog.get_logger(__name__)


class ResearcherAgent(AgentRole):
    """Research agent — flow determined by settings.researcher_agent."""

    @property
    def role_name(self) -> str:
        return "researcher"

    @property
    def agent_flow(self) -> str:
        return settings.researcher_agent

    async def execute(
        self,
        workflow_id: str,
        context: dict[str, Any],
        gateway: GatewayClient,
        event_bus: EventBus,
        workspace: WorkspaceManager,
    ) -> dict[str, Any]:
        """Execute the researcher agent.

        Produces an initial research report and saves it as draft-v1.md.

        Args:
            workflow_id: The workflow ID.
            context: Context dict with 'topic', 'context' (optional), 'depth' (optional).
            gateway: The gateway client.
            event_bus: Event bus for publishing events.
            workspace: Workspace manager.

        Returns:
            Dict with 'report_path' and 'report_version' keys.

        Raises:
            Exception: If research fails.
        """
        topic = context.get("topic", "")
        research_context = context.get("context", "")
        depth = context.get("depth", "standard")

        logger.info("researcher.execute.start", workflow_id=workflow_id, topic=topic, depth=depth)

        # Build research prompt
        prompt = self._build_research_prompt(topic, research_context, depth)

        # Ensure session exists
        session_id = self._build_session_id(workflow_id)
        await self._ensure_session(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            working_dir=settings.gateway_agent_work_dir,
        )

        # Stream and collect response
        report_content = await self._stream_and_collect(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            prompt=prompt,
            event_bus=event_bus,
            workflow_id=workflow_id,
            role=self.role_name,
        )

        # Save report
        report_path = workspace.save_report(workflow_id, "draft-v1", report_content)

        logger.info(
            "researcher.execute.complete",
            workflow_id=workflow_id,
            report_path=str(report_path),
            content_length=len(report_content),
        )

        return {
            "report_path": str(report_path),
            "report_version": "draft-v1",
            "content_length": len(report_content),
        }

    def _build_research_prompt(self, topic: str, context: str, depth: str) -> str:
        """Build the research prompt.

        Args:
            topic: Research topic.
            context: Optional background context.
            depth: Research depth level.

        Returns:
            Prompt string.
        """
        depth_guidance = {
            "shallow": "Provide a brief overview with key points.",
            "standard": "Provide a comprehensive analysis with main findings and supporting evidence.",
            "deep": "Conduct an exhaustive analysis with detailed evidence, edge cases, and implications.",
        }.get(depth, "Provide a comprehensive analysis.")

        prompt = f"""Research the following topic and produce a detailed research report.

Topic: {topic}

{f'Background Context: {context}' if context else ''}

Depth Level: {depth}
{depth_guidance}

Please structure your report with:
1. Executive Summary
2. Introduction
3. Main Findings (organized by theme/category)
4. Supporting Evidence and Analysis
5. Implications and Recommendations
6. Limitations and Caveats
7. Conclusion

Use markdown formatting. Be thorough, accurate, and cite sources where applicable."""
        return prompt
