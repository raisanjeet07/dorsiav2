"""Workflow state machine — states, transitions, guards, and transition logic."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


class WorkflowState(str, enum.Enum):
    """All possible states a research workflow can be in."""

    INITIATED = "INITIATED"
    RESEARCHING = "RESEARCHING"
    RESEARCH_COMPLETE = "RESEARCH_COMPLETE"
    REVIEWING = "REVIEWING"
    REVIEW_COMPLETE = "REVIEW_COMPLETE"
    RESOLVING = "RESOLVING"
    RESOLUTION_COMPLETE = "RESOLUTION_COMPLETE"
    RE_REVIEWING = "RE_REVIEWING"
    CONSENSUS_REACHED = "CONSENSUS_REACHED"
    USER_REVIEW = "USER_REVIEW"
    USER_APPROVED = "USER_APPROVED"
    GENERATING_FINAL = "GENERATING_FINAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TransitionTrigger(str, enum.Enum):
    """What caused a state transition."""

    AUTO = "auto"                          # Automatic transition
    AGENT_COMPLETE = "agent_complete"      # Agent finished producing output
    AGENT_ERROR = "agent_error"            # Agent errored
    CONSENSUS_YES = "consensus_yes"        # Reviewer signaled consensus
    CONSENSUS_NO = "consensus_no"          # Reviewer has more comments
    FORCED_CONSENSUS = "forced_consensus"  # Max cycles reached
    USER_APPROVE = "user_approve"          # User approved the report
    USER_CHANGES = "user_changes"          # User requested changes
    USER_CANCEL = "user_cancel"            # User cancelled
    SYSTEM_ERROR = "system_error"          # Unrecoverable system error
    TIMEOUT = "timeout"                    # Agent or user timeout


# Valid transitions: (from_state, trigger) → to_state
TRANSITION_TABLE: dict[tuple[WorkflowState, TransitionTrigger], WorkflowState] = {
    # Research phase
    (WorkflowState.INITIATED, TransitionTrigger.AUTO): WorkflowState.RESEARCHING,
    (WorkflowState.RESEARCHING, TransitionTrigger.AGENT_COMPLETE): WorkflowState.RESEARCH_COMPLETE,
    (WorkflowState.RESEARCH_COMPLETE, TransitionTrigger.AUTO): WorkflowState.REVIEWING,

    # Review phase
    (WorkflowState.REVIEWING, TransitionTrigger.AGENT_COMPLETE): WorkflowState.REVIEW_COMPLETE,
    (WorkflowState.REVIEW_COMPLETE, TransitionTrigger.AUTO): WorkflowState.RESOLVING,

    # Resolution phase
    (WorkflowState.RESOLVING, TransitionTrigger.AGENT_COMPLETE): WorkflowState.RESOLUTION_COMPLETE,
    (WorkflowState.RESOLUTION_COMPLETE, TransitionTrigger.AUTO): WorkflowState.RE_REVIEWING,

    # Re-review → consensus or loop
    (WorkflowState.RE_REVIEWING, TransitionTrigger.CONSENSUS_YES): WorkflowState.CONSENSUS_REACHED,
    (WorkflowState.RE_REVIEWING, TransitionTrigger.CONSENSUS_NO): WorkflowState.RESOLVING,
    (WorkflowState.RE_REVIEWING, TransitionTrigger.FORCED_CONSENSUS): WorkflowState.CONSENSUS_REACHED,

    # Consensus → user review
    (WorkflowState.CONSENSUS_REACHED, TransitionTrigger.AUTO): WorkflowState.USER_REVIEW,

    # User review → approve or request changes
    (WorkflowState.USER_REVIEW, TransitionTrigger.USER_APPROVE): WorkflowState.USER_APPROVED,
    (WorkflowState.USER_REVIEW, TransitionTrigger.USER_CHANGES): WorkflowState.RESOLVING,

    # Final report generation
    (WorkflowState.USER_APPROVED, TransitionTrigger.AUTO): WorkflowState.GENERATING_FINAL,
    (WorkflowState.GENERATING_FINAL, TransitionTrigger.AGENT_COMPLETE): WorkflowState.COMPLETED,
}

# States that can transition to FAILED
FAILABLE_STATES = {
    WorkflowState.RESEARCHING,
    WorkflowState.REVIEWING,
    WorkflowState.RESOLVING,
    WorkflowState.RE_REVIEWING,
    WorkflowState.USER_REVIEW,
    WorkflowState.GENERATING_FINAL,
}

# States that can be cancelled
CANCELLABLE_STATES = {
    WorkflowState.INITIATED,
    WorkflowState.RESEARCHING,
    WorkflowState.RESEARCH_COMPLETE,
    WorkflowState.REVIEWING,
    WorkflowState.REVIEW_COMPLETE,
    WorkflowState.RESOLVING,
    WorkflowState.RESOLUTION_COMPLETE,
    WorkflowState.RE_REVIEWING,
    WorkflowState.CONSENSUS_REACHED,
    WorkflowState.USER_REVIEW,
}

# Terminal states — no transitions out
TERMINAL_STATES = {
    WorkflowState.COMPLETED,
    WorkflowState.FAILED,
    WorkflowState.CANCELLED,
}

# States where an agent is actively running
AGENT_ACTIVE_STATES = {
    WorkflowState.RESEARCHING,
    WorkflowState.REVIEWING,
    WorkflowState.RESOLVING,
    WorkflowState.RE_REVIEWING,
    WorkflowState.GENERATING_FINAL,
}

# States that auto-transition (no external trigger needed)
AUTO_TRANSITION_STATES = {
    WorkflowState.INITIATED,
    WorkflowState.RESEARCH_COMPLETE,
    WorkflowState.REVIEW_COMPLETE,
    WorkflowState.RESOLUTION_COMPLETE,
    WorkflowState.CONSENSUS_REACHED,
    WorkflowState.USER_APPROVED,
}


@dataclass
class StateTransition:
    """Record of a state transition."""

    from_state: WorkflowState | None
    to_state: WorkflowState
    trigger: TransitionTrigger
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


class StateMachineError(Exception):
    """Raised when an invalid state transition is attempted."""


class WorkflowStateMachine:
    """
    Manages state transitions for a single workflow.

    Enforces valid transitions, guards, and cycle limits.
    """

    def __init__(
        self,
        initial_state: WorkflowState = WorkflowState.INITIATED,
        max_review_cycles: int = 5,
        max_user_change_requests: int = 3,
    ) -> None:
        self.current_state = initial_state
        self.max_review_cycles = max_review_cycles
        self.max_user_change_requests = max_user_change_requests
        self.review_cycle = 0
        self.user_change_count = 0
        self.forced_consensus = False
        self.history: list[StateTransition] = []

    def can_transition(self, trigger: TransitionTrigger) -> bool:
        """Check if a transition is valid from the current state with the given trigger."""
        if self.current_state in TERMINAL_STATES:
            return False

        if trigger == TransitionTrigger.USER_CANCEL:
            return self.current_state in CANCELLABLE_STATES

        if trigger in (TransitionTrigger.AGENT_ERROR, TransitionTrigger.SYSTEM_ERROR, TransitionTrigger.TIMEOUT):
            return self.current_state in FAILABLE_STATES

        return (self.current_state, trigger) in TRANSITION_TABLE

    def transition(self, trigger: TransitionTrigger, metadata: dict[str, Any] | None = None) -> StateTransition:
        """
        Execute a state transition.

        Returns the transition record.
        Raises StateMachineError if the transition is invalid.
        """
        metadata = metadata or {}

        # Handle cancellation
        if trigger == TransitionTrigger.USER_CANCEL:
            if self.current_state not in CANCELLABLE_STATES:
                raise StateMachineError(
                    f"Cannot cancel from state {self.current_state.value}"
                )
            return self._apply_transition(WorkflowState.CANCELLED, trigger, metadata)

        # Handle failure
        if trigger in (TransitionTrigger.AGENT_ERROR, TransitionTrigger.SYSTEM_ERROR, TransitionTrigger.TIMEOUT):
            if self.current_state not in FAILABLE_STATES:
                raise StateMachineError(
                    f"Cannot fail from state {self.current_state.value}"
                )
            return self._apply_transition(WorkflowState.FAILED, trigger, metadata)

        # Normal transition
        key = (self.current_state, trigger)
        target = TRANSITION_TABLE.get(key)
        if target is None:
            raise StateMachineError(
                f"Invalid transition: {self.current_state.value} + {trigger.value}"
            )

        # Guard: review cycle limit
        if (
            self.current_state == WorkflowState.RE_REVIEWING
            and trigger == TransitionTrigger.CONSENSUS_NO
        ):
            self.review_cycle += 1
            if self.review_cycle >= self.max_review_cycles:
                # Force consensus
                self.forced_consensus = True
                metadata["forced_consensus"] = True
                metadata["review_cycles_exhausted"] = self.review_cycle
                return self._apply_transition(
                    WorkflowState.CONSENSUS_REACHED,
                    TransitionTrigger.FORCED_CONSENSUS,
                    metadata,
                )

        # Guard: user change request limit
        if (
            self.current_state == WorkflowState.USER_REVIEW
            and trigger == TransitionTrigger.USER_CHANGES
        ):
            self.user_change_count += 1
            metadata["user_change_count"] = self.user_change_count

        # Track review cycles
        if target == WorkflowState.REVIEWING and self.review_cycle == 0:
            self.review_cycle = 1
        elif target == WorkflowState.RESOLVING and self.current_state == WorkflowState.RE_REVIEWING:
            pass  # cycle already incremented above for CONSENSUS_NO

        return self._apply_transition(target, trigger, metadata)

    def _apply_transition(
        self,
        to_state: WorkflowState,
        trigger: TransitionTrigger,
        metadata: dict[str, Any],
    ) -> StateTransition:
        """Apply the transition and record it."""
        transition = StateTransition(
            from_state=self.current_state,
            to_state=to_state,
            trigger=trigger,
            metadata=metadata,
        )
        self.current_state = to_state
        self.history.append(transition)
        return transition

    @property
    def is_terminal(self) -> bool:
        return self.current_state in TERMINAL_STATES

    @property
    def is_agent_active(self) -> bool:
        return self.current_state in AGENT_ACTIVE_STATES

    @property
    def should_auto_transition(self) -> bool:
        return self.current_state in AUTO_TRANSITION_STATES

    def get_next_auto_trigger(self) -> TransitionTrigger | None:
        """If the current state auto-transitions, return the trigger."""
        if self.current_state in AUTO_TRANSITION_STATES:
            return TransitionTrigger.AUTO
        return None
