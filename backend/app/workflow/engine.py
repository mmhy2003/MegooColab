"""Workflow engine: the per-task state machine (BRD §6.5, WF-1..WF-8).

It starts, pauses and resumes workflows, creates every workflow run (the only way an agent runs on a task),
and reacts when a run ends (`on_run_finished`). Role-specific outcome handling is a registry
(`ROLE_HANDLERS`) that later stages extend; the board rules live in app/workflow/board.py.

Lock order. Every transaction that changes workflow state or ends a workflow run takes its locks in this order:
  1. the `tasks` row, FOR NO KEY UPDATE: only transactions that may UPDATE the task (board moves, the engine's
     entry points, finish_run). It is the mode stop_runs_before_delete takes, so these serialise with a delete.
  2. the `task_workflows` row, FOR UPDATE (`lock_workflow`).
  3. `agent_runs` rows, FOR UPDATE (`_lock_run` in app/agent_runs/service.py).
TaskEvent inserts take FOR KEY SHARE on the task (the FK check), which conflicts with none of these. A
transaction touching several tasks takes them in task id order (stop_runs_before_delete locks all tasks, then
all workflows, then all runs; the runner-loss paths go run by run in task id order, without step 1).
"""

import contextvars
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunPolicy, RunStatus
from app.agent_runs.service import cancel_run, dispatch_pending
from app.agents.models import Agent
from app.agents.service import can_use_agent, is_usable_binding, publish_agents_updated
from app.audit import service as audit
from app.auth.models import User, UserStatus
from app.core.db import SessionLocal
from app.core.events import Event, publish
from app.projects.access import can_manage_project, project_team_ids
from app.projects.models import BoardColumn, Project
from app.tasks.models import Task, TaskType
from app.tasks.service import apply_column, end_position, record_event
from app.teams.service import user_team_ids
from app.workflow.context import FIX_ROLES, MAX_PROMPT_CHARS, build_prompt, resume_text
from app.workflow.models import (
    DocKind,
    DocStatus,
    Driver,
    Enforcement,
    FinishingOption,
    Needs,
    QuestionStatus,
    ReviewScope,
    RunRole,
    Stage,
    StepReview,
    TaskWorkflow,
    WorkflowDocument,
    WorkflowQuestion,
    WorkflowStatus,
)

log = logging.getLogger(__name__)

# ---- roles (AGT-14) -------------------------------------------------------------

ROLE_POLICY: dict[RunRole, RunPolicy] = {
    RunRole.brainstorm: RunPolicy.read_only,
    RunRole.plan: RunPolicy.read_only,
    RunRole.implement: RunPolicy.workspace,
    RunRole.step_review: RunPolicy.read_only,
    RunRole.step_fix: RunPolicy.workspace,
    RunRole.final_review: RunPolicy.read_only,
    RunRole.final_fix: RunPolicy.workspace,
    RunRole.finish: RunPolicy.workspace,
}
READ_ONLY_ROLES = {role for role, policy in ROLE_POLICY.items() if policy == RunPolicy.read_only}
FRESH_ROLES = {RunRole.step_review, RunRole.final_review, RunRole.final_fix, RunRole.finish}  # never resumed
# the role a stage runs when there is no earlier run to repeat
STAGE_ROLE: dict[Stage, RunRole] = {
    Stage.brainstorm: RunRole.brainstorm,
    Stage.design: RunRole.brainstorm,
    Stage.plan: RunRole.plan,
    Stage.build: RunRole.implement,
    Stage.review: RunRole.final_review,
    Stage.done: RunRole.finish,
}

WORKFLOW_TYPES = (TaskType.story, TaskType.task, TaskType.bug)  # what a workflow can run on
MAX_FAILURES = 3  # consecutive failed runs before escalating retries_exhausted (AGT-19)
ACTIVE = (WorkflowStatus.running, WorkflowStatus.waiting_human)
CONTINUE_TEXT = "Your previous run ended before it finished. Continue the same work from where you left off."
NUDGE_TEXT = {
    RunRole.plan: (
        "Your last run ended without asking a question or submitting your plan. Continue: ask the human "
        "with ask_human, or submit your plan with submit_plan."
    ),
}


def session_key(role: RunRole, step: int | None) -> str | None:
    """The `wf.sessions` key a role resumes and stores; None for roles that always start fresh."""
    role = RunRole(role)
    if role in FRESH_ROLES:
        return None
    if role in (RunRole.implement, RunRole.step_fix):
        return f"implement:{step}"
    return role.value


