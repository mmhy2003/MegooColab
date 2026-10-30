import logging
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, true, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.a2a.models import Question
from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunStatus
from app.agent_runs.schemas import RunAgentOut, RunOut
from app.agent_runs.tokens import issue_run_token
from app.agents.models import Agent, AgentBinding
from app.agents.service import (
    can_use_agent,
    owner_can_access,
    publish_agents_updated,
)
from app.audit import service as audit
from app.auth.models import Role, User
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.events import Event, publish
from app.core.text import strip_nul
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.projects.models import Project, ProjectRepository
from app.runner.protocol import (
    CLOSE_UNAUTHORIZED,
    V2_START_FIELDS,
    McpAccess,
    RunCancel,
    RunFile,
    RunBranch,
    RunBranchRepo,
    RunFinished,
    RunStart,
    RunTask,
)
from app.runner.registry import BRANCH_CAPABILITY, WORKFLOW_CAPABILITY, RunnerClosed, RunnerConn, registry
from app.tasks.branches import valid_branch_name
from app.tasks.models import Task, task_watchers
from app.tasks.service import record_event
from app.workflow.models import (
    DocKind,
    DocStatus,
    RunRole,
    TaskWorkflow,
    WorkflowDocument,
)

# roles whose runs carry the approved design and plan into the worktree
DOC_ROLES = {
    RunRole.implement, RunRole.step_review, RunRole.step_fix, RunRole.final_review, RunRole.final_fix, RunRole.finish,
}
# the runner's stable failure codes, kept as a failed run's reason; any other runner error is agent_error
RUNNER_FAILURE_CODES = frozenset({
    "mcp_http_unsupported", "worktree_failed", "not_bound", "files_failed", "commit_failed", "adapter_start_failed",
    "initialize_failed", "session_failed", "prompt_failed", "invalid_run_files", "busy", "git_state_unreadable",
    "start_branch_missing", "repository_not_matched", "start_branch_fetch_failed",
})

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


async def _answering_projects(db: AsyncSession, run: AgentRun) -> set[uuid.UUID]:
    """An answering run shows on the answering project's views (its dashboard's Running now), not only its owner's."""
    target = await db.scalar(select(Question.target_project_id).where(Question.id == run.question_id))
    return {target} if target else set()


async def _announce(db: AsyncSession, task: Task, owner_id: uuid.UUID) -> None:
    """A run's status changed: refresh the task and the project's agent views."""
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
    await publish_agents_updated(db, owner_id, {task.project_id})


async def _transition(
    db: AsyncSession,
    run: AgentRun,
    to: RunStatus,
    event_kind: str,
    *,
    owner_id: uuid.UUID,
    reason: str | None = None,
    actor_id: uuid.UUID | None = None,
    summary: str | None = None,
    extra: dict | None = None,
) -> None:
    """Move a run to a terminal status, record it on the task, tell the browsers and the workflow engine.

    The single exit from `running`, so the run's MCP token dies here whichever path got us here. For a workflow
    run the caller holds the workflow lock (`_lock_workflow_of`) before the run lock."""
    run.status = to
    run.mcp_token_hash = None
    run.reason = reason
    run.finished_at = _now()
    # ADM-2: an agent session stopped, however it ended
    await audit.record(db, "agent_run.ended", actor_id=actor_id, target_type="agent_run", target_id=run.id,
                       data={"status": str(to), "reason": reason})
    if summary is not None:
        run.summary = summary
    if run.question_id is not None:
        # an answering run (§6.6): no task thread to record on; the question moves on instead
        from app.a2a import routing  # local: a2a imports this module

        await publish_agents_updated(db, owner_id, await _answering_projects(db, run))
        await routing.on_answer_run_finished(db, run)
        return
    task = await db.get(Task, run.task_id)
    data = {"run_id": str(run.id), "agent_id": str(run.agent_id), **(extra or {})}
    if reason:
        data["reason"] = reason
    await record_event(db, task, actor_id, event_kind, data)
    await _announce(db, task, owner_id)
    from app.workflow import engine  # the engine imports this module

    await engine.on_run_finished(db, run)  # a workflow run's end moves its workflow on (no-op otherwise)


