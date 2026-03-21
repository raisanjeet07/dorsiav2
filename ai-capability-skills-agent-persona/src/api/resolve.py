"""REST endpoints for resolution preview and gateway sync."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/resolve", tags=["resolve"])


class ResolveRequest(BaseModel):
    persona_name: str
    agent_name: str
    capability_overrides: dict[str, dict[str, Any]] | None = None
    model_override: str | None = None
    mode_override: str | None = None


class SyncRequest(BaseModel):
    persona_name: str
    agent_name: str
    capability_overrides: dict[str, dict[str, Any]] | None = None
    model_override: str | None = None
    mode_override: str | None = None
    session_id: str | None = None  # if provided, also attach to this session


@router.get("", summary="Preview: resolve a persona + agent combo (dry-run)")
async def resolve_preview(
    request: Request,
    persona_name: str,
    agent_name: str,
):
    resolver = request.app.state.resolver
    result = resolver.resolve_preview(persona_name, agent_name)
    return result


@router.post("/preview", summary="Preview with overrides (dry-run)")
async def resolve_preview_with_overrides(body: ResolveRequest, request: Request):
    resolver = request.app.state.resolver
    result = resolver.resolve_preview(
        body.persona_name,
        body.agent_name,
        body.capability_overrides,
    )
    return result


@router.post("/sync", summary="Resolve and sync to gateway")
async def resolve_and_sync(body: SyncRequest, request: Request):
    """
    Resolve a persona + agent, register the skill/MCPs with the gateway,
    and optionally attach to a session.
    """
    resolver = request.app.state.resolver
    gateway_sync = request.app.state.gateway_sync

    if gateway_sync is None:
        raise HTTPException(status_code=503, detail="Gateway sync not configured")

    from src.resolver.persona_resolver import ResolutionError
    try:
        resolved = resolver.resolve(
            body.persona_name,
            body.agent_name,
            body.capability_overrides,
            body.model_override,
            body.mode_override,
        )
    except ResolutionError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Register with gateway
    try:
        sync_result = await gateway_sync.sync_resolved_persona(resolved)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gateway sync failed: {e}")

    result = {
        "resolved": {
            "skill_name": resolved.skill_name,
            "persona_name": resolved.persona_name,
            "agent_name": resolved.agent_name,
            "capabilities": resolved.capability_names,
            "mcps": [m.name for m in resolved.mcps],
        },
        "gateway_sync": sync_result,
    }

    # Optionally attach to session
    if body.session_id:
        try:
            attach_result = await gateway_sync.attach_to_session(body.session_id, resolved)
            result["session_attach"] = attach_result
        except Exception as e:
            result["session_attach_error"] = str(e)

    return result
