import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app.agents.router import admin_router as admin_agents_router
from app.agents.router import project_agents_router
from app.agents.router import router as agents_router
from app.audit.router import router as audit_router
from app.auth.router import router as auth_router
from app.auth.tokens_router import router as tokens_router
from app.core.config import get_settings
from app.core.csrf import CsrfHeaderMiddleware
from app.core.events import hub
from app.org.router import router as org_router
from app.projects.router import router as projects_router
from app.realtime.router import router as realtime_router
from app.runner.router import router as runner_router
from app.agent_runs.router import router as agent_runs_router
from app.setup.router import router as setup_router
from app.sprints.router import router as sprints_router
from app.tasks.activity import router as activity_router
from app.tasks.router import router as tasks_router
from app.teams.router import router as teams_router
from app.users.router import admin_router as admin_users_router
from app.users.router import users_router

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
EXAMPLE_SECRET_KEY = "CHANGE_ME_generate_with_openssl_rand_hex_32"
MIN_SECRET_KEY_LENGTH = 16


def validate_secret_key(key: str) -> None:
    if key == EXAMPLE_SECRET_KEY or len(key) < MIN_SECRET_KEY_LENGTH:
        raise RuntimeError(
            "SECRET_KEY is missing, too short or still the example value. "
            "Generate one with `openssl rand -hex 32` and set it in .env."
        )


def run_migrations() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    validate_secret_key(settings.secret_key)
    if settings.run_migrations_on_startup:
        # env.py uses asyncio.run(), so run it off the server's event loop
        await asyncio.to_thread(run_migrations)
    await hub.start(settings.database_url)
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

    for router in (
        setup_router,
        auth_router,
        tokens_router,
        admin_users_router,
        users_router,
        org_router,
        audit_router,
        teams_router,
        projects_router,
        agents_router,
        project_agents_router,
        admin_agents_router,
        tasks_router,
        activity_router,
        sprints_router,
        realtime_router,
        runner_router,
        agent_runs_router,
    ):
        app.include_router(router)
    return app


app = create_app()
