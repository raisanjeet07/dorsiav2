"""Repository layer for data access — async SQLAlchemy queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database import (
    AgentSession,
    ConversationTurn,
    ReportArtifact,
    ReviewComment,
    ReviewRound,
    StateTransition,
    Workflow,
)


class Repository:
    """Data access layer with async methods for all database operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an async session."""
        self.session = session

    # ============================================================================
    # Workflow Operations
    # ============================================================================

    async def create_workflow(self, workflow_data: dict[str, Any]) -> Workflow:
        """
        Create a new workflow.

        Args:
            workflow_data: Dictionary containing workflow attributes (workflow_id, topic, context, depth, etc.)

        Returns:
            The created Workflow object.
        """
        workflow = Workflow(**workflow_data)
        self.session.add(workflow)
        await self.session.commit()
        return workflow

    async def get_workflow(self, workflow_id: str) -> Workflow | None:
        """
        Retrieve a workflow by workflow_id.

        Args:
            workflow_id: The unique workflow_id string.

        Returns:
            The Workflow object or None if not found.
        """
        stmt = select(Workflow).where(Workflow.workflow_id == workflow_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_workflows(
        self, state: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[Workflow]:
        """
        List workflows with optional filtering and pagination.

        Args:
            state: Filter by current_state (optional).
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of Workflow objects.
        """
        stmt = select(Workflow)
        if state:
            stmt = stmt.where(Workflow.current_state == state)
        stmt = stmt.order_by(desc(Workflow.created_at)).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def update_workflow_state(
        self,
        workflow_id: str,
        new_state: str,
        previous_state: str | None = None,
        review_cycle: int | None = None,
        forced_consensus: bool = False,
    ) -> Workflow | None:
        """
        Update workflow state and related fields.

        Args:
            workflow_id: The unique workflow_id string.
            new_state: The new state value.
            previous_state: The previous state (optional).
            review_cycle: Update review_cycle if provided.
            forced_consensus: Set forced_consensus flag if True.

        Returns:
            The updated Workflow object or None if not found.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return None

        workflow.previous_state = workflow.current_state if previous_state is None else previous_state
        workflow.current_state = new_state
        if review_cycle is not None:
            workflow.review_cycle = review_cycle
        if forced_consensus:
            workflow.forced_consensus = True

        await self.session.commit()
        return workflow

    # ============================================================================
    # State Transition Operations
    # ============================================================================

    async def add_state_transition(
        self,
        workflow_id: str,
        from_state: str | None,
        to_state: str,
        trigger: str,
        metadata: dict[str, Any] | None = None,
    ) -> StateTransition:
        """
        Record a state transition for a workflow.

        Args:
            workflow_id: The unique workflow_id string.
            from_state: The previous state (can be None).
            to_state: The new state.
            trigger: What triggered the transition.
            metadata: Optional metadata to store with the transition.

        Returns:
            The created StateTransition object.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        transition = StateTransition(
            workflow_id=workflow.id,
            from_state=from_state,
            to_state=to_state,
            trigger=trigger,
            metadata_json=metadata or {},
        )
        self.session.add(transition)
        await self.session.commit()
        return transition

    async def get_state_history(self, workflow_id: str) -> list[StateTransition]:
        """
        Retrieve all state transitions for a workflow.

        Args:
            workflow_id: The unique workflow_id string.

        Returns:
            List of StateTransition objects ordered by creation time.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return []

        stmt = (
            select(StateTransition)
            .where(StateTransition.workflow_id == workflow.id)
            .order_by(StateTransition.created_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # ============================================================================
    # Agent Session Operations
    # ============================================================================

    async def create_agent_session(
        self,
        workflow_id: str,
        session_id: str,
        role: str,
        agent_flow: str,
        persona_skill: str | None = None,
    ) -> AgentSession:
        """
        Create a new agent session within a workflow.

        Args:
            workflow_id: The unique workflow_id string.
            session_id: The unique session ID.
            role: The role of the agent (e.g., 'researcher', 'reviewer').
            agent_flow: The agent flow type.
            persona_skill: Optional persona/skill information.

        Returns:
            The created AgentSession object.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        session = AgentSession(
            workflow_id=workflow.id,
            session_id=session_id,
            role=role,
            agent_flow=agent_flow,
            persona_skill=persona_skill,
        )
        self.session.add(session)
        await self.session.commit()
        return session

    async def update_agent_session_status(
        self, session_id: str, status: str, ended_at: datetime | None = None
    ) -> AgentSession | None:
        """
        Update an agent session's status.

        Args:
            session_id: The session_id to update.
            status: The new status.
            ended_at: Optional end timestamp.

        Returns:
            The updated AgentSession or None if not found.
        """
        stmt = select(AgentSession).where(AgentSession.session_id == session_id)
        result = await self.session.execute(stmt)
        session = result.scalar_one_or_none()

        if session:
            session.status = status
            if ended_at:
                session.ended_at = ended_at
            await self.session.commit()

        return session

    # ============================================================================
    # Review Round Operations
    # ============================================================================

    async def create_review_round(
        self,
        workflow_id: str,
        cycle: int,
        reviewer_session: str,
        consensus: bool = False,
        overall_quality: str | None = None,
        summary: str | None = None,
        raw_output: dict[str, Any] | None = None,
    ) -> ReviewRound:
        """
        Create a new review round for a workflow.

        Args:
            workflow_id: The unique workflow_id string.
            cycle: The review cycle number.
            reviewer_session: The reviewer's session ID.
            consensus: Whether consensus was reached.
            overall_quality: Quality assessment (e.g., 'high', 'medium', 'low').
            summary: Summary of the review.
            raw_output: Raw output from the reviewer agent.

        Returns:
            The created ReviewRound object.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        review_round = ReviewRound(
            workflow_id=workflow.id,
            cycle=cycle,
            reviewer_session=reviewer_session,
            consensus=consensus,
            overall_quality=overall_quality,
            summary=summary,
            raw_output=raw_output or {},
        )
        self.session.add(review_round)
        await self.session.commit()
        return review_round

    async def get_review_rounds(self, workflow_id: str) -> list[ReviewRound]:
        """
        Retrieve all review rounds for a workflow.

        Args:
            workflow_id: The unique workflow_id string.

        Returns:
            List of ReviewRound objects ordered by cycle.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return []

        stmt = (
            select(ReviewRound)
            .where(ReviewRound.workflow_id == workflow.id)
            .order_by(ReviewRound.cycle)
            .options(selectinload(ReviewRound.comments))
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # ============================================================================
    # Review Comment Operations
    # ============================================================================

    async def add_review_comment(
        self,
        review_round_id: int,
        comment_id: str,
        severity: str,
        section: str | None,
        comment: str,
        recommendation: str | None = None,
    ) -> ReviewComment:
        """
        Add a comment to a review round.

        Args:
            review_round_id: The ReviewRound ID.
            comment_id: Unique ID for this comment.
            severity: Severity level (e.g., 'critical', 'major', 'minor').
            section: The section of the document this comment applies to.
            comment: The comment text.
            recommendation: Recommended action.

        Returns:
            The created ReviewComment object.
        """
        review_comment = ReviewComment(
            review_round_id=review_round_id,
            comment_id=comment_id,
            severity=severity,
            section=section,
            comment=comment,
            recommendation=recommendation,
        )
        self.session.add(review_comment)
        await self.session.commit()
        return review_comment

    async def resolve_comment(
        self, comment_id: str, resolution: dict[str, Any] | None = None
    ) -> ReviewComment | None:
        """
        Mark a review comment as resolved.

        Args:
            comment_id: The comment_id to resolve.
            resolution: Optional resolution details.

        Returns:
            The updated ReviewComment or None if not found.
        """
        stmt = select(ReviewComment).where(ReviewComment.comment_id == comment_id)
        result = await self.session.execute(stmt)
        comment = result.scalar_one_or_none()

        if comment:
            comment.resolved = True
            comment.resolution = resolution or {}
            await self.session.commit()

        return comment

    # ============================================================================
    # Conversation Turn Operations
    # ============================================================================

    async def add_conversation_turn(
        self,
        workflow_id: str,
        session_id: str,
        role: str,
        direction: str,
        content: str,
        content_type: str = "text",
        metadata: dict[str, Any] | None = None,
    ) -> ConversationTurn:
        """
        Record a conversation turn (message) in a workflow.

        Args:
            workflow_id: The unique workflow_id string.
            session_id: The session ID (from AgentSession).
            role: The role of the speaker (e.g., 'researcher', 'reviewer').
            direction: 'in' for incoming, 'out' for outgoing.
            content: The message content.
            content_type: Type of content (default 'text').
            metadata: Optional metadata.

        Returns:
            The created ConversationTurn object.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        turn = ConversationTurn(
            workflow_id=workflow.id,
            session_id=session_id,
            role=role,
            direction=direction,
            content=content,
            content_type=content_type,
            metadata_json=metadata or {},
        )
        self.session.add(turn)
        await self.session.commit()
        return turn

    async def get_conversations(self, workflow_id: str, role: str | None = None) -> list[ConversationTurn]:
        """
        Retrieve conversation turns for a workflow, optionally filtered by role.

        Args:
            workflow_id: The unique workflow_id string.
            role: Optional role filter (e.g., 'researcher', 'reviewer').

        Returns:
            List of ConversationTurn objects ordered by creation time.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return []

        conditions = [ConversationTurn.workflow_id == workflow.id]
        if role:
            conditions.append(ConversationTurn.role == role)

        stmt = select(ConversationTurn).where(and_(*conditions)).order_by(ConversationTurn.created_at)
        result = await self.session.execute(stmt)
        return result.scalars().all()

    # ============================================================================
    # Report Artifact Operations
    # ============================================================================

    async def create_report_artifact(
        self,
        workflow_id: str,
        version: str,
        file_path: str,
        artifact_type: str = "report",
        size_bytes: int = 0,
        checksum: str | None = None,
    ) -> ReportArtifact:
        """
        Create a report artifact record.

        Args:
            workflow_id: The unique workflow_id string.
            version: Version identifier for the report.
            file_path: Path to the artifact file.
            artifact_type: Type of artifact (default 'report').
            size_bytes: Size of the artifact in bytes.
            checksum: Optional checksum (e.g., SHA256).

        Returns:
            The created ReportArtifact object.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        artifact = ReportArtifact(
            workflow_id=workflow.id,
            version=version,
            file_path=file_path,
            artifact_type=artifact_type,
            size_bytes=size_bytes,
            checksum=checksum,
        )
        self.session.add(artifact)
        await self.session.commit()
        return artifact

    async def get_report_artifacts(self, workflow_id: str) -> list[ReportArtifact]:
        """
        Retrieve all report artifacts for a workflow.

        Args:
            workflow_id: The unique workflow_id string.

        Returns:
            List of ReportArtifact objects ordered by creation time.
        """
        workflow = await self.get_workflow(workflow_id)
        if not workflow:
            return []

        stmt = (
            select(ReportArtifact).where(ReportArtifact.workflow_id == workflow.id).order_by(ReportArtifact.created_at)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
