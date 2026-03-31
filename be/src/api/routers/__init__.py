from __future__ import annotations

from src.api.routers.audit import router as audit_router
from src.api.routers.auth import router as auth_router
from src.api.routers.catalogs import router as catalogs_router
from src.api.routers.consumer import router as consumer_router
from src.api.routers.projects import router as projects_router

__all__ = [
    "audit_router",
    "auth_router",
    "catalogs_router",
    "consumer_router",
    "projects_router",
]
