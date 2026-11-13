"""A cron's run: an AgentRun targeting its CronRun (beside task, question and draft runs). It runs commands in a
throwaway copy of the project's default branch on the agent's machine, and reports through submit_cron_report."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunStatus
from app.agent_runs.tokens import issue_run_token
from app.agents.models import Agent, AgentBinding
from app.agents.service import owner_can_access
from app.auth.models import Role, User, UserStatus
from app.core.config import get_settings
from app.crons.models import Cron, CronMode, CronRun, CronRunStatus
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.projects.access import accessible_project_ids
from app.projects.models import Project, ProjectRepository, ProjectTeam
from app.runner.protocol import McpAccess, RunCron, RunTask
from app.teams.models import TeamMember
from app.workflow import methodology
from app.workflow.context import DOCS_NOTE, wrap_untrusted
from app.workflow.models import MethodologyVersion

DEFAULT_BRANCH = "main"
MODE_TEXT = {
    CronMode.report: "Your cron reports only: report the findings; nothing else changes.",
    CronMode.tasks: ("Your cron may open tasks: up to 5 new tasks per run for real problems not already tracked. "
                     "Check the project's open tasks with list_tasks first."),
    CronMode.kb: ("Your cron keeps one Knowledge Base document: your report's document_md replaces the whole "
                  "document."),
}
SKIP_TEXT = {
    "previous_running": "skipped: the previous run was still going",
    "missed": "skipped: MegooColab was down at that time",
    "no_agent_online": "skipped: no agent online",
    "no_agent": "skipped: no agent can work on this project",
}


class NotSupported(Exception):
    """The run cannot be started: its cron, project or agent binding is gone."""


def cron_link(project_key: str, cron_id: uuid.UUID, run_id: uuid.UUID | None = None) -> str:
    link = f"/projects/{project_key}/crons/{cron_id}"
    return f"{link}?run={run_id}" if run_id else link


async def cron_prompt(db: AsyncSession, cron: Cron, run: CronRun) -> tuple[str, MethodologyVersion]:
    version = await methodology.current(db, "cron")
    project = await db.get(Project, cron.project_id)
    previous = await db.scalar(
        select(CronRun).where(CronRun.cron_id == cron.id, CronRun.scheduled_at < run.scheduled_at,
                              CronRun.report.is_not(None))
        .order_by(CronRun.scheduled_at.desc()).limit(1)
    )
    parts = [
        version.body_md.strip(),
        DOCS_NOTE,
        f"## This run\n\nProject {project.name} ({project.key}), cron \"{cron.name}\". "
        f"This run: {run.scheduled_at:%Y-%m-%d %H:%M} UTC."
        + (f" Last report: {previous.scheduled_at:%Y-%m-%d %H:%M} UTC." if previous else " This is its first report."),
    ]
    if previous is not None:
        import json

        parts.append("## The last run's report\n\n" + wrap_untrusted("last report", json.dumps(previous.report)))
    parts += [f"## The job\n\n{cron.prompt.strip()}", f"## What your cron may do\n\n{MODE_TEXT[CronMode(cron.mode)]}"]
    return "\n\n".join(parts), version


async def start_fields(db: AsyncSession, run: AgentRun) -> tuple[RunTask, str, dict]:
    """(RunTask, local_path, v2 fields) for a cron run's run_start: a synthetic task key `CRN-<cron>` the runner keys
    the cron's own worktree on, the project's repository, and the default branch to reset it to."""
    cron_run = await db.get(CronRun, run.cron_run_id)
    cron = await db.get(Cron, cron_run.cron_id) if cron_run else None
    if cron is None:
        raise NotSupported("cron_gone")
    project = await db.get(Project, cron.project_id)
    local_path = await db.scalar(
        select(AgentBinding.local_path)
        .join(Agent, Agent.id == AgentBinding.agent_id)
        .where(AgentBinding.agent_id == run.agent_id, AgentBinding.project_id == project.id,
               owner_can_access(project.id))
    )
    if local_path is None:
        raise NotSupported("agent_not_bound")
    branch = await db.scalar(
        select(ProjectRepository.default_branch).where(ProjectRepository.project_id == project.id)
        .order_by(ProjectRepository.created_at, ProjectRepository.id).limit(1)
    )
    cron_run.status = CronRunStatus.running
    cron_run.started_at = datetime.now(UTC)
    task = RunTask(key=f"CRN-{cron.id.hex[:12]}", title=cron.name, description_md="", project_key=project.key)
    fields = {
        "role": "cron",
        "mcp": McpAccess(url=get_settings().public_url.rstrip("/") + "/api/mcp", token=issue_run_token(run)),
        "cron": RunCron(id=cron.id, branch=branch or DEFAULT_BRANCH),
    }
    return task, local_path, fields


async def project_managers(db: AsyncSession, project_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        select(User.id)
        .join(TeamMember, TeamMember.user_id == User.id)
        .join(ProjectTeam, ProjectTeam.team_id == TeamMember.team_id)
        .where(ProjectTeam.project_id == project_id, User.role == Role.manager, User.status == UserStatus.active)
    )
    return set(rows.scalars())


async def people_to_tell(db: AsyncSession, cron: Cron) -> list[uuid.UUID]:
    """The project's managers, and the cron's creator while they can still read the project."""
    people = await project_managers(db, cron.project_id)
    creator = await db.get(User, cron.created_by) if cron.created_by else None
    if creator is not None and creator.status == UserStatus.active:
        allowed = await accessible_project_ids(db, creator)  # None: an admin, every project
        if allowed is None or cron.project_id in allowed:
            people.add(creator.id)
    return sorted(people)


async def tell(db: AsyncSession, cron: Cron, run: CronRun, title: str, body: str = "") -> None:
    project = await db.get(Project, cron.project_id)
    await notifications.notify(db, await people_to_tell(db, cron), Kind.needs_you, title=title, body=body,
                               link=cron_link(project.key, cron.id, run.id), project_id=project.id)


async def tell_outcome(db: AsyncSession, cron: Cron, run: CronRun) -> None:
    """The notifications a finished (or skipped) run sends, per its cron's settings."""
    findings = len((run.report or {}).get("findings") or [])
    if run.status in (CronRunStatus.failed, CronRunStatus.skipped):
        if cron.notify_failures:
            word = "failed" if run.status == CronRunStatus.failed else "skipped"
            await tell(db, cron, run, f"Cron {cron.name} {word}", SKIP_TEXT.get(run.skip_reason or "", run.skip_reason or ""))
    elif findings and cron.notify_findings:
        await tell(db, cron, run, f"Cron {cron.name}: {findings} finding{'s' if findings != 1 else ''}",
                   (run.report or {}).get("summary", ""))
    elif cron.notify_every:
        await tell(db, cron, run, f"Cron {cron.name} ran", (run.report or {}).get("summary", ""))


