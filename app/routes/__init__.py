"""Route registration helpers for the Aegis API surface.

TODO: expand the router registry when health, approval, and proxy subroutes
grow beyond the initial skeleton.
"""

from __future__ import annotations

from app.logger import get_logger
from app.routes.approve import router as approve_router
from app.routes.proxy import router as proxy_router

LOGGER = get_logger(__name__)

routers = (proxy_router, approve_router)

__all__ = ["approve_router", "proxy_router", "routers"]