def _now() -> datetime:
    return datetime.now(UTC)


# ---- locks and small helpers ------------------------------------------------------


async def lock_task_row(db: AsyncSession, task_id: uuid.UUID) -> bool:
    """Lock 1 (FOR NO KEY UPDATE). False if the task is gone."""
    found = await db.scalar(select(Task.id).where(Task.id == task_id).with_for_update(key_share=True))
    return found is not None


async def lock_workflow(db: AsyncSession, task_id: uuid.UUID) -> TaskWorkflow | None:
    """Lock 2. Re-locking in the same transaction is a no-op (pending changes are flushed first)."""
    return (
        await db.execute(
            select(TaskWorkflow)
            .where(TaskWorkflow.task_id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def lock_task(db: AsyncSession, task: Task, *, create: bool = False) -> TaskWorkflow | None:
    """Locks 1 and 2 for an engine entry point; 404 if the task was deleted meanwhile."""
    if not await lock_task_row(db, task.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task_not_found")
    if create:
        await db.execute(
            insert(TaskWorkflow)
            .values(
                task_id=task.id, driver=Driver.runner, stage=Stage.brainstorm, status=WorkflowStatus.idle,
                enforcement=Enforcement.enforced, review_round=0, failures=0, nudged=False, sessions={},
            )
            .on_conflict_do_nothing(index_elements=["task_id"])
        )
    return await lock_workflow(db, task.id)


async def record_workflow_event(db: AsyncSession, task: Task, actor_id: uuid.UUID | None, kind: str, data: dict | None = None) -> None:
    await record_event(db, task, actor_id, kind, data or {})
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))


async def _manages(db: AsyncSession, user: User, project: Project) -> bool:
    return can_manage_project(user, await project_team_ids(db, project.id), await user_team_ids(db, user.id))


async def require_actor(db: AsyncSession, user: User, task: Task, wf: TaskWorkflow | None = None) -> None:
    """WF-6: the owner of the task's agent, a manager of the project, or an admin; else 403."""
    agent_id = task.assignee_agent_id or (wf.agent_id if wf else None)
    agent = await db.get(Agent, agent_id) if agent_id else None
    if agent is not None and agent.owner_id == user.id:
        return
    if wf is not None and wf.driver == Driver.connect_only and task.assignee_user_id == user.id:
        return  # connect-only (AGT-32): the assignee owns the agent working through their personal token
    if not await _manages(db, user, await db.get(Project, task.project_id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot_act_on_workflow")


async def _usable_agent(db: AsyncSession, user: User, task: Task) -> Agent:
    """Start and resume (AGT-5): the task's agent, usable by this user and bound to the project."""
    if task.assignee_agent_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "task_not_assigned_to_agent")
    agent = await db.get(Agent, task.assignee_agent_id)
    project = await db.get(Project, task.project_id)
    if agent is None or not await can_use_agent(db, user, agent, project):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot_use_agent")
    if not await is_usable_binding(db, agent.id, project.id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_not_bound")
    return agent


async def _require_can_use(db: AsyncSession, user: User, task: Task, wf: TaskWorkflow) -> None:
    """Pause (AGT-5): may this user use the workflow's agent? With the agent gone, managers and admins may."""
    agent_id = task.assignee_agent_id or wf.agent_id
    agent = await db.get(Agent, agent_id) if agent_id else None
    project = await db.get(Project, task.project_id)
    allowed = await can_use_agent(db, user, agent, project) if agent else await _manages(db, user, project)
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot_use_agent")


async def latest_run(db: AsyncSession, task_id: uuid.UUID) -> AgentRun | None:
    """The task's newest workflow run. Runs are created under the workflow lock with an explicit created_at,
    so this order is the creation order."""
    return (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.task_id == task_id, AgentRun.workflow_role.is_not(None))
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def active_run(db: AsyncSession, task_id: uuid.UUID) -> AgentRun | None:
    return (
        await db.execute(
            select(AgentRun).where(AgentRun.task_id == task_id, AgentRun.status.in_(ACTIVE_STATUSES)).limit(1)
        )
    ).scalar_one_or_none()


# ---- dispatch after commit ----------------------------------------------------------

_DISPATCH_KEY = "workflow_dispatch_owners"


async def dispatch_queued(db: AsyncSession) -> None:
    """Commit, then hand the runs this session queued to their owners' runners (each dispatch in a session of
    its own, as dispatch_pending commits). Call it at the end of a request that may have enqueued.

    `enqueue` never dispatches itself: it may run inside on_run_finished, within a run's ending transaction,
    whose own caller dispatches once it has committed."""
    owners = db.info.pop(_DISPATCH_KEY, set())
    if not owners:
        return
    await db.commit()
    for owner_id in sorted(owners):
        async with SessionLocal() as s:
            await dispatch_pending(s, owner_id)
            await s.commit()


# ---- state changes --------------------------------------------------------------------


async def set_stage(db: AsyncSession, wf: TaskWorkflow, task: Task, to: Stage) -> None:
    """Only the engine changes the stage (WF-3). Resets the nudge; the plan stage starts a fresh session."""
    to = Stage(to)
    if wf.stage == to:
        return
    frm = wf.stage
    from app.workflow import questions  # local: questions imports this module

    await questions.retire_answers(db, wf.task_id)  # a pending answer belongs to the stage it was asked in
    wf.stage = to
    wf.nudged = False
    if to == Stage.plan:
        wf.sessions.pop(session_key(RunRole.plan, None), None)
    await record_workflow_event(db, task, None, "workflow.stage", {"from": str(frm), "to": str(to)})


def set_step(wf: TaskWorkflow, n: int | None) -> None:
    """Advance the build step; the nudge is per step."""
    if wf.current_step != n:
        wf.current_step = n
        wf.nudged = False


def wait_for(wf: TaskWorkflow, needs: Needs) -> None:
    wf.status = WorkflowStatus.waiting_human
    wf.needs = Needs(needs)


async def escalate(db: AsyncSession, wf: TaskWorkflow, reason: str) -> None:
    task = await db.get(Task, wf.task_id)
    wait_for(wf, Needs.escalation)
    wf.escalation_reason = reason
    await record_workflow_event(db, task, None, "workflow.escalated", {"reason": reason})


async def _latest_findings(db: AsyncSession, task_id: uuid.UUID, role: RunRole, step: int | None) -> list[dict]:
    scope = ReviewScope.step if role == RunRole.step_fix else ReviewScope.final
    stmt = select(StepReview.findings).where(StepReview.task_id == task_id, StepReview.scope == scope)
    if scope == ReviewScope.step:
        stmt = stmt.where(StepReview.step == step)
    found = await db.scalar(stmt.order_by(StepReview.round.desc(), StepReview.created_at.desc()).limit(1))
    return list(found or [])


async def _previous_findings(db: AsyncSession, wf: TaskWorkflow, role: RunRole, step: int | None) -> list[dict] | None:
    """A re-review (round > 1 of a step review, round 2 of the final review) sees the round before's findings."""
    if wf.review_round <= 1 or role not in (RunRole.step_review, RunRole.final_review):
        return None
    scope = ReviewScope.step if role == RunRole.step_review else ReviewScope.final
    stmt = select(StepReview.findings).where(
        StepReview.task_id == wf.task_id, StepReview.scope == scope, StepReview.round < wf.review_round
    )
    if scope == ReviewScope.step:
        stmt = stmt.where(StepReview.step == step)
    found = await db.scalar(stmt.order_by(StepReview.round.desc(), StepReview.created_at.desc()).limit(1))
    return list(found) if found else None


# When the Done stage begins, finish.enter_done freezes the effective option into wf.finishing_override and records
# wf.finish_requires_human_review, so later project changes do not affect the run.
def requires_human_review(project: Project, wf: TaskWorkflow) -> bool:
    """The frozen requirement; a Done-stage row from before it existed falls back to the live setting."""
    if wf.stage == Stage.done and wf.finish_requires_human_review is not None:
        return wf.finish_requires_human_review
    return bool(project.require_human_code_review)


def finishing_option(project: Project, wf: TaskWorkflow) -> FinishingOption:
    """WF-6a/6b: human code review forces a pull request; else the task's override; else the project's option."""
    if wf.stage == Stage.done and wf.finish_requires_human_review is not None:  # frozen when Done began
        return FinishingOption(wf.finishing_override)
    if project.require_human_code_review:
        return FinishingOption.pull_request
    return FinishingOption(wf.finishing_override or project.finishing_option)


async def enqueue(
    db: AsyncSession,
    wf: TaskWorkflow,
    task: Task,
    role: RunRole | str,
    *,
    step: int | None = None,
    resume_kind: str | None = None,
    payload=None,
    requested_by: uuid.UUID,
    resume_prompt: str | None = None,
    resume_session_ref: str | None = None,
) -> AgentRun:
    """Queue the next workflow run. The caller holds the workflow lock; dispatch happens after commit
    (`dispatch_queued`, or the run-ending path's own dispatch).

    Resuming roles continue their stored session (`wf.sessions`) with `resume_text(resume_kind, payload)`, or
    an explicit `resume_prompt`; without a stored session the run starts fresh from its full prompt. Fix roles
    get the latest review's findings in their prompt."""
    role = RunRole(role)
    if wf.driver != Driver.runner:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_not_runner_driven")
    if task.assignee_agent_id is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "task_not_assigned_to_agent")
    if await active_run(db, task.id) is not None:  # one active run per task: they would share its worktree
        raise HTTPException(status.HTTP_409_CONFLICT, "task_has_active_run")
    agent = await db.get(Agent, task.assignee_agent_id)
    findings = await _latest_findings(db, task.id, role, step) if role in FIX_ROLES else None
    key_override = "design_revision" if role == RunRole.brainstorm and wf.stage == Stage.design else None
    extra = None
    if role == RunRole.finish:
        option = finishing_option(await db.get(Project, task.project_id), wf)
        extra = [f"## Finishing\nFinishing option: {option.value}"]
    prompt, meth = await build_prompt(
        db, task, role, step=step, findings=findings, key_override=key_override,
        previous_findings=await _previous_findings(db, wf, role, step), extra_sections=extra,
    )
    key = session_key(role, step)
    # a fresh-by-design role has no stored session; an answer resumes the asking run's own (resume_session_ref)
    session = resume_session_ref or (wf.sessions.get(key) if key else None)
    text = resume_text(resume_kind, payload) if resume_kind else resume_prompt
    if resume_kind == "nudge" and not session:
        # nothing to resume: the reminder goes at the end of the full prompt, within its size limit
        note = "\n\n## Reminder\n" + text
        prompt += note[: max(0, MAX_PROMPT_CHARS - len(prompt))]
    run = AgentRun(
        task_id=task.id,
        agent_id=agent.id,
        requested_by=requested_by,
        policy=ROLE_POLICY[role],
        prompt=prompt,
        status=RunStatus.queued,
        workflow_role=role,
        stage=wf.stage,
        step=step,
        resume_session_ref=session,
        resume_prompt=text if session else None,
        methodology_version_id=meth.id,
        created_at=_now(),  # not the transaction's start time: latest_run relies on creation order
    )
    db.add(run)
    await db.flush()
    wf.status = WorkflowStatus.running
    wf.needs = None
    wf.agent_id = agent.id
    await record_event(db, task, None, "agent_run_queued", {
        "run_id": str(run.id), "agent_id": str(agent.id), "policy": run.policy, "role": role.value, "step": step,
    })
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
    await publish_agents_updated(db, agent.owner_id, {task.project_id})
    db.info.setdefault(_DISPATCH_KEY, set()).add(agent.owner_id)
    return run


async def hand_to_agent(
    db: AsyncSession, wf: TaskWorkflow, task: Task, role: RunRole | str, *, step: int | None = None, **enqueue_args
) -> AgentRun | None:
    """Give the work back to the agent after a human decision (an answer, an approval, a rejection). A
    runner-driven workflow queues the role's run (`enqueue`). A connect_only one has no run to queue (its agent
    works through its owner's personal MCP token, AGT-32): it simply runs again, and the agent learns what to
    do next from get_workflow."""
    if wf.driver == Driver.connect_only:
        wf.status = WorkflowStatus.running
        wf.needs = None
        return None
    return await enqueue(db, wf, task, role, step=step, **enqueue_args)


async def rerun(
    db: AsyncSession,
    wf: TaskWorkflow,
    task: Task,
    *,
    requested_by: uuid.UUID,
    last: AgentRun | None = None,
    resume_kind: str | None = None,
    payload=None,
) -> AgentRun:
    """Run the current role and step again: a retry, a nudge, a resume after a pause or an escalation retry.
    A message the last run may never have processed (it did not complete) is carried over."""
    last = last or await latest_run(db, task.id)
    if last is not None:
        role, step = RunRole(last.workflow_role), last.step
    else:
        role = STAGE_ROLE[wf.stage]
        step = wf.current_step if role == RunRole.implement else None
    text = None
    if resume_kind is None:
        carried = last.resume_prompt if last is not None and last.status != RunStatus.completed else None
        text = carried or CONTINUE_TEXT
    return await enqueue(
        db, wf, task, role, step=step, resume_kind=resume_kind, payload=payload, requested_by=requested_by,
        resume_prompt=text,
    )


async def owner_id(db: AsyncSession, run: AgentRun) -> uuid.UUID:
    return await db.scalar(select(Agent.owner_id).where(Agent.id == run.agent_id))


async def _owner_deactivated(db: AsyncSession, run: AgentRun) -> bool:
    owner_status = await db.scalar(
        select(User.status).join(Agent, Agent.owner_id == User.id).where(Agent.id == run.agent_id)
    )
    return owner_status == UserStatus.deactivated


# ---- start / pause / resume (AGT-5: can_use_agent) -----------------------------------


async def start(db: AsyncSession, user: User, task: Task) -> TaskWorkflow:
    """Start the agent-driven workflow at brainstorm with a fresh brainstorm run."""
    if task.type not in WORKFLOW_TYPES:  # plan subtasks cannot hang under an epic or a subtask
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "workflow_not_supported_for_type")
    agent = await _usable_agent(db, user, task)
    wf = await lock_task(db, task, create=True)
    # again under the task lock: a concurrent PATCH may have made it an epic since `task` was loaded
    if await db.scalar(select(Task.type).where(Task.id == task.id)) not in WORKFLOW_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "workflow_not_supported_for_type")
    if wf.status in (*ACTIVE, WorkflowStatus.paused):
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_active")
    if wf.status == WorkflowStatus.finished:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_finished")
    wf.driver = Driver.runner
    wf.stage = Stage.brainstorm
    wf.needs = None
    wf.enforcement = Enforcement.enforced
    wf.agent_id = agent.id
    wf.current_step = None
    wf.review_round = 0
    wf.failures = 0
    wf.nudged = False
    wf.escalation_reason = None
    wf.sessions.clear()
    wf.started_at = _now()
    wf.finished_at = None
    await record_workflow_event(db, task, user.id, "workflow.started", {"agent_id": str(agent.id)})
    await enqueue(db, wf, task, RunRole.brainstorm, requested_by=user.id)
    return wf


async def pause(db: AsyncSession, user: User, task: Task) -> TaskWorkflow:
    """Pause an active workflow and cancel its run (as this user: cancelled_by). It is never retried."""
    wf = await lock_task(db, task)
    if wf is None or wf.driver != Driver.runner or wf.status not in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_not_active")
    await _require_can_use(db, user, task, wf)
    wf.status = WorkflowStatus.paused
    wf.needs = None  # an escalation keeps its reason, so resuming returns to it
    await record_workflow_event(db, task, user.id, "workflow.paused")
    run = await active_run(db, task.id)
    if run is not None:
        await cancel_run(db, user, run)
    return wf


async def _pending_need(db: AsyncSession, wf: TaskWorkflow) -> Needs | None:
    """What a resumed workflow is waiting for, if a human still owes an answer or a decision."""
    if wf.escalation_reason:
        return Needs.escalation
    open_q = await db.scalar(
        select(WorkflowQuestion.id)
        .where(WorkflowQuestion.task_id == wf.task_id, WorkflowQuestion.status == QuestionStatus.open)
        .limit(1)
    )
    if open_q is not None:
        return Needs.question
    # a design submitted by a run that ended while the workflow was paused left the stage at brainstorm
    kind = {Stage.brainstorm: DocKind.design, Stage.design: DocKind.design, Stage.plan: DocKind.plan}.get(wf.stage)
    if kind is not None:
        submitted = await db.scalar(
            select(WorkflowDocument.id)
            .where(
                WorkflowDocument.task_id == wf.task_id,
                WorkflowDocument.kind == kind,
                WorkflowDocument.status == DocStatus.submitted,
            )
            .limit(1)
        )
        if submitted is not None:
            return Needs.design_approval if kind == DocKind.design else Needs.plan_approval
    return None


async def resume(db: AsyncSession, user: User, task: Task) -> TaskWorkflow:
    """Resume a paused workflow: back to the wait it was in, or the current role and step run again."""
    agent = await _usable_agent(db, user, task)
    wf = await lock_task(db, task)
    if wf is None or wf.driver != Driver.runner or wf.status != WorkflowStatus.paused:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_not_paused")
    wf.agent_id = agent.id
    wf.failures = 0
    await record_workflow_event(db, task, user.id, "workflow.resumed")
    need = await _pending_need(db, wf)
    if need == Needs.design_approval:
        await set_stage(db, wf, task, Stage.design)  # what the brainstorm handler would have done
    if need is not None:
        wait_for(wf, need)
    else:
        from app.workflow import questions  # local: questions imports this module

        # answered while paused: only for the latest run, and only if it is still the current stage and step
        last = await latest_run(db, task.id)
        current = last is not None and last.stage == wf.stage and last.step == wf.current_step
        pending = await questions.undelivered_answer(db, task.id, last.id) if current else None
        if pending is not None:
            await questions.deliver(db, wf, task, pending, requested_by=user.id)
        else:
            await rerun(db, wf, task, requested_by=user.id)
    return wf


# ---- escalations ----------------------------------------------------------------------

AcceptHandler = Callable[[AsyncSession, TaskWorkflow, Task, User], Awaitable[None]]
# reason -> what `accept` does. Accept applies only to review_rounds_exhausted, final_review_not_clean
# (registered by the build and review stages) and enforcement_violation; any other reason gets 422.
ACCEPT_HANDLERS: dict[str, AcceptHandler] = {}


async def _accept_violation(db: AsyncSession, wf: TaskWorkflow, task: Task, user: User) -> None:
    """The human accepts the repository change: the run's output counts, the task stays partially_enforced."""
    run = await latest_run(db, task.id)
    handler = ROLE_HANDLERS.get(RunRole(run.workflow_role)) if run is not None else None
    if handler is not None:
        await handler(db, wf, task, run)


ACCEPT_HANDLERS["enforcement_violation"] = _accept_violation


async def decide_escalation(db: AsyncSession, user: User, task: Task, action: str) -> TaskWorkflow:
    wf = await lock_task(db, task)
    await require_actor(db, user, task, wf)
    if wf is None or wf.status != WorkflowStatus.waiting_human or wf.needs != Needs.escalation:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_decided")
    reason = wf.escalation_reason
    if action == "accept" and reason not in ACCEPT_HANDLERS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "cannot_accept_here")
    await record_workflow_event(db, task, user.id, "escalation.decided", {"action": action, "reason": reason})
    await audit.record(
        db, f"workflow.{action}", actor_id=user.id, target_type="task", target_id=task.id, data={"reason": reason}
    )
    wf.escalation_reason = None
    wf.needs = None
    if action == "pause":
        wf.status = WorkflowStatus.paused
        await record_workflow_event(db, task, user.id, "workflow.paused")
    elif action == "retry":
        wf.failures = 0
        wf.nudged = False
        wf.status = WorkflowStatus.running
        await rerun(db, wf, task, requested_by=user.id)
    else:
        wf.status = WorkflowStatus.running
        await ACCEPT_HANDLERS[reason](db, wf, task, user)
    return wf


