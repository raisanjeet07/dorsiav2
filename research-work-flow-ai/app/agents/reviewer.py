"""Claude Code reviewer agent — reviews reports and produces consensus feedback."""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.agents.base import AgentRole, session_payload_process_id
from app.agents.gateway_client import GatewayClient
from app.agents.workspace import WorkspaceManager
from app.config import settings
from app.streaming.event_bus import EventBus

logger = structlog.get_logger(__name__)


class ReviewerAgent(AgentRole):
    """Reviewer agent — flow determined by settings.reviewer_agent."""

    @property
    def role_name(self) -> str:
        return "reviewer"

    @property
    def agent_flow(self) -> str:
        return settings.reviewer_agent

    async def execute(
        self,
        workflow_id: str,
        context: dict[str, Any],
        gateway: GatewayClient,
        event_bus: EventBus,
        workspace: WorkspaceManager,
    ) -> dict[str, Any]:
        """Execute the reviewer agent.

        Reviews the current report and produces structured feedback with a consensus flag.

        Args:
            workflow_id: The workflow ID.
            context: Context dict with 'report_version' (e.g., 'draft-v1', 'draft-v2').
            gateway: The gateway client.
            event_bus: Event bus for publishing events.
            workspace: Workspace manager.

        Returns:
            Dict with 'consensus', 'comments', 'overall_quality', 'summary' keys.

        Raises:
            Exception: If review fails.
        """
        report_version = context.get("report_version", "draft-v1")
        cycle = context.get("review_cycle", 1)

        logger.info(
            "reviewer.execute.start",
            workflow_id=workflow_id,
            report_version=report_version,
            cycle=cycle,
        )

        # Read the current report
        try:
            report_content = workspace.get_report(workflow_id, report_version)
        except FileNotFoundError as e:
            logger.error("reviewer.report_not_found", workflow_id=workflow_id, version=report_version)
            raise

        # Build review prompt
        prompt = self._build_review_prompt(report_content, cycle)

        # Ensure session exists with reviewer persona
        session_id = self._build_session_id(workflow_id)
        wd = settings.gateway_agent_work_dir
        sess_payload = await self._ensure_session(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            working_dir=wd,
            skills=["reviewer-persona"],  # Attach reviewer persona skill
        )
        await self._emit_agent_session_active(
            event_bus,
            workflow_id,
            session_id,
            self.agent_flow,
            wd,
            self.role_name,
            process_id=session_payload_process_id(sess_payload),
        )

        # Stream and collect response
        # Note: report content is already embedded in the prompt text.
        # File attachments are not used here because the file lives in the
        # research-workflow container, which is a different volume than the
        # gateway container where Claude Code actually runs.
        review_response = await self._stream_and_collect(
            gateway=gateway,
            session_id=session_id,
            flow=self.agent_flow,
            prompt=prompt,
            event_bus=event_bus,
            workflow_id=workflow_id,
            role=self.role_name,
        )

        # Parse the JSON response
        review_data = self._parse_review_response(review_response)

        logger.info(
            "reviewer.execute.complete",
            workflow_id=workflow_id,
            consensus=review_data.get("consensus"),
            comment_count=len(review_data.get("comments", [])),
        )

        return review_data

    def _build_review_prompt(self, report_content: str, cycle: int) -> str:
        """Build the review prompt.

        Args:
            report_content: The report text to review.
            cycle: Review cycle number.

        Returns:
            Prompt string.
        """
        cycle_context = (
            "This is the first review of the research report."
            if cycle == 1
            else f"This is review cycle {cycle}. The report has been revised based on previous feedback."
        )

        prompt = f"""You are a critical research reviewer. Your job is to thoroughly review a research report and provide actionable feedback.

{cycle_context}

Please review the attached report and provide your feedback in the following JSON format:

{{
  "consensus": <boolean - true if report is ready (no critical issues), false if revisions needed>,
  "overall_quality": "<one of: 'excellent', 'good', 'fair', 'poor'>",
  "summary": "<executive summary of review findings, 2-3 sentences>",
  "comments": [
    {{
      "id": "<comment_id>",
      "severity": "<one of: 'critical', 'major', 'minor'>",
      "section": "<section or topic being criticized>",
      "comment": "<the actual comment/criticism>",
      "recommendation": "<suggested improvement>"
    }},
    ...
  ]
}}

IMPORTANT: Return ONLY valid JSON, no other text.

Evaluation criteria:
1. Accuracy and factual correctness
2. Completeness and thoroughness
3. Structure and clarity
4. Evidence and citation quality
5. Logical flow and coherence
6. Appropriate tone and professionalism

The report is:

{report_content}"""
        return prompt

    def _parse_review_response(self, response: str) -> dict[str, Any]:
        """Parse the JSON review response from Claude.

        Args:
            response: The response text from Claude.

        Returns:
            Parsed review dict.
        """
        try:
            # Try to extract JSON from the response
            # Claude might include some text, so we look for {...}
            start_idx = response.find("{")
            end_idx = response.rfind("}") + 1

            if start_idx >= 0 and end_idx > start_idx:
                json_str = response[start_idx:end_idx]
                review_data = json.loads(json_str)
                return review_data
            else:
                raise ValueError("No JSON found in response")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("reviewer.parse_error", error=str(e), response_preview=response[:200])
            # Return a safe default structure
            return {
                "consensus": False,
                "overall_quality": "fair",
                "summary": "Unable to parse structured feedback; manual review recommended.",
                "comments": [
                    {
                        "id": "parse_error",
                        "severity": "major",
                        "section": "general",
                        "comment": f"Review response parsing error: {str(e)}",
                        "recommendation": "Check reviewer response format",
                    }
                ],
            }
