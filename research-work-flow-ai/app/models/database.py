"""SQLAlchemy ORM models for research workflow persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import uuid


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


class Workflow(Base):
    """Represents a single research workflow."""

    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(Text, nullable=True)
    depth: Mapped[str] = mapped_column(String(50), nullable=True)
    current_state: Mapped[str] = mapped_column(String(50), default="INITIATED", nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    review_cycle: Mapped[int] = mapped_column(default=0, nullable=False)
    max_review_cycles: Mapped[int] = mapped_column(default=5, nullable=False)
    forced_consensus: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    output_format: Mapped[str] = mapped_column(String(50), default="markdown", nullable=False)
    workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    state_transitions: Mapped[list[StateTransition]] = relationship(
        "StateTransition", back_populates="workflow", cascade="all, delete-orphan"
    )
    agent_sessions: Mapped[list[AgentSession]] = relationship(
        "AgentSession", back_populates="workflow", cascade="all, delete-orphan"
    )
    review_rounds: Mapped[list[ReviewRound]] = relationship(
        "ReviewRound", back_populates="workflow", cascade="all, delete-orphan"
    )
    conversation_turns: Mapped[list[ConversationTurn]] = relationship(
        "ConversationTurn", back_populates="workflow", cascade="all, delete-orphan"
    )
    report_artifacts: Mapped[list[ReportArtifact]] = relationship(
        "ReportArtifact", back_populates="workflow", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_workflows_workflow_id", "workflow_id"), Index("ix_workflows_current_state", "current_state"))


class StateTransition(Base):
    """Records state transitions for a workflow."""

    __tablename__ = "state_transitions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    from_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="state_transitions")

    __table_args__ = (Index("ix_state_transitions_workflow_id", "workflow_id"),)


class AgentSession(Base):
    """Represents an agent session within a workflow."""

    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    agent_flow: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="created", nullable=False)
    persona_skill: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="agent_sessions")

    __table_args__ = (
        Index("ix_agent_sessions_workflow_id", "workflow_id"),
        Index("ix_agent_sessions_session_id", "session_id"),
    )


class ReviewRound(Base):
    """Represents a review cycle for a workflow."""

    __tablename__ = "review_rounds"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    cycle: Mapped[int] = mapped_column(nullable=False)
    reviewer_session: Mapped[str] = mapped_column(String(255), nullable=False)
    consensus: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    overall_quality: Mapped[str | None] = mapped_column(String(50), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="review_rounds")
    comments: Mapped[list[ReviewComment]] = relationship(
        "ReviewComment", back_populates="review_round", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_review_rounds_workflow_id", "workflow_id"),)


class ReviewComment(Base):
    """Represents a comment within a review round."""

    __tablename__ = "review_comments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    review_round_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("review_rounds.id", ondelete="CASCADE"), nullable=False
    )
    comment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(50), nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    review_round: Mapped[ReviewRound] = relationship("ReviewRound", back_populates="comments")

    __table_args__ = (Index("ix_review_comments_review_round_id", "review_round_id"),)


class ConversationTurn(Base):
    """Represents a single turn in an agent conversation."""

    __tablename__ = "conversation_turns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)  # 'in' or 'out'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), default="text", nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="conversation_turns")

    __table_args__ = (
        Index("ix_conversation_turns_workflow_id", "workflow_id"),
        Index("ix_conversation_turns_session_id", "session_id"),
    )


class ReportArtifact(Base):
    """Represents a generated report artifact."""

    __tablename__ = "report_artifacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(50), default="report", nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)

    # Relationships
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="report_artifacts")

    __table_args__ = (Index("ix_report_artifacts_workflow_id", "workflow_id"),)
