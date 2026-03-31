from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routers.audit import router as audit_router
from src.api.routers.auth import router as auth_router
from src.api.routers.catalogs import router as catalogs_router
from src.api.routers.consumer import router as consumer_router
from src.api.routers.project_chat import router as project_chat_router
from src.api.routers.projects import router as projects_router
from src.database.bootstrap import init_database
from src.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = app
    init_database()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router, prefix=settings.api_base_path)
    app.include_router(audit_router, prefix=settings.api_base_path)
    app.include_router(catalogs_router, prefix=settings.api_base_path)
    app.include_router(projects_router, prefix=settings.api_base_path)
    app.include_router(consumer_router, prefix=settings.api_base_path)
    app.include_router(project_chat_router, prefix=settings.api_base_path)
    return app


app = create_app()