# ---- manual driver (WF-11) -------------------------------------------------------------


async def set_manual(db: AsyncSession, user: User, task: Task, stage: Stage) -> TaskWorkflow:
    """A human's opt-in checklist: records the stage, without enforcement, approvals or runs."""
    if task.assignee_agent_id is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "task_assigned_to_agent")
    if task.assignee_user_id != user.id and not await _manages(db, user, await db.get(Project, task.project_id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot_act_on_workflow")
    wf = await lock_task(db, task, create=True)
    if wf.status in ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "workflow_active")
    if wf.driver != Driver.manual:
        wf.driver = Driver.manual
        wf.enforcement = Enforcement.unenforced
        wf.needs = None
        wf.escalation_reason = None
        wf.failures = 0
        wf.nudged = False
        wf.review_round = 0
        wf.sessions.clear()
        wf.started_at = _now()
    frm = wf.stage
    wf.stage = Stage(stage)
    wf.status = WorkflowStatus.finished if wf.stage == Stage.done else WorkflowStatus.idle
    wf.finished_at = _now() if wf.stage == Stage.done else None
    if frm != wf.stage:
        await record_workflow_event(db, task, user.id, "workflow.stage", {"from": str(frm), "to": str(wf.stage)})
    return wf


# ---- connect-only driver (AGT-32) --------------------------------------------------------------
# An agent working through its owner's personal MCP token on the owner's own task. The documents, questions and
# approvals are the same as for a runner-driven workflow, but nothing is ever queued (`hand_to_agent`), and
# nothing is enforced. Its stages are gated by documents.submit_connect_only and build.complete_step_connect_only,
# called from the MCP tools (app/mcp_server/workflow_tools.py).


def check_connect_only(user: User, task: Task, wf: TaskWorkflow | None) -> None:
    """A personal token drives only its owner's own task (403 not_your_task), never one MegooColab drives
    (409 runner_driven): a human's own MCP client cannot submit for their agent."""
    if task.assignee_agent_id is not None or (
        wf is not None and wf.driver == Driver.runner and wf.status != WorkflowStatus.idle
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "runner_driven")
    if task.assignee_user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not_your_task")


async def lock_connect_only(db: AsyncSession, user: User, task: Task) -> TaskWorkflow:
    """Locks 1 and 2 for a connect-only stage tool. The first one starts the workflow: driver connect_only,
    enforcement unenforced, stage brainstorm, running (a manual checklist is replaced)."""
    wf = await lock_task(db, task)
    # again under the task lock: the assignee or type may have changed since `task` was loaded
    await db.refresh(task, ["assignee_user_id", "assignee_agent_id", "type"])
    check_connect_only(user, task, wf)
    if wf is not None and wf.driver == Driver.connect_only:
        return wf
    if task.type not in WORKFLOW_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "workflow_not_supported_for_type")
    if wf is None:
        wf = await lock_task(db, task, create=True)
    wf.driver = Driver.connect_only
    wf.enforcement = Enforcement.unenforced
    wf.stage = Stage.brainstorm
    wf.status = WorkflowStatus.running
    wf.needs = None
    wf.agent_id = None
    wf.current_step = None
    wf.review_round = 0
    wf.failures = 0
    wf.nudged = False
    wf.escalation_reason = None
    wf.sessions.clear()
    wf.started_at = _now()
    wf.finished_at = None
    await record_workflow_event(db, task, user.id, "workflow.started", {"driver": Driver.connect_only.value})
    return wf