async def _lock_workflow_of(db: AsyncSession, run: AgentRun) -> None:
    """For a workflow run, take its task's workflow lock before the run's own: the engine's lock order
    (app/workflow/engine.py), since ending the run moves the workflow on under both."""
    if run.workflow_role is not None:
        from app.workflow import engine

        await engine.lock_workflow(db, run.task_id)


async def _lock_question_of(db: AsyncSession, question_id: uuid.UUID | None) -> None:
    """For an answering run, take its question's lock before the run's own: the order of a human answer, a
    withdrawal and submit_answer (app/a2a/service.py), since ending the run moves the question on."""
    if question_id is not None:
        from app.a2a.models import Question  # local: a2a imports this module

        await db.execute(select(Question.id).where(Question.id == question_id).with_for_update())


async def _claim_next(db: AsyncSession, agent_id: uuid.UUID, owner_id: uuid.UUID) -> AgentRun | None:
    """Under the agent lock, mark its oldest queued run running and COMMIT, if a slot is free.

    The agent row is locked FOR NO KEY UPDATE (serialises concurrent dispatches so max_concurrent_runs
    cannot be overshot) and the run row FOR UPDATE SKIP LOCKED. A queued run whose task already has a running
    run is skipped (one active run per task; the workflow engine already refuses a second one). The commit comes before
    run_start is sent: a run the runner has can never be rolled back to queued and sent twice."""
    agent = (
        await db.execute(
            select(Agent)
            .where(Agent.id == agent_id, Agent.owner_id == owner_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if agent is None:
        await db.rollback()
        return None
    running = await db.scalar(
        select(func.count()).select_from(AgentRun).where(
            AgentRun.agent_id == agent.id, AgentRun.status == RunStatus.running
        )
    )
    run = None
    if agent.max_concurrent_runs > (running or 0):
        # a runner without workflow/1 leaves workflow and answering runs queued (they need the MCP run token); one
        # without branch/1 leaves every task run queued (it would start the task's branch from whatever is checked out)
        workflow = registry.agent_supports(agent.id, WORKFLOW_CAPABILITY)
        branch = registry.agent_supports(agent.id, BRANCH_CAPABILITY)
        task_run = AgentRun.question_id.is_(None)
        runnable = and_(
            true() if workflow else and_(AgentRun.workflow_role.is_(None), task_run),
            true() if branch else ~task_run,
        )
        sibling = aliased(AgentRun)
        task_running = (
            select(sibling.id)
            .where(sibling.task_id == AgentRun.task_id, sibling.status == RunStatus.running)
            .exists()
        )
        question_running = (
            select(sibling.id)
            .where(sibling.question_id == AgentRun.question_id, sibling.status == RunStatus.running)
            .exists()
        )
        run = (
            await db.execute(
                select(AgentRun)
                .where(AgentRun.agent_id == agent.id, AgentRun.status == RunStatus.queued, ~task_running,
                       ~question_running, runnable)
                .order_by(AgentRun.created_at, AgentRun.id)
                .limit(1)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
    if run is not None:
        run.status = RunStatus.running
        run.started_at = _now()
    await db.commit()
    return run


async def _approved_body(db: AsyncSession, task_id: uuid.UUID, kind: DocKind) -> str | None:
    return await db.scalar(
        select(WorkflowDocument.body_md)
        .where(
            WorkflowDocument.task_id == task_id,
            WorkflowDocument.kind == kind,
            WorkflowDocument.status == DocStatus.approved,
        )
        .order_by(WorkflowDocument.version.desc())
        .limit(1)
    )


async def _v2_start_fields(db: AsyncSession, run: AgentRun, task: Task, task_key: str) -> dict:
    """The run_start fields for a workflow run. Issues the run's MCP token: the caller holds the run row
    lock and sends right after, and must clear the hash again if the send fails."""
    role = RunRole(run.workflow_role)
    fields: dict = {
        "role": role.value,
        "stage": run.stage,
        "step": run.step,
        "resume_session_id": run.resume_session_ref,
        "resume_prompt": run.resume_prompt,
        "mcp": McpAccess(url=get_settings().public_url.rstrip("/") + "/api/mcp", token=issue_run_token(run)),
    }
    design = plan = None
    if role in DOC_ROLES:
        design = await _approved_body(db, task.id, DocKind.design)
        plan = await _approved_body(db, task.id, DocKind.plan)
        fields["files"] = [
            RunFile(path=f".megoocolab/{name}.md", content=body)
            for name, body in (("design", design), ("plan", plan))
            if body is not None
        ]
    if role == RunRole.finish and (await db.get(Project, task.project_id)).commit_docs_to_repo:
        fields["repo_files"] = [
            RunFile(path=f"docs/superpowers/{folder}/{task_key}-{name}.md", content=body)
            for folder, name, body in (("specs", "design", design), ("plans", "plan", plan))
            if body is not None
        ]
        fields["commit_message"] = f"docs: {task_key} design and plan"
    return fields


async def _send_start(db: AsyncSession, conn: RunnerConn, agent_id: uuid.UUID, run: AgentRun) -> bool:
    """Send run_start for a run already committed as running. False if the connection is gone, in which
    case the run goes back to queued.

    The run row stays locked from the re-check until the commit after the send, so a cancel_run that
    lands after the claim either committed first (the run is no longer running: nothing is sent) or
    waits, then finds the run in conn.run_ids and sends run_cancel after run_start."""
    await _lock_workflow_of(db, run)
    run = await _lock_run(db, run.id)
    if run is None or run.status != RunStatus.running:  # cancelled between the claim and now
        await db.commit()
        return True
    if run.question_id is not None:
        return await _send_answer_start(db, conn, agent_id, run)
    row = (
        await db.execute(
            select(Task, Project.key, AgentBinding.local_path, Agent.owner_id)
            .join(Project, Project.id == Task.project_id)
            .join(Agent, Agent.id == agent_id)
            .outerjoin(
                AgentBinding,
                (AgentBinding.project_id == Task.project_id) & (AgentBinding.agent_id == agent_id),
            )
            .where(Task.id == run.task_id)
        )
    ).one()
    task, project_key, local_path, owner_id = row
    if local_path is None:  # the binding was removed while the run waited
        await _transition(db, run, RunStatus.failed, "agent_run_failed", owner_id=owner_id, reason="agent_not_bound")
        await db.commit()
        return True
    if await db.scalar(select(Agent.id).where(Agent.id == agent_id, owner_can_access(task.project_id))) is None:
        # the owner left the project while the run waited: its task must not reach their laptop
        await _transition(db, run, RunStatus.failed, "agent_run_failed", owner_id=owner_id, reason="owner_lost_access")
        await db.commit()
        return True
    task_key = f"{project_key}-{task.number}"
    try:
        v2 = await _v2_start_fields(db, run, task, task_key) if run.workflow_role else {}
        repos = await db.execute(
            select(ProjectRepository.url, ProjectRepository.default_branch)
            .where(ProjectRepository.project_id == task.project_id)
            .order_by(ProjectRepository.created_at, ProjectRepository.id)
        )
        branch = RunBranch(
            branch_from=task.branch_from or "",
            start_branch=task.start_branch or "",
            repositories=[RunBranchRepo(url=url, default_branch=default) for url, default in repos],
        )
        message = RunStart(
            run_id=run.id,
            agent_id=agent_id,
            task=RunTask(
                key=task_key, title=task.title, description_md=task.description_md, project_key=project_key
            ),
            local_path=local_path,
            policy=run.policy,
            prompt=run.prompt,
            branch=branch,
            **v2,
        )
    except ValueError:  # e.g. the documents are too large to hand to the runner
        log.exception("run %s: building run_start failed", run.id)
        await _transition(db, run, RunStatus.failed, "agent_run_failed", owner_id=owner_id, reason="invalid_run_files")
        await db.commit()
        return True
    # a plan-2 style run keeps the v1 shape
    payload = (
        message.model_dump(mode="json")
        if run.workflow_role
        else message.model_dump(mode="json", exclude=V2_START_FIELDS)
    )
    conn.run_ids.add(run.id)
    try:
        await conn.send(payload)
    except RunnerClosed:
        conn.run_ids.discard(run.id)
        run.status = RunStatus.queued
        run.started_at = None
        run.mcp_token_hash = None
        await db.commit()
        return False
    await record_event(db, task, None, "agent_run_started", {"run_id": str(run.id), "agent_id": str(agent_id)})
    await _audit_started(db, run, owner_id)
    await _announce(db, task, owner_id)
    await db.commit()
    return True


async def _audit_started(db: AsyncSession, run: AgentRun, owner_id: uuid.UUID | None) -> None:
    """ADM-2: an agent session started (the run reached the runner)."""
    await audit.record(db, "agent_run.started", actor_id=run.requested_by, target_type="agent_run", target_id=run.id,
                       data={"agent_id": str(run.agent_id), "owner_id": str(owner_id) if owner_id else None,
                             "task_id": str(run.task_id) if run.task_id else None,
                             "question_id": str(run.question_id) if run.question_id else None,
                             "role": "answer" if run.question_id else run.workflow_role})


async def _send_answer_start(db: AsyncSession, conn: RunnerConn, agent_id: uuid.UUID, run: AgentRun) -> bool:
    """run_start for an answering run (§6.6): read-only, a synthetic task key, the run's MCP token."""
    from app.a2a import routing  # local: a2a imports this module

    owner_id = await db.scalar(select(Agent.owner_id).where(Agent.id == agent_id))
    try:
        task, local_path, v2 = await routing.start_fields(db, run)
    except routing.NotSupported as exc:
        await _transition(db, run, RunStatus.failed, "agent_run_failed", owner_id=owner_id,
                          reason=str(exc) or "not_supported")
        await db.commit()
        return True
    message = RunStart(run_id=run.id, agent_id=agent_id, task=task, local_path=local_path, policy=run.policy,
                       prompt=run.prompt, **v2)
    conn.run_ids.add(run.id)
    try:
        await conn.send(message.model_dump(mode="json"))
    except RunnerClosed:
        conn.run_ids.discard(run.id)
        run.status = RunStatus.queued
        run.started_at = None
        run.mcp_token_hash = None
        await db.commit()
        return False
    await _audit_started(db, run, owner_id)
    await publish_agents_updated(db, owner_id, await _answering_projects(db, run))
    await db.commit()
    return True


async def dispatch_pending(db: AsyncSession, owner_id: uuid.UUID) -> None:
    """Send run_start for each available agent's oldest queued runs, up to its free slots.

    Commits the session it is given (claim, then send, then record), so call it with a session of its own.
    """
    for conn in registry.conns_for_user(owner_id):  # each of the owner's machines
        await _send_pending(db, conn, owner_id)
    # a run that could not be started ends here, and its question may have gone to another owner's agent
    from app.workflow import engine  # local: the engine imports this module

    await engine.dispatch_queued(db)


async def _send_pending(db: AsyncSession, conn: RunnerConn, owner_id: uuid.UUID) -> None:
    for agent_id in sorted(conn.available):
        while True:
            run = await _claim_next(db, agent_id, owner_id)
            if run is None:
                break
            if not await _send_start(db, conn, agent_id, run):
                return  # the connection died: everything else stays queued


async def _lock_run(db: AsyncSession, run_id: uuid.UUID) -> AgentRun | None:
    return (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def cancel_run(db: AsyncSession, user: User, run: AgentRun) -> None:
    """Queued: cancelled now. Running with a live runner: run_cancel is sent and the run is closed when its
    run_finished arrives. Running with the runner gone: cancelled now."""
    agent = await db.get(Agent, run.agent_id)
    if run.question_id is not None:
        # an answering run (§6.6) has no task: its agent's owner or an admin may stop it
        if user.role != Role.admin and (agent is None or agent.owner_id != user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot_use_agent")
        await _lock_question_of(db, run.question_id)
    else:
        task = await db.get(Task, run.task_id)
        project = await db.get(Project, task.project_id)
        if not await can_use_agent(db, user, agent, project):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot_use_agent")
    await _lock_workflow_of(db, run)
    run = await _lock_run(db, run.id)
    if run.status not in ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "run_not_active")
    run.cancelled_by = user.id  # the actor of the cancelled event, whenever the run is closed
    if run.status == RunStatus.running:
        conn = registry.conn_for_run(run.id)
        if conn is not None:
            try:
                await conn.send(RunCancel(run_id=run.id))
                return
            except RunnerClosed:
                pass
    await _transition(
        db, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=agent.owner_id, actor_id=user.id
    )


async def _lock_runs_one_by_one(
    db: AsyncSession, statuses: tuple[RunStatus, ...], *where
) -> AsyncIterator[tuple[AgentRun, uuid.UUID]]:
    """Yield the runs in `statuses` that match `where`, with their agent's owner, each locked in the engine's
    order (its workflow, then the run) and in task id order. A run whose status changed meanwhile is skipped."""
    candidates = (
        await db.execute(
            select(AgentRun.id, AgentRun.task_id, AgentRun.question_id, AgentRun.workflow_role, Agent.owner_id)
            .join(Agent, Agent.id == AgentRun.agent_id)
            .where(AgentRun.status.in_(statuses), *where)
            .order_by(AgentRun.task_id, AgentRun.created_at, AgentRun.id)
        )
    ).all()
    for run_id, task_id, question_id, role, owner_id in candidates:
        if role is not None:
            from app.workflow import engine

            await engine.lock_workflow(db, task_id)
        await _lock_question_of(db, question_id)
        run = await _lock_run(db, run_id)
        if run is not None and run.status in statuses:
            yield run, owner_id


async def fail_disconnected_runs(db: AsyncSession, conn: RunnerConn) -> None:
    """The runner is gone: its running runs fail with runner_disconnected, or, if the server closed the
    socket because the token or user was revoked (4401), are cancelled with runner_unauthorized. If a newer
    connection already took over, only the runs this connection was given are touched."""
    superseded = registry.conn_for_token(conn.token_id) is not None
    async for run, owner_id in _lock_runs_one_by_one(db, (RunStatus.running,), Agent.owner_id == conn.user_id):
        if superseded and run.id not in conn.run_ids:
            continue
        if run.cancelled_by is not None:  # a user asked for the cancel: the runner going away completes it
            await _transition(
                db, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=owner_id, actor_id=run.cancelled_by
            )
        elif conn.close_code == CLOSE_UNAUTHORIZED:
            await _transition(
                db, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=owner_id, reason="runner_unauthorized"
            )
        else:
            await _transition(
                db, run, RunStatus.failed, "agent_run_failed", owner_id=owner_id, reason="runner_disconnected"
            )
            await _notify_offline(db, run)


async def _notify_offline(db: AsyncSession, run: AgentRun) -> None:
    """A task run lost its runner mid-task (NOT-1): the requester, the task's assignee and its watchers."""
    if run.task_id is None:
        return
    task = await db.get(Task, run.task_id)
    project = await db.get(Project, task.project_id)
    watchers = (await db.execute(select(task_watchers.c.user_id).where(task_watchers.c.task_id == task.id))).scalars()
    key = f"{project.key}-{task.number}"
    await notifications.notify(
        db, [run.requested_by, task.assignee_user_id, *watchers], Kind.agent_offline,
        title=f"{key}: the agent went offline mid-task", body=task.title,
        link=f"/projects/{project.key}/board?task={key}", task_id=task.id, project_id=project.id,
    )


async def fail_unclaimed_runs(db: AsyncSession, conn: RunnerConn) -> None:
    """On hello: running runs of this user that this connection was not given (left over from a server
    restart or an earlier connection) can never finish, so they fail with runner_disconnected."""
    async for run, owner_id in _lock_runs_one_by_one(db, (RunStatus.running,), Agent.owner_id == conn.user_id):
        if run.id in conn.run_ids:
            continue
        if run.cancelled_by is not None:
            await _transition(
                db, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=owner_id, actor_id=run.cancelled_by
            )
        else:
            await _transition(
                db, run, RunStatus.failed, "agent_run_failed", owner_id=owner_id, reason="runner_disconnected"
            )


async def stop_runs_before_delete(db: AsyncSession, task_ids, question_ids=()) -> None:
    """These tasks (and these questions) are about to be deleted, and their runs with them in the cascade. Queued
    runs simply go; running ones get run_cancel on the owner's runner so no agent keeps working unobserved (its
    later run_finished, for a run that no longer exists, is ignored). `task_ids` and `question_ids` are lists or
    selects of ids; answering runs belong to a question, not a task.

    The run rows are locked: a dispatch in flight finishes its send first (and the cancel follows it), and
    a queued run cannot be claimed and started before the delete commits."""
    # Lock the tasks first, FOR NO KEY UPDATE (the mode the workflow engine takes, so the two serialise): an
    # enqueue racing this delete either committed its run (seen below) or finds the task gone (404). Not FOR UPDATE:
    # that would conflict with the FOR KEY SHARE that every TaskEvent insert (FK check) takes on the task
    # while holding a run row lock, and the two sides would deadlock.
    await db.execute(
        select(Task.id).where(Task.id.in_(task_ids)).order_by(Task.id).with_for_update(key_share=True)
    )
    # then their workflows (the engine's lock order): the cascade deletes those rows too
    await db.execute(
        select(TaskWorkflow.task_id)
        .where(TaskWorkflow.task_id.in_(task_ids))
        .order_by(TaskWorkflow.task_id)
        .with_for_update()
    )
    rows = (
        await db.execute(
            select(AgentRun, Agent.owner_id, func.coalesce(Task.project_id, Question.target_project_id))
            .join(Agent, Agent.id == AgentRun.agent_id)
            .outerjoin(Task, Task.id == AgentRun.task_id)
            .outerjoin(Question, Question.id == AgentRun.question_id)
            .where(or_(AgentRun.task_id.in_(task_ids), AgentRun.question_id.in_(question_ids)),
                   AgentRun.status.in_(ACTIVE_STATUSES))
            .with_for_update(of=AgentRun)
            .execution_options(populate_existing=True)
        )
    ).all()
    affected: dict[uuid.UUID, set[uuid.UUID]] = {}
    for run, owner_id, project_id in rows:
        affected.setdefault(owner_id, set()).add(project_id)
        if run.status != RunStatus.running:
            continue
        conn = registry.conn_for_run(run.id)
        if conn is not None:
            try:
                await conn.send(RunCancel(run_id=run.id))
            except RunnerClosed:
                pass
    for owner_id, project_ids in affected.items():
        await publish_agents_updated(db, owner_id, project_ids)


async def cancel_user_runs(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Deactivation: cancel the user's queued and running runs, on their agents or requested by them.
    Running ones get a best-effort run_cancel on the agent owner's connection.

    A running run on someone else's live runner (the user only requested it) stays running until that
    runner's run_finished ends it, as with cancel_run: the runner still holds the run, so a retry sent
    sooner would find the agent busy, or share the worktree with the run being cancelled. The user's own
    runs end now: their runner's connection is being closed."""
    theirs = (Agent.owner_id == user_id) | (AgentRun.requested_by == user_id)
    async for run, owner_id in _lock_runs_one_by_one(db, ACTIVE_STATUSES, theirs):
        if run.status == RunStatus.running:
            conn = registry.conn_for_run(run.id)
            if conn is not None:
                try:
                    await conn.send(RunCancel(run_id=run.id))
                    if owner_id != user_id:
                        continue
                except RunnerClosed:
                    pass
        await _transition(db, run, RunStatus.cancelled, "agent_run_cancelled", owner_id=owner_id, reason="user_deactivated")


async def runs_out(db: AsyncSession, runs: list[AgentRun]) -> list[RunOut]:
    if not runs:
        return []
    agents = {
        a.id: a
        for a in (await db.execute(select(Agent).where(Agent.id.in_({r.agent_id for r in runs})))).scalars()
    }
    keys = {
        t_id: f"{pkey}-{num}"
        for t_id, pkey, num in await db.execute(
            select(Task.id, Project.key, Task.number)
            .join(Project, Project.id == Task.project_id)
            .where(Task.id.in_({r.task_id for r in runs}))
        )
    }
    return [
        RunOut(
            id=r.id,
            task_key=keys[r.task_id],
            agent=RunAgentOut(id=r.agent_id, name=agents[r.agent_id].name, program=agents[r.agent_id].program),
            policy=r.policy,
            status=r.status,
            workflow_role=r.workflow_role,
            step=r.step,
            reason=r.reason,
            summary=r.summary,
            created_at=r.created_at,
            started_at=r.started_at,
            finished_at=r.finished_at,
        )
        for r in runs
    ]


# ---- run updates: metadata only (BRD NFR-2) ---------------------------------

OUTSIDE_WORKTREE = "<outside worktree>"
MAX_TEXT = 4000
MAX_TITLE = 200
MAX_PLAN_ENTRIES = 50
MAX_PATH = 500
MAX_COMMAND = 100
_TOOL_KINDS = {"read", "edit", "delete", "move", "search", "execute", "think", "fetch", "other"}
_PLAN_STATUS = {"pending", "in_progress", "completed"}
_TOOL_STATUS = {"pending", "in_progress", "completed", "failed"}
_DECISIONS = {"allowed", "denied"}
_DRIVE = re.compile(r"^[A-Za-z]:")


MAX_REPOSITORY_URL = 1000


def _branch(value) -> str | None:
    return value if isinstance(value, str) and valid_branch_name(value) else None


def _pick(fields: dict) -> dict:
    return {k: v for k, v in fields.items() if v is not None}


def _text(value, limit: int) -> str | None:
    return strip_nul(value)[:limit] if isinstance(value, str) else None


def _choice(value, allowed: set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _int(value, *, non_negative: bool = False) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 or not non_negative else None


def _safe_path(value) -> str | None:
    """Relative paths without `..` are kept; anything else is replaced, never echoed."""
    if not isinstance(value, str):
        return None
    value = strip_nul(value)
    if (
        not value
        or value.startswith(("/", "\\", "~"))
        or _DRIVE.match(value)
        or ".." in value.replace("\\", "/").split("/")
    ):
        return OUTSIDE_WORKTREE
    return value[:MAX_PATH]


def _first_token(value) -> str | None:
    parts = strip_nul(value).split() if isinstance(value, str) else []
    return parts[0][:MAX_COMMAND] if parts else None


def _plan_entries(value) -> list[dict] | None:
    if not isinstance(value, list):
        return None
    return [
        _pick({"title": _text(e.get("title"), MAX_TITLE), "status": _choice(e.get("status"), _PLAN_STATUS)})
        for e in value[:MAX_PLAN_ENTRIES]
        if isinstance(e, dict)
    ]


def sanitize_update(kind: str, data: dict) -> dict | None:
    """Keep only the metadata fields allowed for this kind, within their limits. None for unknown kinds."""
    g = data.get
    match kind:
        case "message":
            return _pick({"text": _text(g("text"), MAX_TEXT)})
        case "plan":
            return _pick({"entries": _plan_entries(g("entries"))})
        case "tool":
            return _pick({
                "tool_kind": _choice(g("tool_kind"), _TOOL_KINDS),
                "title": _text(g("title"), MAX_TITLE),
                "status": _choice(g("status"), _TOOL_STATUS),
            })
        case "file_change":
            return _pick({
                "path": _safe_path(g("path")),
                "lines_added": _int(g("lines_added"), non_negative=True),
                "lines_removed": _int(g("lines_removed"), non_negative=True),
            })
        case "command":
            return _pick({"command": _first_token(g("command")), "exit_code": _int(g("exit_code"))})
        case "branch":
            return _pick({
                "start_branch": _branch(g("start_branch")),
                "default_branch": _branch(g("default_branch")),
                "repository_url": _text(g("repository_url"), MAX_REPOSITORY_URL),
            })
        case "permission":
            return _pick({
                "tool_kind": _choice(g("tool_kind"), _TOOL_KINDS),
                "title": _text(g("title"), MAX_TITLE),
                "decision": _choice(g("decision"), _DECISIONS),
                "reason": _text(g("reason"), MAX_TITLE),
            })
    return None


async def record_start_branch(db: AsyncSession, task: Task, start_branch: str, default_branch: str) -> bool:
    """The runner created the task's branch from `start_branch`; `default_branch` is the repository's. Recorded
    once: later runs, the finish run and the task page read these, so nothing moves the target afterwards. True
    when it recorded."""
    locked = (
        await db.execute(
            select(Task).where(Task.id == task.id).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one()
    if locked.start_branch is not None or not start_branch:
        return False
    locked.start_branch = start_branch
    locked.back_merge_into = default_branch if default_branch and default_branch != start_branch else None
    await record_event(db, locked, None, "branch_started",
                       {"start_branch": start_branch, "back_merge_into": locked.back_merge_into})
    return True


async def apply_update(
    db: AsyncSession, conn_user_id: uuid.UUID, run_id: uuid.UUID, seq: int, kind: str, data: dict
) -> None:
    """Store one run update as a task event. Ignored unless the run is running, belongs to this runner's
    user and seq is new. Does not commit."""
    clean = sanitize_update(kind, data)
    if clean is None:
        return
    # one conditional statement: ownership, running, and a strictly newer seq (idempotent on resend)
    claimed = (
        await db.execute(
            update(AgentRun)
            .where(
                AgentRun.id == run_id,
                AgentRun.status == RunStatus.running,
                AgentRun.last_seq < seq,
                AgentRun.agent_id.in_(select(Agent.id).where(Agent.owner_id == conn_user_id)),
            )
            .values(last_seq=seq)
            .returning(AgentRun.task_id, AgentRun.agent_id)
        )
    ).first()
    if claimed is None or claimed.task_id is None:
        return  # an answering run's progress is not stored: its answer is what counts
    task = await db.get(Task, claimed.task_id)
    if kind == "branch":  # not progress to show: where the task's branch started, recorded once
        if await record_start_branch(db, task, clean.get("start_branch") or "", clean.get("default_branch") or ""):
            await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
        return
    event = {**clean, "run_id": str(run_id), "agent_id": str(claimed.agent_id)}
    await record_event(db, task, None, f"agent_{kind}", event)
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))


async def finish_run(
    db: AsyncSession,
    conn_user_id: uuid.UUID,
    run_id: uuid.UUID,
    outcome: str,
    summary: str,
    error: str | None,
    finished: RunFinished | None = None,
) -> None:
    """The runner reports the end of a run. A running run takes the outcome; a run already terminal (e.g.
    cancelled by deactivation) keeps its status and only gets finished_at and summary if they are empty.
    Commits, then dispatches the owner's pending runs."""
    peek = (
        await db.execute(
            select(AgentRun.task_id, AgentRun.question_id, AgentRun.workflow_role).where(AgentRun.id == run_id)
        )
    ).first()
    if peek is not None and peek.workflow_role is not None:
        # the engine's lock order: the task (a completed run may move the card), its workflow, then the run
        from app.workflow import engine

        await engine.lock_task_row(db, peek.task_id)
        await engine.lock_workflow(db, peek.task_id)
    if peek is not None:
        await _lock_question_of(db, peek.question_id)
    run = await _lock_run(db, run_id)
    if run is None:  # deleted with its task: the slot it held is free, so the owner's queue moves on
        await db.rollback()
        async with SessionLocal() as dispatch_db:
            await dispatch_pending(dispatch_db, conn_user_id)
            await dispatch_db.commit()
        return
    agent = await db.get(Agent, run.agent_id)
    if agent is None or agent.owner_id != conn_user_id or run.status == RunStatus.queued:
        await db.rollback()
        return
    summary = strip_nul(summary)[:2000]
    if finished is not None:  # protocol v2: the agent session and the worktree's git state
        if finished.session_id:
            run.session_ref = finished.session_id
        if finished.git_before is not None:
            run.git_before = finished.git_before.model_dump(mode="json")
        if finished.git_after is not None:
            run.git_after = finished.git_after.model_dump(mode="json")
    if run.status == RunStatus.running:
        reason = None
        if outcome == "failed":
            # a known runner failure code is the reason; any other runner text is logged, not stored (it is not
            # allowed metadata)
            reason = error if error in RUNNER_FAILURE_CODES else "agent_error"
            log.warning("run %s failed on the runner: %.200s", run.id, strip_nul(error or ""))
        await _transition(
            db, run, RunStatus(outcome), f"agent_run_{outcome}", owner_id=agent.owner_id,
            actor_id=run.cancelled_by if outcome == "cancelled" else None,
            reason=reason, summary=summary, extra={"summary": summary},
        )
    else:
        run.finished_at = run.finished_at or _now()
        run.summary = run.summary or summary
        if run.workflow_role is not None:
            # a late report still carries the agent session (e.g. paused while the runner was away); the
            # engine stores it and, the run being handled already, changes nothing else
            from app.workflow import engine

            await engine.on_run_finished(db, run)
    if run.task_id is not None:
        # local: memory imports the task modules
        from app.memory.sources import queue_extract

        await queue_extract(db, "run", run.id)
    await db.commit()
    async with SessionLocal() as dispatch_db:
        await dispatch_pending(dispatch_db, agent.owner_id)
        await dispatch_db.commit()
    from app.workflow import engine  # local: the engine imports this module

    await engine.dispatch_queued(db)  # a question this run left unanswered may have gone to another agent
