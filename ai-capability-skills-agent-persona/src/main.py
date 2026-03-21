"""Main entrypoint — FastAPI app with lifespan for the capability service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.loader.yaml_loader import ExtensionLoader
from src.registry.extension_registry import ExtensionRegistry
from src.resolver.persona_resolver import PersonaResolver
from src.sync.gateway_sync import GatewaySync
from src.watcher.hot_reload import ExtensionWatcher
from src.persistence import ExtensionPersistence
from src.api.router import api_router, system_api_router

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown logic."""

    logger.info("starting_capability_service", port=settings.port)

    # 1. Initialize loader
    loader = ExtensionLoader(directories=[settings.defaults_dir, settings.extensions_dir])
    app.state.loader = loader

    # 2. Load all extensions
    result = loader.load_all()

    # 3. Populate registry
    registry = ExtensionRegistry()
    registry.load_from_result(result)
    app.state.registry = registry

    # 4. Initialize resolver
    resolver = PersonaResolver(registry)
    app.state.resolver = resolver

    # 5. Initialize gateway sync
    gateway_sync: GatewaySync | None = None
    if settings.gateway_http_url:
        gateway_sync = GatewaySync(
            gateway_http_url=settings.gateway_http_url,
            timeout=settings.gateway_sync_timeout_seconds,
        )
        # Check gateway connectivity (non-blocking)
        if settings.gateway_sync_on_startup:
            healthy = await gateway_sync.check_health()
            if healthy:
                logger.info("gateway_connected", url=settings.gateway_http_url)
            else:
                logger.warning("gateway_unreachable", url=settings.gateway_http_url)
    app.state.gateway_sync = gateway_sync

    # 6. Initialize persistence
    persistence: ExtensionPersistence | None = None
    if settings.persist_api_extensions:
        persistence = ExtensionPersistence(settings.api_extensions_dir)
    app.state.persistence = persistence

    # 7. Start hot-reload watcher
    watcher: ExtensionWatcher | None = None
    if settings.hot_reload_enabled:
        watcher = ExtensionWatcher(
            loader=loader,
            registry=registry,
            debounce_seconds=settings.hot_reload_debounce_seconds,
        )
        loop = asyncio.get_event_loop()
        watcher.start(loop=loop)
    app.state.watcher = watcher

    logger.info(
        "capability_service_ready",
        personas=registry.stats()["personas"],
        capabilities=registry.stats()["capabilities"],
        agent_profiles=registry.stats()["agent_profiles"],
        load_errors=len(result.errors),
    )

    yield  # App is running

    # Shutdown
    logger.info("shutting_down_capability_service")

    if watcher:
        watcher.stop()

    if gateway_sync:
        await gateway_sync.close()

    logger.info("capability_service_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="AI Capability, Skills & Agent Persona Service",
        description=(
            "Config-driven extensibility microservice for managing AI agent personas, "
            "capabilities, and skills. Integrates with the CLI Agent Gateway."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(api_router)
    app.include_router(system_api_router)

    return app


app = create_app()


def run() -> None:
    """CLI entrypoint."""
    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    run()
