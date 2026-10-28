"""The dashboard (home page): one request for every widget, and the sidebar's need-you count."""

from fastapi import APIRouter

from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.dashboard import tasks
from app.dashboard.schemas import DashboardOut, Numbers, ScopeName
from app.dashboard.scope import resolve_scope

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard")
async def dashboard(user: AuthedUser, db: DbSession, scope: ScopeName = "teams") -> DashboardOut:
    s = await resolve_scope(db, user, scope)
    return DashboardOut(
        scope=scope,
        numbers=Numbers(**await tasks.task_numbers(db, s)),
        my_tasks=await tasks.my_tasks(db, user),
        finished_daily=await tasks.finished_daily(db, s),
        projects=await tasks.projects(db, s),
    )
