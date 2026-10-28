"""The dashboard (home page): one request for every widget, and the sidebar's need-you count."""

from fastapi import APIRouter

from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.dashboard import needs, tasks, workflows
from app.dashboard.schemas import DashboardOut, NeedsCount, Numbers, ScopeName
from app.dashboard.scope import resolve_scope

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard")
async def dashboard(user: AuthedUser, db: DbSession, scope: ScopeName = "teams") -> DashboardOut:
    s = await resolve_scope(db, user, scope)
    need_rows, need_total, need_old = await needs.needs(db, s)
    stages, in_progress, workflow_projects = await workflows.stages(db, s)
    return DashboardOut(
        scope=scope,
        numbers=Numbers(
            **await tasks.task_numbers(db, s),
            need_you=need_total, need_you_over_day=need_old,
            workflows_in_progress=in_progress, workflow_projects=workflow_projects,
        ),
        needs=need_rows,
        my_tasks=await tasks.my_tasks(db, user),
        stages=stages,
        finished_daily=await tasks.finished_daily(db, s),
        projects=await tasks.projects(db, s),
    )


@router.get("/api/dashboard/count")
async def needs_count(user: AuthedUser, db: DbSession) -> NeedsCount:
    """What the sidebar badge shows: the Mine scope's need-you count."""
    _rows, total, _old = await needs.needs(db, await resolve_scope(db, user, "mine"), limit=0)
    return NeedsCount(needs_you=total)
