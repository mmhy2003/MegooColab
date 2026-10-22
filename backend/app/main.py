from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.core.csrf import CsrfHeaderMiddleware
from app.setup.router import router as setup_router
from app.teams.router import router as teams_router
from app.users.router import admin_router as admin_users_router
from app.users.router import users_router
from app.audit.router import router as audit_router
from app.org.router import router as org_router
from app.projects.router import router as projects_router
from app.tasks.router import router as tasks_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="MegooColab",
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
    return app


app = create_app()
