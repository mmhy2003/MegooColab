"""The dashboard (home page): one request for every widget, and the sidebar's need-you count."""

from fastapi import APIRouter

from app.auth.deps import AuthedUser
from app.auth.models import Role
from app.core.db import DbSession
from app.dashboard import activity, agents, needs, system, tasks, workflows
from app.dashboard.schemas import DashboardOut, NeedsCount, Numbers, ScopeName
from app.dashboard.scope import resolve_scope, viewer_zone

router = APIRouter(tags=["dashboard"])


@router.get("/api/dashboard")
async def dashboard(user: AuthedUser, db: DbSession, scope: ScopeName = "teams", tz: str | None = None) -> DashboardOut:
    """`tz`: the browser's IANA time zone, so "today" (due, overdue, runs today, finished per day) is the viewer's."""
    s = await resolve_scope(db, user, scope, viewer_zone(tz))
    need_rows, need_total, need_old = await needs.needs(db, s)
    stages, in_progress, workflow_projects = await workflows.stages(db, s)
    agent_rows, queued = await agents.agents(db, s), await agents.queued(db, s)
    failed, success_rate = await agents.failed_runs(db, s)
    return DashboardOut(
        scope=scope,
        numbers=Numbers(
            **await tasks.task_numbers(db, s),
            need_you=need_total, need_you_over_day=need_old,
            workflows_in_progress=in_progress, workflow_projects=workflow_projects,
            agents_working=sum(1 for a in agent_rows if a.status == "busy"),  # busy in scope, as Running now
            agents_online=sum(1 for a in agent_rows if a.status != "offline"),
            runs_queued=queued.total, failed_24h=failed, success_rate_24h=success_rate,
        ),
        needs=need_rows,
        my_tasks=await tasks.my_tasks(db, user, s.tz),
        running=await agents.running(db, s),
        queued=queued,
        agents=agent_rows,
        stages=stages,
        finished_daily=await tasks.finished_daily(db, s),
        projects=await tasks.projects(db, s),
        activity=await activity.activity(db, s),
        system=await system.system(db, s.tz) if user.role == Role.admin else None,
    )


@router.get("/api/dashboard/count")
async def needs_count(user: AuthedUser, db: DbSession) -> NeedsCount:
    """What the sidebar badge shows: the Mine scope's need-you count."""
    return NeedsCount(needs_you=await needs.count(db, await resolve_scope(db, user, "mine")))
