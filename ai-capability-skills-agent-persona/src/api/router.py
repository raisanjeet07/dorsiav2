"""Top-level API router — aggregates all sub-routers."""

from fastapi import APIRouter

from src.api.personas import router as personas_router
from src.api.capabilities import router as capabilities_router
from src.api.agents import router as agents_router
from src.api.resolve import router as resolve_router
from src.api.system import router as system_router

api_router = APIRouter(prefix="/api/v1/extensions")
api_router.include_router(personas_router)
api_router.include_router(capabilities_router)
api_router.include_router(agents_router)
api_router.include_router(resolve_router)

# System routes are at /api/v1/ (no /extensions prefix)
system_api_router = APIRouter(prefix="/api/v1")
system_api_router.include_router(system_router)
