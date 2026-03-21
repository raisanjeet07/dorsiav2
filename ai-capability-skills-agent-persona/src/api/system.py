"""System endpoints: health, stats, reload."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


@router.get("/health", summary="Service health check")
async def health(request: Request):
    registry = request.app.state.registry
    gateway_sync = request.app.state.gateway_sync

    gateway_healthy = False
    if gateway_sync:
        gateway_healthy = await gateway_sync.check_health()

    return {
        "status": "ok",
        "registry": registry.stats(),
        "gateway_reachable": gateway_healthy,
    }


@router.get("/stats", summary="Registry statistics")
async def stats(request: Request):
    registry = request.app.state.registry
    return registry.stats()


@router.post("/reload", summary="Hot-reload all extensions from disk")
async def reload_extensions(request: Request):
    loader = request.app.state.loader
    registry = request.app.state.registry

    result = loader.load_all()
    registry.load_from_result(result)

    return {
        "reloaded": True,
        "summary": result.summary(),
        "errors": result.errors,
    }
