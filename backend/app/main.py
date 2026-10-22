import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.csrf import CsrfHeaderMiddleware
from app.core.events import hub
from app.setup.router import router as setup_router
from app.teams.router import router as teams_router
from app.users.router import admin_router as admin_users_router
from app.users.router import users_router
from app.audit.router import router as audit_router
from app.org.router import router as org_router
from app.projects.router import router as projects_router
from app.realtime.router import router as realtime_router
from app.sprints.router import router as sprints_router
from app.tasks.activity import router as activity_router
from app.tasks.router import router as tasks_router


log = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await hub.start(get_settings().database_url)
    try:
        await asyncio.wait_for(hub.ready.wait(), timeout=10)
    except TimeoutError:
        log.error("event hub not connected yet; live updates start once the database is reachable")
    yield
    await hub.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="MegooColab",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.add_middleware(CsrfHeaderMiddleware)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(setup_router)
    app.include_router(auth_router)
    app.include_router(admin_users_router)
    app.include_router(users_router)
    app.include_router(org_router)
    app.include_router(audit_router)
    app.include_router(teams_router)
    app.include_router(projects_router)
    app.include_router(tasks_router)
    app.include_router(activity_router)
    app.include_router(sprints_router)
    app.include_router(realtime_router)
    return app


app = create_app()
