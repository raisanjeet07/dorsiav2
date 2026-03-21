"""Workspace manager for organizing workflow files and artifacts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class WorkspaceManager:
    """Manages workspace directory structure and file persistence for workflows."""

    def __init__(self, base_dir: str | Path) -> None:
        """Initialize the workspace manager.

        Args:
            base_dir: Base directory for all workflow workspaces.
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info("workspace_manager.initialized", base_dir=str(self.base_dir))

    def get_workspace_path(self, workflow_id: str) -> Path:
        """Get the workspace directory path for a workflow.

        Args:
            workflow_id: The workflow ID.

        Returns:
            Path to the workflow workspace directory.
        """
        return self.base_dir / workflow_id

    def create_workspace(self, workflow_id: str, config: dict[str, Any] | None = None) -> Path:
        """Create workspace directory structure for a workflow.

        Creates:
        - {workflow_id}/config.json
        - {workflow_id}/reports/
        - {workflow_id}/reviews/
        - {workflow_id}/conversations/
        - {workflow_id}/metadata/

        Args:
            workflow_id: The workflow ID.
            config: Optional workflow configuration to save.

        Returns:
            Path to the created workspace directory.
        """
        workspace = self.get_workspace_path(workflow_id)
        workspace.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        for subdir in ["reports", "reviews", "conversations", "metadata"]:
            (workspace / subdir).mkdir(exist_ok=True)

        # Save config if provided
        if config:
            await_none = self.save_config(workflow_id, config)

        logger.info("workspace.created", workflow_id=workflow_id, path=str(workspace))
        return workspace

    def save_report(self, workflow_id: str, version: str, content: str) -> Path:
        """Save a report version to the workspace.

        Args:
            workflow_id: The workflow ID.
            version: Version identifier (e.g., 'draft-v1', 'final').
            content: Report content (markdown).

        Returns:
            Path to the saved report file.
        """
        workspace = self.get_workspace_path(workflow_id)
        report_dir = workspace / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{version}.md" if version != "final" else "final.md"
        report_path = report_dir / filename

        report_path.write_text(content, encoding="utf-8")
        logger.info("report.saved", workflow_id=workflow_id, version=version, path=str(report_path))
        return report_path

    def get_report(self, workflow_id: str, version: str) -> str:
        """Read a report from the workspace.

        Args:
            workflow_id: The workflow ID.
            version: Version identifier.

        Returns:
            Report content as string.

        Raises:
            FileNotFoundError: If the report does not exist.
        """
        workspace = self.get_workspace_path(workflow_id)
        filename = f"{version}.md" if version != "final" else "final.md"
        report_path = workspace / "reports" / filename

        if not report_path.exists():
            raise FileNotFoundError(f"Report not found: {report_path}")

        content = report_path.read_text(encoding="utf-8")
        logger.debug("report.read", workflow_id=workflow_id, version=version)
        return content

    def has_final_report(self, workflow_id: str) -> bool:
        """True if reports/final.md exists (post–user-approval generation)."""
        p = self.get_workspace_path(workflow_id) / "reports" / "final.md"
        return p.exists()

    def get_latest_report_version(self, workflow_id: str) -> str | None:
        """Find the latest draft report version.

        Returns the highest draft-vN version found, or None if no drafts exist.

        Args:
            workflow_id: The workflow ID.

        Returns:
            Latest version string (e.g., 'draft-v3') or None.
        """
        workspace = self.get_workspace_path(workflow_id)
        report_dir = workspace / "reports"

        if not report_dir.exists():
            return None

        # Look for draft-vN.md files
        draft_files = sorted(report_dir.glob("draft-v*.md"))
        if not draft_files:
            return None

        # Extract version number from filename
        latest = draft_files[-1]
        return latest.stem  # e.g., 'draft-v3'

    def get_best_report(self, workflow_id: str) -> tuple[str, str]:
        """Return (version, markdown) for API display.

        Prefers ``final`` when ``final.md`` exists; otherwise latest ``draft-vN``.
        """
        if self.has_final_report(workflow_id):
            return "final", self.get_report(workflow_id, "final")
        latest = self.get_latest_report_version(workflow_id)
        if latest:
            return latest, self.get_report(workflow_id, latest)
        raise FileNotFoundError(f"No report found for workflow {workflow_id}")

    def save_review(self, workflow_id: str, cycle: int, data: dict[str, Any]) -> Path:
        """Save review data for a cycle.

        Args:
            workflow_id: The workflow ID.
            cycle: Review cycle number.
            data: Review data (will be JSON serialized).

        Returns:
            Path to the saved review file.
        """
        workspace = self.get_workspace_path(workflow_id)
        cycle_dir = workspace / "reviews" / f"cycle-{cycle}"
        cycle_dir.mkdir(parents=True, exist_ok=True)

        review_path = cycle_dir / "review.json"
        review_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        logger.info("review.saved", workflow_id=workflow_id, cycle=cycle, path=str(review_path))
        return review_path

    def save_resolution(
        self, workflow_id: str, cycle: int, agent_name: str, data: dict[str, Any]
    ) -> Path:
        """Save individual agent resolution for a cycle.

        Args:
            workflow_id: The workflow ID.
            cycle: Cycle number.
            agent_name: Name of the agent (e.g., 'gemini', 'claude-code').
            data: Resolution data.

        Returns:
            Path to the saved resolution file.
        """
        workspace = self.get_workspace_path(workflow_id)
        cycle_dir = workspace / "reviews" / f"cycle-{cycle}"
        cycle_dir.mkdir(parents=True, exist_ok=True)

        resolution_path = cycle_dir / f"resolution-{agent_name}.json"
        resolution_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        logger.info(
            "resolution.saved",
            workflow_id=workflow_id,
            cycle=cycle,
            agent=agent_name,
            path=str(resolution_path),
        )
        return resolution_path

    def save_merged_resolution(self, workflow_id: str, cycle: int, data: dict[str, Any]) -> Path:
        """Save merged resolutions for a cycle.

        Args:
            workflow_id: The workflow ID.
            cycle: Cycle number.
            data: Merged resolution data.

        Returns:
            Path to the saved merged resolution file.
        """
        workspace = self.get_workspace_path(workflow_id)
        cycle_dir = workspace / "reviews" / f"cycle-{cycle}"
        cycle_dir.mkdir(parents=True, exist_ok=True)

        merged_path = cycle_dir / "merged_resolution.json"
        merged_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

        logger.info(
            "merged_resolution.saved",
            workflow_id=workflow_id,
            cycle=cycle,
            path=str(merged_path),
        )
        return merged_path

    def save_conversation_log(self, workflow_id: str, role: str, turn: dict[str, Any]) -> Path:
        """Append a conversation turn to a JSONL log.

        Args:
            workflow_id: The workflow ID.
            role: Role of the agent/participant (e.g., 'researcher', 'user-chat').
            turn: Conversation turn data (dict).

        Returns:
            Path to the conversation log file.
        """
        workspace = self.get_workspace_path(workflow_id)
        conv_dir = workspace / "conversations"
        conv_dir.mkdir(parents=True, exist_ok=True)

        log_path = conv_dir / f"{role}.jsonl"

        # Append as JSONL (one JSON per line)
        line = json.dumps(turn, default=str) + "\n"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)

        logger.debug("conversation_log.appended", workflow_id=workflow_id, role=role)
        return log_path

    def get_conversation_log(self, workflow_id: str, role: str) -> list[dict[str, Any]]:
        """Read all conversation turns for a role.

        Args:
            workflow_id: The workflow ID.
            role: Role to read logs for.

        Returns:
            List of conversation turn dicts.
        """
        workspace = self.get_workspace_path(workflow_id)
        log_path = workspace / "conversations" / f"{role}.jsonl"

        if not log_path.exists():
            return []

        turns = []
        with log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    turns.append(json.loads(line))

        logger.debug("conversation_log.read", workflow_id=workflow_id, role=role, count=len(turns))
        return turns

    def save_config(self, workflow_id: str, config: dict[str, Any]) -> Path:
        """Save workflow configuration.

        Args:
            workflow_id: The workflow ID.
            config: Configuration dict.

        Returns:
            Path to the saved config file.
        """
        workspace = self.get_workspace_path(workflow_id)
        config_path = workspace / "config.json"

        config["saved_at"] = datetime.now(timezone.utc).isoformat()
        config_path.write_text(json.dumps(config, indent=2, default=str), encoding="utf-8")

        logger.info("config.saved", workflow_id=workflow_id, path=str(config_path))
        return config_path
