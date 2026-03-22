"""FastAPI application entrypoint with lifecycle management."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.agents.gateway_client import GatewayClient
from app.agents.workspace import WorkspaceManager
from app.api.router import api_router
from app.api.websocket import handle_workflow_websocket
from app.config import settings
from app.core.orchestrator import WorkflowOrchestrator
from app.persistence.database import (
    async_session_factory,
    close_db,
    init_db,
)
from app.persistence.repositories import Repository
from app.streaming.event_bus import EventBus
from app.streaming.session_snapshot import GatewaySessionSnapshotStore

logger = structlog.get_logger(__name__)

# Configure structlog
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    logger.info("app.startup")

    # Initialize database tables
    try:
        await init_db()
        logger.info("database.tables_created")
    except Exception as e:
        logger.exception("database.init_failed", error=str(e))
        raise

    # Initialize Gateway Client
    try:
        logger.info("gateway_client.init")
        gateway = GatewayClient(
            ws_url=settings.gateway_ws_url,
            http_url=settings.gateway_http_url,
            reconnect_max_attempts=settings.gateway_reconnect_max_attempts,
            reconnect_base_delay=settings.gateway_reconnect_base_delay,
        )
        await gateway.connect()
        logger.info("gateway_client.connected")
    except Exception as e:
        logger.exception("gateway_client.connection_failed", error=str(e))
        raise

    # Initialize shared components
    gateway_session_snapshots = GatewaySessionSnapshotStore()
    event_bus = EventBus(
        queue_size=1000,
        session_snapshot_store=gateway_session_snapshots,
    )
    workspace_manager = WorkspaceManager(base_dir=settings.workspace_base_dir)

    # Create a long-lived session for the orchestrator's background tasks.
    # API endpoints create their own per-request sessions via the factory.
    orchestrator_session = async_session_factory()
    orchestrator_repo = Repository(orchestrator_session)

    orchestrator = WorkflowOrchestrator(
        gateway=gateway,
        event_bus=event_bus,
        repository=orchestrator_repo,
        workspace_manager=workspace_manager,
    )

    # Store in app state
    app.state.gateway = gateway
    app.state.event_bus = event_bus
    app.state.gateway_session_snapshots = gateway_session_snapshots
    app.state.workspace_manager = workspace_manager
    app.state.orchestrator = orchestrator
    app.state.session_factory = async_session_factory

    # Initialize ID counter from existing workflows in DB to avoid collisions on restart.
    try:
        init_session = async_session_factory()
        from app.persistence.repositories import Repository as _Repo
        _r = _Repo(init_session)
        existing = await _r.list_workflows(limit=1000)
        max_id = -1
        for wf in existing:
            try:
                n = int(wf.workflow_id.split("-")[-1])
                if n > max_id:
                    max_id = n
            except (ValueError, IndexError):
                pass
        await init_session.close()
        app.state.id_counter = max_id + 1
        logger.info("id_counter.initialized", id_counter=app.state.id_counter)
    except Exception:
        app.state.id_counter = 0

    logger.info("app.startup_complete")
    yield

    # Shutdown
    logger.info("app.shutdown")

    try:
        for workflow_id, task in orchestrator._tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                logger.info("workflow_cancelled", workflow_id=workflow_id)

        await gateway.disconnect()
        logger.info("gateway_client.disconnected")
    except Exception as e:
        logger.exception("app.shutdown_error", error=str(e))

    # Close orchestrator session
    try:
        await orchestrator_session.close()
    except Exception:
        pass

    try:
        await close_db()
        logger.info("database.closed")
    except Exception as e:
        logger.exception("database.close_error", error=str(e))

    logger.info("app.shutdown_complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Research Workflow Service",
        description="Multi-agent research workflow orchestrator",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.websocket("/ws/workflows/{workflow_id}")
    async def websocket_endpoint(websocket: WebSocket, workflow_id: str) -> None:
        await handle_workflow_websocket(websocket, workflow_id)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "service": "Research Workflow Service",
            "version": "0.1.0",
            "docs": "/docs",
        }

    return app


app = create_app()


def run(host: str | None = None, port: int | None = None, reload: bool = False) -> None:
    """Run the FastAPI application with uvicorn."""
    import uvicorn

    host = host or settings.host
    port = port or settings.port
    logger.info("uvicorn.run", host=host, port=port, reload=reload)

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run(reload=settings.debug)
