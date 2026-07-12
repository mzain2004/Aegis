"""FastAPI application entrypoint for Aegis.

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
from app.routes import routers

settings = get_settings()
configure_logging(settings.log_level)
LOGGER = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown hooks for the service."""

    LOGGER.info(
        "aegis_starting",
        service="Aegis Proxy",
        version=__version__,
        environment=settings.environment,
        host=settings.proxy_host,
        port=settings.proxy_port,
    )
    app.state.settings = settings
    yield
    LOGGER.info("aegis_stopping", service="Aegis Proxy", version=__version__)


app = FastAPI(
    title="Aegis Proxy",
    version=__version__,
    description="Phase 1 foundation for a zero-trust MCP execution guard.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

for router in routers:
    app.include_router(router)


@app.get("/", tags=["system"])
async def root() -> dict[str, str]:
    """Return service metadata for basic readiness checks."""

    LOGGER.debug("root_endpoint_invoked")
    return {
        "service": "Aegis Proxy",
        "version": __version__,
        "status": "running",
    }


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    """Return a minimal health response."""

    LOGGER.debug("health_endpoint_invoked")
    return {"status": "healthy"}