async def on_run_finished(db: AsyncSession, run: AgentRun) -> None:
    """The cron's run ended: what came of it, and who is told."""
    cron_run = await db.get(CronRun, run.cron_run_id)
    if cron_run is None:
        return
    cron = await db.get(Cron, cron_run.cron_id)
    before = (run.git_before or {}).get("head")
    after = (run.git_after or {}).get("head")
    cron_run.commit = before or cron_run.commit
    cron_run.finished_at = datetime.now(UTC)
    submitted = bool((cron_run.report or {}).get("submitted"))
    if before and after and before != after:
        cron_run.status, cron_run.skip_reason = CronRunStatus.failed, "made_a_commit"
    elif cron_run.skip_reason == "timed_out":
        cron_run.status = CronRunStatus.failed
    elif run.status == RunStatus.cancelled and cron_run.skip_reason == "no_agent_online":
        cron_run.status = CronRunStatus.skipped
    elif run.status == RunStatus.completed and submitted:
        cron_run.status = CronRunStatus.done
    elif run.status == RunStatus.completed:
        cron_run.status, cron_run.skip_reason = CronRunStatus.failed, "no_report"
    else:
        cron_run.status = CronRunStatus.failed
        cron_run.skip_reason = run.reason or ("cancelled" if run.status == RunStatus.cancelled else "agent_error")
    if cron is not None:
        await tell_outcome(db, cron, cron_run)
