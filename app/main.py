"""FastAPI application entrypoint for Veto Ops.

Phase 1 provides the application shell, settings, structured logging, router
registration, and health endpoints only.

TODO: add zero-trust proxy middleware, MCP request interception, approval
orchestration, and upstream forwarding in later phases.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.dependencies import get_logger
from app.logger import configure_logging
from app.monitoring.tracing import TraceMiddleware
from app.routes import routers

settings = get_settings()
configure_logging(settings.log_level)
LOGGER = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown hooks for the service."""

    LOGGER.info(
        "veto_ops_starting",
        service="Veto Ops Proxy",
        version=__version__,
        environment=settings.environment,
        host=settings.proxy_host,
        port=settings.proxy_port,
    )
    app.state.settings = settings

    # Bootstrap default operator database records
    from app.database.bootstrap import bootstrap_database
    from app.database.connection import SessionLocal
    from app.database.services import CleanupService
    from app.monitoring.cleanup_scheduler import cleanup_scheduler

    try:
        with SessionLocal() as db:
            bootstrap_database(db)
            # Perform startup database cleanup
            cleanup_service = CleanupService(db)
            results = cleanup_service.run_cleanup()
            db.commit()
            LOGGER.info("startup_cleanup_completed", results=results)
    except Exception as e:
        LOGGER.error("database_bootstrap_and_cleanup_failed", error=str(e))

    # Start periodic background cleanup scheduler
    cleanup_scheduler.start()

    yield
    # Stop background cleanup scheduler on shutdown
    await cleanup_scheduler.stop()
    LOGGER.info("veto_ops_stopping", service="Veto Ops Proxy", version=__version__)


app = FastAPI(
    title="Veto Ops Proxy",
    version=__version__,
    description="Phase 1 foundation for a zero-trust MCP execution guard.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Add structured trace, correlation ID, and metrics middleware
app.add_middleware(TraceMiddleware)

for router in routers:
    app.include_router(router)


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    """Return service metadata for basic readiness checks."""

    LOGGER.debug("root_endpoint_invoked")
    return {
        "service": "Veto Ops Proxy",
        "version": __version__,
        "status": "running",
    }
