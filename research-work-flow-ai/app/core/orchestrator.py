"""Workflow orchestrator — the main engine that drives the research workflow."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
import uuid

import structlog

from app.agents.base import AgentRole
from app.agents.gateway_client import GatewayClient
from app.agents.report_generator import ReportGeneratorAgent
from app.agents.researcher import ResearcherAgent
from app.agents.resolver import ClaudeResolverAgent, GeminiResolverAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.user_chat import UserChatAgent
from app.agents.workspace import WorkspaceManager
from app.core.state_machine import (
    StateMachineError,
    TransitionTrigger,
    WorkflowState,
    WorkflowStateMachine,
)
from app.config import settings
from app.persistence.repositories import Repository
from app.streaming.event_bus import EventBus
from app.streaming.events import (
    AgentSessionLifecycleEvent,
    ReviewCommentsEvent,
    ResolutionMergedEvent,
    WorkflowCompletedEvent,
    WorkflowErrorEvent,
    WorkflowStateChangedEvent,
)

logger = structlog.get_logger(__name__)


class WorkflowOrchestrator:
    """Main workflow orchestration engine.

    Manages state transitions, agent execution, and workflow progress.
    """

    def __init__(
        self,
        gateway: GatewayClient,
        event_bus: EventBus,
        repository: Repository,
        workspace_manager: WorkspaceManager,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            gateway: The gateway client for agent communication.
            event_bus: Event bus for publishing workflow events.
            repository: Repository for database persistence.
            workspace_manager: Workspace manager for file operations.
        """
        self.gateway = gateway
        self.event_bus = event_bus
        self.repository = repository
        self.workspace = workspace_manager

        # In-memory state machines per workflow
        self._state_machines: dict[str, WorkflowStateMachine] = {}

        # Background tasks per workflow
        self._tasks: dict[str, asyncio.Task[None]] = {}

        # Agent instances
        self.researcher = ResearcherAgent()
        self.reviewer = ReviewerAgent()
        self.gemini_resolver = GeminiResolverAgent()
        self.claude_resolver = ClaudeResolverAgent()
        self.user_chat = UserChatAgent()
        self.report_generator = ReportGeneratorAgent()

        logger.info("orchestrator.initialized")

    def _gateway_session_specs(self, workflow_id: str) -> list[tuple[str, str, str]]:
        """All (session_id, gateway flow, role) pairs this workflow may create.

        Used for best-effort cleanup on cancel or run exit so subprocesses are not left
        running on the gateway.
        """
        return [
            (f"{workflow_id}-researcher", settings.researcher_agent, "researcher"),
            (f"{workflow_id}-reviewer", settings.reviewer_agent, "reviewer"),
            (f"{workflow_id}-resolver-gemini", "gemini", "resolver-gemini"),
            (f"{workflow_id}-resolver-claude", "claude-code", "resolver-claude"),
            (f"{workflow_id}-user-chat", "claude-code", "user-chat"),
            (f"{workflow_id}-final-report", "claude-code", "final-report"),
        ]

    async def _cleanup_all_gateway_sessions(self, workflow_id: str) -> None:
        """End every known gateway session for this workflow (idempotent, logs at debug on miss)."""
        for session_id, flow, role in self._gateway_session_specs(workflow_id):
            try:
                await self._end_gateway_session(workflow_id, session_id, flow, role)
            except Exception as e:
                logger.debug(
                    "gateway.cleanup_session_skip",
                    workflow_id=workflow_id,
                    session_id=session_id,
                    flow=flow,
                    error=str(e),
                )

    async def _end_gateway_session(
        self,
        workflow_id: str,
        session_id: str,
        flow: str,
        role: str,
    ) -> None:
        """End a gateway agent session and notify subscribers (kills subprocess on gateway)."""
        wd = settings.gateway_agent_work_dir
        try:
            await self.gateway.end_session(session_id, flow)
        except Exception as e:
            logger.warning(
                "gateway.end_session_failed",
                workflow_id=workflow_id,
                session_id=session_id,
                flow=flow,
                error=str(e),
            )
        await self.event_bus.publish(
            workflow_id,
            AgentSessionLifecycleEvent(
                workflow_id=workflow_id,
                role=role,
                session_id=session_id,
                flow=flow,
                workspace_dir=wd,
                process_id=None,
                status="ended",
            ),
        )

    async def start_workflow(
        self,
        workflow_id: str,
        topic: str,
        context: str = "",
        depth: str = "standard",
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Start a new research workflow.

        Creates the workflow in the database, sets up workspace, initializes state machine,
        and starts the async run loop.

        Args:
            workflow_id: Unique workflow identifier.
            topic: Research topic.
            context: Optional background context.
            depth: Research depth (shallow/standard/deep).
            config: Optional workflow configuration.

        Returns:
            Dict with workflow_id, initial_state, and workspace_path.

        Raises:
            ValueError: If workflow already exists.
        """
        logger.info(
            "start_workflow",
            workflow_id=workflow_id,
            topic=topic,
            depth=depth,
        )

        # Check if workflow already exists
        existing = await self.repository.get_workflow(workflow_id)
        if existing:
            raise ValueError(f"Workflow {workflow_id} already exists")

        cfg = config or {}
        max_review_cycles = int(cfg.get("max_review_cycles", settings.default_max_review_cycles))
        max_user_change_requests = int(
            cfg.get("max_user_change_requests", settings.default_max_user_change_requests)
        )
        output_format = str(cfg.get("output_format", "markdown"))

        # Create workspace
        workspace_path = self.workspace.create_workspace(workflow_id, cfg)

        # Create workflow in database
        workflow_data = {
            "workflow_id": workflow_id,
            "topic": topic,
            "context": context,
            "depth": depth,
            "current_state": WorkflowState.INITIATED.value,
            "workspace_path": str(workspace_path),
            "config_json": cfg,
            "max_review_cycles": max_review_cycles,
            "output_format": output_format,
        }
        await self.repository.create_workflow(workflow_data)

        # Initialize state machine (must match persisted max_review_cycles)
        self._state_machines[workflow_id] = WorkflowStateMachine(
            max_review_cycles=max_review_cycles,
            max_user_change_requests=max_user_change_requests,
        )

        # Start the async run loop
        task = asyncio.create_task(self._run_workflow(workflow_id))
        self._tasks[workflow_id] = task

        logger.info(
            "start_workflow.complete",
            workflow_id=workflow_id,
            workspace_path=str(workspace_path),
        )

        return {
            "workflow_id": workflow_id,
            "initial_state": WorkflowState.INITIATED.value,
            "workspace_path": str(workspace_path),
        }

    async def _run_workflow(self, workflow_id: str) -> None:
        """Main workflow run loop — drives state transitions and agent execution.

        Args:
            workflow_id: The workflow ID.
        """
        logger.info("run_workflow.start", workflow_id=workflow_id)

        try:
            while True:
                # Get current state
                sm = self._state_machines[workflow_id]
                workflow = await self.repository.get_workflow(workflow_id)

                if not workflow:
                    logger.error("run_workflow.workflow_not_found", workflow_id=workflow_id)
                    break

                current_state = WorkflowState(sm.current_state)

                # Check for terminal state
                if sm.is_terminal:
                    logger.info(
                        "run_workflow.terminal_state",
                        workflow_id=workflow_id,
                        state=current_state.value,
                    )
                    break

                # Handle auto-transition states
                if sm.should_auto_transition:
                    trigger = sm.get_next_auto_trigger()
                    if trigger:
                        await self._transition(workflow_id, trigger, {})
                        continue

                # Handle agent-active states
                if sm.is_agent_active:
                    try:
                        await self._execute_agent(workflow_id)
                    except Exception as e:
                        logger.exception(
                            "run_workflow.agent_error",
                            workflow_id=workflow_id,
                            state=current_state.value,
                            error=str(e),
                        )
                        await self._transition(
                            workflow_id,
                            TransitionTrigger.AGENT_ERROR,
                            {"error": str(e)},
                        )
                        break
                    continue

                # Handle USER_REVIEW state — wait for user input (no auto-progress)
                if current_state == WorkflowState.USER_REVIEW:
                    logger.info(
                        "run_workflow.waiting_for_user",
                        workflow_id=workflow_id,
                    )
                    # Sleep briefly to avoid busy loop; will be unblocked by user message/approval
                    await asyncio.sleep(5)
                    continue

                # If we get here, something unexpected happened
                logger.warning(
                    "run_workflow.unexpected_state",
                    workflow_id=workflow_id,
                    state=current_state.value,
                )
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            logger.info("run_workflow.cancelled", workflow_id=workflow_id)
            await self._transition(
                workflow_id,
                TransitionTrigger.USER_CANCEL,
                {"reason": "cancelled"},
            )
        except Exception as e:
            logger.exception("run_workflow.fatal_error", workflow_id=workflow_id, error=str(e))
            try:
                await self._transition(
                    workflow_id,
                    TransitionTrigger.SYSTEM_ERROR,
                    {"error": str(e)},
                )
            except Exception:
                pass
        finally:
            # Best-effort: end any gateway sessions still bound to this workflow (e.g. user-chat
            # on cancel, or after errors where per-phase finally did not run).
            try:
                await self._cleanup_all_gateway_sessions(workflow_id)
            except Exception as e:
                logger.warning(
                    "run_workflow.gateway_cleanup_failed",
                    workflow_id=workflow_id,
                    error=str(e),
                )

        logger.info("run_workflow.complete", workflow_id=workflow_id)

    async def _execute_agent(self, workflow_id: str) -> None:
        """Execute the appropriate agent for the current state.

        Args:
            workflow_id: The workflow ID.

        Raises:
            Exception: If agent execution fails.
        """
        sm = self._state_machines[workflow_id]
        workflow = await self.repository.get_workflow(workflow_id)
        current_state = WorkflowState(sm.current_state)

        logger.info("execute_agent.start", workflow_id=workflow_id, state=current_state.value)

        # Build context for agent
        context = {
            "topic": workflow.topic,
            "context": workflow.context,
            "depth": workflow.depth,
            "review_cycle": sm.review_cycle,
        }

        # Select and execute appropriate agent
        agent: AgentRole | None = None
        result: dict[str, Any] | None = None

        if current_state == WorkflowState.RESEARCHING:
            agent = self.researcher
            try:
                result = await agent.execute(
                    workflow_id=workflow_id,
                    context=context,
                    gateway=self.gateway,
                    event_bus=self.event_bus,
                    workspace=self.workspace,
                )
                # Transition to RESEARCH_COMPLETE
                await self._transition(workflow_id, TransitionTrigger.AGENT_COMPLETE, {})
            finally:
                await self._end_gateway_session(
                    workflow_id,
                    self.researcher._build_session_id(workflow_id),
                    settings.researcher_agent,
                    "researcher",
                )

        elif current_state == WorkflowState.REVIEWING:
            agent = self.reviewer
            # Add report version to context
            latest_version = self.workspace.get_latest_report_version(workflow_id)
            context["report_version"] = latest_version or "draft-v1"

            try:
                result = await agent.execute(
                    workflow_id=workflow_id,
                    context=context,
                    gateway=self.gateway,
                    event_bus=self.event_bus,
                    workspace=self.workspace,
                )

                review_comments = result.get("comments", [])
                consensus = result.get("consensus", False)

                await self._save_review(workflow_id, sm.review_cycle, result)

                # Publish review comments event
                await self.event_bus.publish(
                    workflow_id,
                    ReviewCommentsEvent(
                        workflow_id=workflow_id,
                        cycle=sm.review_cycle,
                        comments=[c.get("comment", "") for c in review_comments],
                        consensus=consensus,
                        agent="claude-code",
                    ),
                )

                # First review always proceeds to REVIEW_COMPLETE → RESOLVING.
                # consensus_yes is only valid from RE_REVIEWING.
                await self._transition(
                    workflow_id,
                    TransitionTrigger.AGENT_COMPLETE,
                    {"consensus_reached": consensus},
                )
            finally:
                await self._end_gateway_session(
                    workflow_id,
                    self.reviewer._build_session_id(workflow_id),
                    settings.reviewer_agent,
                    "reviewer",
                )

        elif current_state == WorkflowState.RESOLVING:
            latest_version = self.workspace.get_latest_report_version(workflow_id)
            context["report_version"] = latest_version or "draft-v1"

            # Get review comments from latest review round
            review_rounds = await self.repository.get_review_rounds(workflow_id)
            if review_rounds:
                latest_round = review_rounds[-1]
                comments = [
                    {
                        "id": c.comment_id,
                        "severity": c.severity,
                        "section": c.section,
                        "comment": c.comment,
                        "recommendation": c.recommendation,
                    }
                    for c in latest_round.comments
                ]
                context["review_comments"] = comments

            # Run resolvers. Important: end each gateway session as soon as that resolver
            # finishes — otherwise the previous adapter subprocess stays alive while the next runs.
            gemini_result: dict[str, Any] = {"resolutions": [], "agent": "gemini"}
            claude_result: dict[str, Any] = {"resolutions": [], "agent": "claude-code"}

            async def _run_gemini() -> dict[str, Any]:
                try:
                    return await self.gemini_resolver.execute(
                        workflow_id=workflow_id,
                        context=context,
                        gateway=self.gateway,
                        event_bus=self.event_bus,
                        workspace=self.workspace,
                    )
                except Exception as e:
                    logger.warning(
                        "resolver.gemini_failed",
                        workflow_id=workflow_id,
                        error=str(e),
                    )
                    return {"resolutions": [], "agent": "gemini"}

            async def _run_claude() -> dict[str, Any]:
                try:
                    return await self.claude_resolver.execute(
                        workflow_id=workflow_id,
                        context=context,
                        gateway=self.gateway,
                        event_bus=self.event_bus,
                        workspace=self.workspace,
                    )
                except Exception as e:
                    logger.warning(
                        "resolver.claude_failed",
                        workflow_id=workflow_id,
                        error=str(e),
                    )
                    return {"resolutions": [], "agent": "claude-code"}

            try:
                if settings.resolvers_parallel:
                    gemini_result, claude_result = await asyncio.gather(
                        _run_gemini(),
                        _run_claude(),
                    )
                else:
                    try:
                        gemini_result = await _run_gemini()
                    finally:
                        await self._end_gateway_session(
                            workflow_id,
                            f"{workflow_id}-resolver-gemini",
                            "gemini",
                            "resolver-gemini",
                        )
                    try:
                        claude_result = await _run_claude()
                    finally:
                        await self._end_gateway_session(
                            workflow_id,
                            f"{workflow_id}-resolver-claude",
                            "claude-code",
                            "resolver-claude",
                        )

                # Merge resolutions
                merged = await self._merge_resolutions(
                    workflow_id,
                    sm.review_cycle,
                    gemini_result,
                    claude_result,
                )

                # Save merged resolutions
                self.workspace.save_merged_resolution(
                    workflow_id,
                    sm.review_cycle,
                    merged,
                )

                # Publish resolution merged event
                await self.event_bus.publish(
                    workflow_id,
                    ResolutionMergedEvent(
                        workflow_id=workflow_id,
                        cycle=sm.review_cycle,
                        resolutions=[r.get("action", "") for r in merged.get("resolutions", [])],
                    ),
                )

                # Transition to RESOLUTION_COMPLETE
                await self._transition(workflow_id, TransitionTrigger.AGENT_COMPLETE, {})
            finally:
                if settings.resolvers_parallel:
                    await self._end_gateway_session(
                        workflow_id,
                        f"{workflow_id}-resolver-gemini",
                        "gemini",
                        "resolver-gemini",
                    )
                    await self._end_gateway_session(
                        workflow_id,
                        f"{workflow_id}-resolver-claude",
                        "claude-code",
                        "resolver-claude",
                    )

        elif current_state == WorkflowState.RE_REVIEWING:
            agent = self.reviewer
            latest_version = self.workspace.get_latest_report_version(workflow_id)
            context["report_version"] = latest_version or "draft-v1"

            try:
                result = await agent.execute(
                    workflow_id=workflow_id,
                    context=context,
                    gateway=self.gateway,
                    event_bus=self.event_bus,
                    workspace=self.workspace,
                )

                # Save review
                await self._save_review(workflow_id, sm.review_cycle + 1, result)

                # Check for consensus
                consensus = result.get("consensus", False)

                await self.event_bus.publish(
                    workflow_id,
                    ReviewCommentsEvent(
                        workflow_id=workflow_id,
                        cycle=sm.review_cycle + 1,
                        comments=[c.get("comment", "") for c in result.get("comments", [])],
                        consensus=consensus,
                        agent="claude-code",
                    ),
                )

                # Transition based on consensus (or forced consensus)
                if consensus:
                    await self._transition(
                        workflow_id,
                        TransitionTrigger.CONSENSUS_YES,
                        {"consensus_reached": True},
                    )
                else:
                    await self._transition(
                        workflow_id,
                        TransitionTrigger.CONSENSUS_NO,
                        {"consensus_reached": False},
                    )
            finally:
                await self._end_gateway_session(
                    workflow_id,
                    self.reviewer._build_session_id(workflow_id),
                    settings.reviewer_agent,
                    "reviewer",
                )

        elif current_state == WorkflowState.GENERATING_FINAL:
            agent = self.report_generator
            latest_version = self.workspace.get_latest_report_version(workflow_id)
            context["report_version"] = latest_version or "draft-v1"
            context["user_approval_comments"] = workflow.config_json.get("user_approval_comments", "")

            try:
                result = await agent.execute(
                    workflow_id=workflow_id,
                    context=context,
                    gateway=self.gateway,
                    event_bus=self.event_bus,
                    workspace=self.workspace,
                )

                # Transition to COMPLETED
                await self._transition(
                    workflow_id,
                    TransitionTrigger.AGENT_COMPLETE,
                    {"final_report_path": result.get("final_report_path")},
                )

                # Publish completion event
                await self.event_bus.publish(
                    workflow_id,
                    WorkflowCompletedEvent(
                        workflow_id=workflow_id,
                        final_report_path=result.get("final_report_path", ""),
                        summary=result.get("summary", ""),
                    ),
                )
            finally:
                await self._end_gateway_session(
                    workflow_id,
                    self.report_generator._build_session_id(workflow_id),
                    "claude-code",
                    "final-report",
                )

    async def _transition(
        self,
        workflow_id: str,
        trigger: TransitionTrigger,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Execute a state transition.

        Args:
            workflow_id: The workflow ID.
            trigger: The transition trigger.
            metadata: Optional metadata for the transition.

        Raises:
            StateMachineError: If the transition is invalid.
        """
        metadata = metadata or {}
        sm = self._state_machines[workflow_id]

        try:
            transition = sm.transition(trigger, metadata)

            # Update workflow in database
            await self.repository.update_workflow_state(
                workflow_id=workflow_id,
                new_state=transition.to_state.value,
                previous_state=transition.from_state.value if transition.from_state else None,
                review_cycle=sm.review_cycle,
                forced_consensus=sm.forced_consensus,
            )

            # Record state transition
            await self.repository.add_state_transition(
                workflow_id=workflow_id,
                from_state=transition.from_state.value if transition.from_state else None,
                to_state=transition.to_state.value,
                trigger=trigger.value,
                metadata=metadata,
            )

            # Publish state changed event
            await self.event_bus.publish(
                workflow_id,
                WorkflowStateChangedEvent(
                    workflow_id=workflow_id,
                    from_state=transition.from_state.value if transition.from_state else "",
                    to_state=transition.to_state.value,
                    trigger=trigger.value,
                    review_cycle=sm.review_cycle,
                    metadata=metadata,
                ),
            )

            logger.info(
                "transition.complete",
                workflow_id=workflow_id,
                from_state=transition.from_state.value if transition.from_state else None,
                to_state=transition.to_state.value,
                trigger=trigger.value,
            )

        except StateMachineError as e:
            logger.error(
                "transition.error",
                workflow_id=workflow_id,
                current_state=sm.current_state.value,
                trigger=trigger.value,
                error=str(e),
            )
            raise

    async def handle_user_message(
        self,
        workflow_id: str,
        message: str,
    ) -> None:
        """Handle a user message during USER_REVIEW state.

        Streams assistant output via the event bus as ``user.chat_response`` events.

        Args:
            workflow_id: The workflow ID.
            message: User message text.

        Raises:
            ValueError: If workflow not in USER_REVIEW state.
        """
        sm = self._state_machines.get(workflow_id)
        if not sm or sm.current_state != WorkflowState.USER_REVIEW:
            raise ValueError(f"Workflow {workflow_id} not in USER_REVIEW state")

        logger.info("handle_user_message", workflow_id=workflow_id, message_length=len(message))

        async for _chunk in self.user_chat.send_message(
            workflow_id=workflow_id,
            message=message,
            gateway=self.gateway,
            event_bus=self.event_bus,
            workspace=self.workspace,
        ):
            pass

    async def handle_user_approve(
        self,
        workflow_id: str,
        comment: str = "",
    ) -> dict[str, Any]:
        """Handle user approval of the report.

        Transitions from USER_REVIEW to USER_APPROVED.

        Args:
            workflow_id: The workflow ID.
            comment: Optional approval comment.

        Returns:
            Dict with new state and metadata.

        Raises:
            ValueError: If workflow not in USER_REVIEW state.
        """
        sm = self._state_machines.get(workflow_id)
        if not sm or sm.current_state != WorkflowState.USER_REVIEW:
            raise ValueError(f"Workflow {workflow_id} not in USER_REVIEW state")

        logger.info("handle_user_approve", workflow_id=workflow_id)

        # Save approval comment to config
        workflow = await self.repository.get_workflow(workflow_id)
        workflow.config_json["user_approval_comments"] = comment
        await self.repository.session.flush()

        # Transition to USER_APPROVED
        await self._transition(
            workflow_id,
            TransitionTrigger.USER_APPROVE,
            {"approval_comment": comment},
        )

        await self._end_gateway_session(
            workflow_id,
            f"{workflow_id}-user-chat",
            "claude-code",
            "user-chat",
        )
        self.user_chat._chat_sessions_announced.discard(workflow_id)

        return {
            "workflow_id": workflow_id,
            "new_state": WorkflowState.USER_APPROVED.value,
            "message": "User approval received, proceeding to final report generation",
        }

    async def handle_user_changes(
        self,
        workflow_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle user request for changes to the report.

        Transitions from USER_REVIEW back to RESOLVING.

        Args:
            workflow_id: The workflow ID.
            changes: Dict with requested changes.

        Returns:
            Dict with new state and metadata.

        Raises:
            ValueError: If workflow not in USER_REVIEW state.
        """
        sm = self._state_machines.get(workflow_id)
        if not sm or sm.current_state != WorkflowState.USER_REVIEW:
            raise ValueError(f"Workflow {workflow_id} not in USER_REVIEW state")

        logger.info("handle_user_changes", workflow_id=workflow_id)

        # Save changes to config
        workflow = await self.repository.get_workflow(workflow_id)
        workflow.config_json["user_change_requests"] = changes
        await self.repository.session.flush()

        # Transition back to RESOLVING
        await self._transition(
            workflow_id,
            TransitionTrigger.USER_CHANGES,
            {"changes": changes},
        )

        await self._end_gateway_session(
            workflow_id,
            f"{workflow_id}-user-chat",
            "claude-code",
            "user-chat",
        )
        self.user_chat._chat_sessions_announced.discard(workflow_id)

        return {
            "workflow_id": workflow_id,
            "new_state": WorkflowState.RESOLVING.value,
            "message": "User change request received, returning to resolution phase",
        }

    async def cancel_workflow(self, workflow_id: str) -> dict[str, Any]:
        """Cancel a workflow.

        Args:
            workflow_id: The workflow ID.

        Returns:
            Dict with cancellation info.
        """
        logger.info("cancel_workflow", workflow_id=workflow_id)

        sm = self._state_machines.get(workflow_id)
        if not sm:
            raise ValueError(f"Workflow {workflow_id} not found")

        try:
            await self._transition(workflow_id, TransitionTrigger.USER_CANCEL, {})
        except StateMachineError:
            pass  # Already terminal

        # Cancel background task
        task = self._tasks.get(workflow_id)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.user_chat._chat_sessions_announced.discard(workflow_id)
        await self._cleanup_all_gateway_sessions(workflow_id)

        return {
            "workflow_id": workflow_id,
            "status": "cancelled",
        }

    async def get_workflow_state(self, workflow_id: str) -> dict[str, Any]:
        """Get the current state of a workflow.

        Args:
            workflow_id: The workflow ID.

        Returns:
            Dict with workflow state information.
        """
        workflow = await self.repository.get_workflow(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")

        sm = self._state_machines.get(workflow_id)
        current_state = sm.current_state.value if sm else workflow.current_state

        return {
            "workflow_id": workflow_id,
            "current_state": current_state,
            "previous_state": workflow.previous_state,
            "review_cycle": workflow.review_cycle,
            "forced_consensus": workflow.forced_consensus,
            "topic": workflow.topic,
            "depth": workflow.depth,
            "created_at": workflow.created_at.isoformat(),
            "updated_at": workflow.updated_at.isoformat(),
            "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None,
        }

    async def _save_review(
        self,
        workflow_id: str,
        cycle: int,
        review_result: dict[str, Any],
    ) -> None:
        """Save review data to workspace and database.

        Args:
            workflow_id: The workflow ID.
            cycle: Review cycle number.
            review_result: Review result dict from reviewer agent.
        """
        # Save to workspace
        self.workspace.save_review(workflow_id, cycle, review_result)

        # Save to database
        session_id = f"{workflow_id}-reviewer"
        comments = review_result.get("comments", [])
        consensus = review_result.get("consensus", False)

        review_round = await self.repository.create_review_round(
            workflow_id=workflow_id,
            cycle=cycle,
            reviewer_session=session_id,
            consensus=consensus,
            overall_quality=review_result.get("overall_quality"),
            summary=review_result.get("summary"),
            raw_output=review_result,
        )

        # Add individual comments
        for comment_data in comments:
            await self.repository.add_review_comment(
                review_round_id=review_round.id,
                comment_id=comment_data.get("id", str(uuid.uuid4())),
                severity=comment_data.get("severity", "major"),
                section=comment_data.get("section"),
                comment=comment_data.get("comment", ""),
                recommendation=comment_data.get("recommendation"),
            )

        logger.info(
            "save_review.complete",
            workflow_id=workflow_id,
            cycle=cycle,
            comment_count=len(comments),
        )

    async def _merge_resolutions(
        self,
        workflow_id: str,
        cycle: int,
        gemini_result: dict[str, Any],
        claude_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge resolutions from both agents.

        Args:
            workflow_id: The workflow ID.
            cycle: Cycle number.
            gemini_result: Resolutions from Gemini.
            claude_result: Resolutions from Claude.

        Returns:
            Merged resolution dict.
        """
        # Save individual resolutions
        self.workspace.save_resolution(workflow_id, cycle, "gemini", gemini_result)
        self.workspace.save_resolution(workflow_id, cycle, "claude-code", claude_result)

        # Merge: for each comment, combine perspectives
        gemini_resolutions = {
            r.get("comment_id"): r for r in gemini_result.get("resolutions", [])
        }
        claude_resolutions = {
            r.get("comment_id"): r for r in claude_result.get("resolutions", [])
        }

        merged_resolutions = []
        all_comment_ids = set(gemini_resolutions.keys()) | set(claude_resolutions.keys())

        for comment_id in all_comment_ids:
            gemini_res = gemini_resolutions.get(comment_id)
            claude_res = claude_resolutions.get(comment_id)

            if gemini_res and claude_res:
                # Both agents have a resolution
                if gemini_res.get("action") == claude_res.get("action"):
                    # Consensus
                    merged_resolutions.append({
                        "comment_id": comment_id,
                        "status": "agreed",
                        "action": gemini_res.get("action"),
                        "perspectives": [
                            {"agent": "gemini", "action": gemini_res.get("action")},
                            {"agent": "claude-code", "action": claude_res.get("action")},
                        ],
                    })
                else:
                    # Disagreement — include both
                    merged_resolutions.append({
                        "comment_id": comment_id,
                        "status": "disagreement",
                        "perspectives": [
                            {"agent": "gemini", "action": gemini_res.get("action")},
                            {"agent": "claude-code", "action": claude_res.get("action")},
                        ],
                    })
            elif gemini_res:
                merged_resolutions.append({
                    "comment_id": comment_id,
                    "status": "single_perspective",
                    "agent": "gemini",
                    "action": gemini_res.get("action"),
                })
            else:
                merged_resolutions.append({
                    "comment_id": comment_id,
                    "status": "single_perspective",
                    "agent": "claude-code",
                    "action": claude_res.get("action"),
                })

        return {
            "cycle": cycle,
            "resolutions": merged_resolutions,
            "merged_at": datetime.now(timezone.utc).isoformat(),
        }