# ---- run outcomes ------------------------------------------------------------------------

RoleHandler = Callable[[AsyncSession, TaskWorkflow, Task, AgentRun], Awaitable[None]]
# role -> handling of a completed run. Each handler must leave the workflow either waiting, finished, or with a
# new run queued: that is what makes on_run_finished idempotent (see there).
ROLE_HANDLERS: dict[RunRole, RoleHandler] = {}

_handling: contextvars.ContextVar[bool] = contextvars.ContextVar("workflow_handling", default=False)


def _git_changed(run: AgentRun) -> bool:
    """R1: a read-only run moved HEAD or left edits. Without both reports (an old runner, or a run that never
    reached the runner) nothing is known."""
    before, after = run.git_before, run.git_after
    if not before or not after:
        return False
    return before.get("head") != after.get("head") or bool(after.get("dirty"))


async def on_run_finished(db: AsyncSession, run: AgentRun) -> None:
    """React to a workflow run reaching a terminal status. Called by every path that ends a run, after the
    transition, inside its transaction (the caller holds the workflow lock, then the run lock).

    Idempotent: only the task's newest workflow run is handled, and only while the workflow is `running`;
    handling always queues a newer run or leaves `running`, so a second call does nothing. Not re-entrant:
    a run ending inside another run's handling is not handled again."""
    if run.workflow_role is None or run.status in ACTIVE_STATUSES or _handling.get():
        return
    token = _handling.set(True)
    try:
        async with db.begin_nested():  # a failure here must not undo the run's own end
            await _on_run_finished(db, run)
    except Exception:
        log.exception("workflow: handling the end of run %s failed", run.id)
        wf = await lock_workflow(db, run.task_id)
        if wf is not None and wf.status == WorkflowStatus.running:
            await escalate(db, wf, "engine_error")  # a human can retry
    finally:
        _handling.reset(token)


