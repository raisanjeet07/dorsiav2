"""REST API endpoints for workflow management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import structlog
from websockets.connection import State as WsState

from app.config import settings
from app.models.database import Workflow as WorkflowORM
from app.persistence.repositories import Repository

logger = structlog.get_logger(__name__)


async def get_repository(request: Request) -> Repository:
    """Create a per-request repository with a fresh DB session."""
    session: AsyncSession = request.app.state.session_factory()
    try:
        yield Repository(session)
    finally:
        await session.close()

# Request/Response Models
class WorkflowCreateRequest(BaseModel):
    """Request model for creating a new workflow."""

    topic: str = Field(..., description="Research topic")
    context: str = Field(default="", description="Optional background context")
    depth: str = Field(default="standard", description="Research depth: shallow/standard/deep")
    max_review_cycles: int = Field(
        default_factory=lambda: settings.default_max_review_cycles,
        description="Max RE_REVIEWING→RESOLVING loops before forced consensus (default from RESEARCH_DEFAULT_MAX_REVIEW_CYCLES)",
    )
    output_format: str = Field(default="markdown", description="Output format")
    agent_config: dict[str, Any] = Field(default_factory=dict, description="Agent configuration")


class WorkflowResponse(BaseModel):
    """Response model for workflow info."""

    workflow_id: str
    topic: str
    context: str
    depth: str
    current_state: str
    previous_state: str | None
    review_cycle: int
    forced_consensus: bool
    workspace_path: str
    created_at: str
    updated_at: str
    completed_at: str | None


def workflow_to_response(w: WorkflowORM) -> WorkflowResponse:
    """Map ORM row to API model; coalesce NULL columns so Pydantic validation never fails."""
    return WorkflowResponse(
        workflow_id=w.workflow_id,
        topic=w.topic or "",
        context=w.context or "",
        depth=w.depth or "standard",
        current_state=w.current_state,
        previous_state=w.previous_state,
        review_cycle=w.review_cycle,
        forced_consensus=w.forced_consensus,
        workspace_path=w.workspace_path or "",
        created_at=w.created_at.isoformat(),
        updated_at=w.updated_at.isoformat(),
        completed_at=w.completed_at.isoformat() if w.completed_at else None,
    )


class WorkflowListResponse(BaseModel):
    """Response model for workflow list."""

    workflows: list[WorkflowResponse]
    total: int
    limit: int
    offset: int


class WorkflowStateResponse(BaseModel):
    """Detailed workflow state info."""

    workflow_id: str
    current_state: str
    previous_state: str | None
    review_cycle: int
    forced_consensus: bool
    state_history: list[dict[str, Any]]
    active_sessions: list[str]
    artifacts: list[dict[str, Any]]


class ApprovalRequest(BaseModel):
    """Request to approve a report."""

    comment: str = Field(default="", description="Optional approval comment")


class ChangesRequest(BaseModel):
    """Request to make changes to the report."""

    changes: dict[str, Any] = Field(..., description="Requested changes")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    gateway_connected: bool
    database_ready: bool
    version: str


# Create router
router = APIRouter(prefix="/api/v1", tags=["workflows"])


@router.post("/workflows", response_model=dict[str, Any])
async def create_workflow(
    request: Request, body: WorkflowCreateRequest, repo: Repository = Depends(get_repository)
) -> dict[str, Any]:
    """Create a new research workflow."""
    orchestrator = request.app.state.orchestrator

    workflow_id = f"wf-{request.app.state.id_counter}"
    request.app.state.id_counter += 1

    logger.info("create_workflow", workflow_id=workflow_id, topic=body.topic)

    try:
        result = await orchestrator.start_workflow(
            workflow_id=workflow_id,
            topic=body.topic,
            context=body.context,
            depth=body.depth,
            config={
                "max_review_cycles": body.max_review_cycles,
                "output_format": body.output_format,
                "agent_config": body.agent_config,
            },
        )

        return {
            "workflow_id": result["workflow_id"],
            "initial_state": result["initial_state"],
            "workspace_path": result["workspace_path"],
        }
    except Exception as e:
        logger.exception("create_workflow.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/workflows", response_model=WorkflowListResponse)
async def list_workflows(
    request: Request,
    state: str | None = Query(None, description="Filter by state"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    repository: Repository = Depends(get_repository),
) -> WorkflowListResponse:
    """List workflows with optional filtering and pagination."""

    logger.info("list_workflows", state=state, limit=limit, offset=offset)

    try:
        workflows = await repository.list_workflows(state=state, limit=limit, offset=offset)

        responses = [workflow_to_response(w) for w in workflows]

        return WorkflowListResponse(
            workflows=responses,
            total=len(workflows),
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.exception("list_workflows.error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflows/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    request: Request, workflow_id: str, repository: Repository = Depends(get_repository)
) -> WorkflowResponse:
    """Get detailed workflow information."""

    logger.info("get_workflow", workflow_id=workflow_id)

    try:
        workflow = await repository.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        return workflow_to_response(workflow)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_workflow.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflows/{workflow_id}/state", response_model=WorkflowStateResponse)
async def get_workflow_state(
    request: Request, workflow_id: str, repository: Repository = Depends(get_repository)
) -> WorkflowStateResponse:
    """Get detailed workflow state information."""
    orchestrator = request.app.state.orchestrator

    logger.info("get_workflow_state", workflow_id=workflow_id)

    try:
        workflow = await repository.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        state_history = await repository.get_state_history(workflow_id)
        artifacts = await repository.get_report_artifacts(workflow_id)

        return WorkflowStateResponse(
            workflow_id=workflow_id,
            current_state=workflow.current_state,
            previous_state=workflow.previous_state,
            review_cycle=workflow.review_cycle,
            forced_consensus=workflow.forced_consensus,
            state_history=[
                {
                    "from_state": h.from_state,
                    "to_state": h.to_state,
                    "trigger": h.trigger,
                    "created_at": h.created_at.isoformat(),
                }
                for h in state_history
            ],
            active_sessions=[],  # Would fetch from database
            artifacts=[
                {
                    "version": a.version,
                    "file_path": a.file_path,
                    "artifact_type": a.artifact_type,
                    "size_bytes": a.size_bytes,
                    "created_at": a.created_at.isoformat(),
                }
                for a in artifacts
            ],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_workflow_state.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workflows/{workflow_id}/cancel", response_model=dict[str, Any])
async def cancel_workflow(request: Request, workflow_id: str) -> dict[str, Any]:
    """Cancel a workflow.

    Args:
        request: FastAPI request
        workflow_id: The workflow ID

    Returns:
        Cancellation info
    """
    orchestrator = request.app.state.orchestrator

    logger.info("cancel_workflow", workflow_id=workflow_id)

    try:
        result = await orchestrator.cancel_workflow(workflow_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("cancel_workflow.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflows/{workflow_id}/report")
async def get_current_report(
    request: Request, workflow_id: str, repository: Repository = Depends(get_repository)
) -> dict[str, Any]:
    """Get current report content (markdown text)."""
    workspace = request.app.state.workspace_manager

    logger.info("get_current_report", workflow_id=workflow_id)

    try:
        workflow = await repository.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        # Prefer final.md when present (completed workflows); else latest draft-vN
        try:
            version, content = workspace.get_best_report(workflow_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="No report generated yet")

        return {
            "workflow_id": workflow_id,
            "version": version,
            "content": content,
            "is_final": version == "final",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_current_report.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflows/{workflow_id}/workspace-files", response_model=dict[str, Any])
async def list_workflow_workspace_files(
    request: Request, workflow_id: str, repository: Repository = Depends(get_repository)
) -> dict[str, Any]:
    """List files under this workflow's workspace directory (scoped to the workflow only)."""
    workspace = request.app.state.workspace_manager

    try:
        wf = await repository.get_workflow(workflow_id)
        if not wf:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        root = workspace.get_workspace_path(workflow_id)
        files: list[dict[str, Any]] = []
        if root.is_dir():
            for p in root.rglob("*"):
                if p.is_file():
                    rel = p.relative_to(root)
                    files.append(
                        {
                            "path": str(rel).replace("\\", "/"),
                            "size_bytes": p.stat().st_size,
                        }
                    )
        files.sort(key=lambda x: x["path"])

        return {
            "workflow_id": workflow_id,
            "workspace_path": str(root),
            "files": files,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("list_workflow_workspace_files.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflows/{workflow_id}/report/final")
async def get_final_report(
    request: Request, workflow_id: str, repository: Repository = Depends(get_repository)
) -> dict[str, Any]:
    """Get final report (file download info)."""
    workspace = request.app.state.workspace_manager

    logger.info("get_final_report", workflow_id=workflow_id)

    try:
        workflow = await repository.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        try:
            content = workspace.get_report(workflow_id, "final")
            final_report_path = str(workspace.get_workspace_path(workflow_id) / "reports" / "final.md")
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="Final report not available yet (workflow must reach COMPLETED)",
            )

        return {
            "workflow_id": workflow_id,
            "file_path": final_report_path,
            "download_url": f"/downloads/workflows/{workflow_id}/final-report",
            "content": content,
            "length_chars": len(content),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_final_report.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflows/{workflow_id}/reviews", response_model=dict[str, Any])
async def get_reviews(
    request: Request, workflow_id: str, repository: Repository = Depends(get_repository)
) -> dict[str, Any]:
    """Get all review rounds with comments."""

    logger.info("get_reviews", workflow_id=workflow_id)

    try:
        workflow = await repository.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        reviews = await repository.get_review_rounds(workflow_id)

        review_data = []
        for review in reviews:
            comments = [
                {
                    "id": c.comment_id,
                    "severity": c.severity,
                    "section": c.section,
                    "comment": c.comment,
                    "recommendation": c.recommendation,
                    "resolved": c.resolved,
                }
                for c in review.comments
            ]
            review_data.append(
                {
                    "cycle": review.cycle,
                    "reviewer_session": review.reviewer_session,
                    "consensus": review.consensus,
                    "overall_quality": review.overall_quality,
                    "summary": review.summary,
                    "comments": comments,
                    "created_at": review.created_at.isoformat(),
                }
            )

        return {
            "workflow_id": workflow_id,
            "reviews": review_data,
            "total_cycles": len(review_data),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_reviews.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workflows/{workflow_id}/conversations", response_model=dict[str, Any])
async def get_conversations(
    request: Request,
    workflow_id: str,
    role: str | None = Query(None, description="Optional role filter"),
    repository: Repository = Depends(get_repository),
) -> dict[str, Any]:
    """Get conversation history."""

    logger.info("get_conversations", workflow_id=workflow_id, role=role)

    try:
        workflow = await repository.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")

        conversations = await repository.get_conversations(workflow_id, role=role)

        conv_data = [
            {
                "session_id": c.session_id,
                "role": c.role,
                "direction": c.direction,
                "content": c.content,
                "content_type": c.content_type,
                "created_at": c.created_at.isoformat(),
            }
            for c in conversations
        ]

        return {
            "workflow_id": workflow_id,
            "conversations": conv_data,
            "total": len(conv_data),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_conversations.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workflows/{workflow_id}/approve", response_model=dict[str, Any])
async def approve_workflow(
    request: Request, workflow_id: str, body: ApprovalRequest
) -> dict[str, Any]:
    """User approves the report.

    Args:
        request: FastAPI request
        workflow_id: The workflow ID
        body: Approval info

    Returns:
        Updated workflow state
    """
    orchestrator = request.app.state.orchestrator

    logger.info("approve_workflow", workflow_id=workflow_id)

    try:
        result = await orchestrator.handle_user_approve(workflow_id, comment=body.comment)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("approve_workflow.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/workflows/{workflow_id}/request-changes", response_model=dict[str, Any])
async def request_changes(
    request: Request, workflow_id: str, body: ChangesRequest
) -> dict[str, Any]:
    """User requests changes to the report.

    Args:
        request: FastAPI request
        workflow_id: The workflow ID
        body: Changes info

    Returns:
        Updated workflow state
    """
    orchestrator = request.app.state.orchestrator

    logger.info("request_changes", workflow_id=workflow_id)

    try:
        result = await orchestrator.handle_user_changes(workflow_id, changes=body.changes)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("request_changes.error", workflow_id=workflow_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """Service health check.

    Args:
        request: FastAPI request

    Returns:
        Health status
    """
    gateway = request.app.state.gateway

    gateway_connected = False
    try:
        # Check if gateway client is connected
        if gateway.ws and gateway.ws.state == WsState.OPEN:
            gateway_connected = True
    except Exception as e:
        logger.warning("health_check.gateway_check_failed", error=str(e))

    return HealthResponse(
        status="healthy",
        gateway_connected=gateway_connected,
        database_ready=True,
        version="1.0.0",
    )
