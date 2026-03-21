"""Aggregate all API routers."""

from fastapi import APIRouter

from app.api import workflows

# Create main router
api_router = APIRouter()

# Include all sub-routers
api_router.include_router(workflows.router)