async def _on_run_finished(db: AsyncSession, run: AgentRun) -> None:
    wf = await lock_workflow(db, run.task_id)
    if wf is None or wf.driver != Driver.runner:
        return
    newest = await latest_run(db, run.task_id)
    if newest is None or newest.id != run.id:
        return  # a superseded run's late end changes nothing
    role = RunRole(run.workflow_role)
    key = session_key(role, run.step)
    if key and run.session_ref and run.agent_id == wf.agent_id:  # also while paused: resume continues it
        wf.sessions[key] = run.session_ref
    if wf.status != WorkflowStatus.running:
        return  # paused, or already handled
    task = await db.get(Task, run.task_id)
    if run.status == RunStatus.cancelled and run.cancelled_by is not None:
        # a human cancelled the run itself: the workflow pauses with it, and the run is never retried
        wf.status = WorkflowStatus.paused
        await record_workflow_event(db, task, run.cancelled_by, "workflow.paused", {"run_id": str(run.id)})
        return
    if role in READ_ONLY_ROLES and _git_changed(run):
        # R1, whatever the outcome: an agent that commits and then errors out is caught too, never retried
        wf.enforcement = Enforcement.partially_enforced
        await record_workflow_event(db, task, None, "enforcement.violation", {"stage": str(run.stage), "role": role.value})
        await escalate(db, wf, "enforcement_violation")
        return
    requester_id = await owner_id(db, run)
    if run.status == RunStatus.cancelled and run.reason == "user_deactivated" and await _owner_deactivated(db, run):
        # the agent's owner is gone: nothing could ever run, so the workflow pauses instead of retrying
        wf.status = WorkflowStatus.paused
        await record_workflow_event(db, task, None, "workflow.paused", {"reason": "owner_deactivated"})
        return
    if run.status in (RunStatus.failed, RunStatus.cancelled):  # a cancel nobody asked for counts as a failure
        wf.failures += 1
        if wf.failures >= MAX_FAILURES:
            await escalate(db, wf, "retries_exhausted")
        else:
            await rerun(db, wf, task, last=run, requested_by=requester_id)
        return
    wf.failures = 0
    handler = ROLE_HANDLERS.get(role)
    if handler is not None:
        await handler(db, wf, task, run)


# ---- brainstorm and plan --------------------------------------------------------------------

STAGE_DOC = {RunRole.brainstorm: DocKind.design, RunRole.plan: DocKind.plan}


async def _handle_brainstorm_or_plan(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    """WF-5: a question waits for the answer; a submitted design or plan waits for approval; neither gets one
    nudge, then an escalation."""
    asked = await db.scalar(
        select(WorkflowQuestion.id)
        .where(WorkflowQuestion.run_id == run.id, WorkflowQuestion.status == QuestionStatus.open)
        .limit(1)
    )
    if asked is not None:
        wait_for(wf, Needs.question)
        return
    role = RunRole(run.workflow_role)
    kind = STAGE_DOC[role]
    submitted = await db.scalar(
        select(WorkflowDocument.id)
        .where(
            WorkflowDocument.submitted_run_id == run.id,
            WorkflowDocument.kind == kind,
            WorkflowDocument.status == DocStatus.submitted,
        )
        .limit(1)
    )
    if submitted is not None:
        if kind == DocKind.design:
            await set_stage(db, wf, task, Stage.design)
            wait_for(wf, Needs.design_approval)
        else:
            wait_for(wf, Needs.plan_approval)
        return
    from app.workflow import questions  # local: questions imports this module

    pending = await questions.undelivered_answer(db, task.id, run.id)
    if pending is not None:  # answered while this run was still running: it gets the answer, not a nudge
        await questions.deliver(db, wf, task, pending, requested_by=await owner_id(db, run))
        return
    if not wf.nudged:
        wf.nudged = True
        await rerun(
            db, wf, task, last=run, requested_by=await owner_id(db, run),
            resume_kind="nudge", payload=NUDGE_TEXT.get(role),
        )
        return
    await escalate(db, wf, "no_output")


ROLE_HANDLERS[RunRole.brainstorm] = _handle_brainstorm_or_plan
ROLE_HANDLERS[RunRole.plan] = _handle_brainstorm_or_plan


# ---- engine card moves (WF-2) ------------------------------------------------------------------


async def move_to_category(db: AsyncSession, task: Task, category: str) -> None:
    """Move the card to the end of the first column of `category`. Recorded like a human move
    (`status_changed`), with no actor and `by: "workflow"`."""
    column = (
        await db.execute(
            select(BoardColumn)
            .where(BoardColumn.project_id == task.project_id, BoardColumn.category == category)
            .order_by(BoardColumn.position)
            .limit(1)
        )
    ).scalar_one()
    if task.column_id == column.id:
        return
    frm = task.column_id
    task.position = await end_position(db, column.id)
    apply_column(task, column)
    task.updated_at = _now()
    await record_workflow_event(db, task, None, "status_changed", {
        "from_column": str(frm), "to_column": str(column.id), "to_category": str(column.category), "by": "workflow",
    })


# The build and finish stages register their role and accept handlers on import; importing them here means every
# user of the engine (run ends, escalation decisions) has them. Last, as they import this module.
from app.workflow import build, finish  # noqa: F401
