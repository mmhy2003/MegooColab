"""A project's triggers: its managers set them up, its members read them and their firings; and the firing behind a
chat."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.agents.service import can_use_agent, is_usable_binding
from app.audit import service as audit
from app.auth.models import User
from app.chats.schemas import ChatTrigger
from app.crons.models import Cron
from app.kb.schemas import Named
from app.projects.models import BoardColumn, Label, Project
from app.tasks.models import Task
from app.triggers import events
from app.triggers.models import FiringStatus, Trigger, TriggerFiring
from app.triggers.schemas import FiringOut, FiringSubject, TriggerIn, TriggerOut, TriggerPatch
from app.workflow.models import Needs, QuestionStatus, RunRole, TaskWorkflow, WorkflowQuestion

EXCERPT_CHARS = 300


async def firing_of_chat(db: AsyncSession, chat_id: uuid.UUID) -> TriggerFiring | None:
    """The firing that started the chat, if a trigger did."""
    return await db.scalar(select(TriggerFiring).where(TriggerFiring.chat_id == chat_id))


async def chat_trigger(db: AsyncSession, chat_id: uuid.UUID) -> ChatTrigger | None:
    """The trigger that started the chat and what happened; None for a person's chat, or once the trigger is
    deleted (its firings go with it)."""
    row = (await db.execute(
        select(Trigger.id, Trigger.name, TriggerFiring.what, TriggerFiring.keep_open)
        .join(Trigger, Trigger.id == TriggerFiring.trigger_id)
        .where(TriggerFiring.chat_id == chat_id)
    )).first()
    return ChatTrigger(id=row.id, name=row.name, what=row.what, keep_open=row.keep_open) if row else None


# ---- reading ------------------------------------------------------------------------------------------------


async def _named(db: AsyncSession, model, id_: uuid.UUID | None) -> Named | None:
    row = await db.get(model, id_) if id_ else None
    return Named(id=row.id, name=row.name) if row else None


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


async def broken(db: AsyncSession, trigger: Trigger) -> str | None:
    """Which of the config's references no longer exists in the project: the trigger matches nothing until fixed."""
    config = trigger.config or {}
    for key, model, reason in (("column_id", BoardColumn, "column_deleted"), ("label_id", Label, "label_deleted"),
                               ("cron_id", Cron, "cron_deleted")):
        if config.get(key) is None:
            continue
        ref = _uuid(config[key])
        found = ref and await db.scalar(select(model.id).where(model.id == ref, model.project_id == trigger.project_id))
        if not found:
            return reason
    return None


async def _result(db: AsyncSession, firing: TriggerFiring) -> tuple[str, str | None]:
    """What became of the firing (FiringOut.result) and its excerpt, from its chat's newest round."""
    from app.runner.registry import registry
    from app.workflow import engine, freestyle  # local: the workflow calls into this module

    if firing.status == FiringStatus.skipped:
        return "skipped", firing.skip_reason
    task = await db.scalar(
        select(Task).where(Task.chat_id == firing.chat_id).order_by(Task.chat_round.desc().nulls_last()).limit(1)
    ) if firing.chat_id else None
    if firing.status == FiringStatus.pending or task is None:
        return "starting", None
    run = await engine.active_run(db, task.id)
    if run is not None:
        waiting = run.status == RunStatus.queued and not registry.is_available(run.agent_id)
        return ("waiting_agent" if waiting else "working"), None
    wf = await db.get(TaskWorkflow, task.id)
    if wf is not None and wf.needs == Needs.question:
        body = await db.scalar(
            select(WorkflowQuestion.body)
            .where(WorkflowQuestion.task_id == task.id, WorkflowQuestion.status == QuestionStatus.open)
            .order_by(WorkflowQuestion.created_at.desc()).limit(1)
        )
        return "question", body[:EXCERPT_CHARS] if body else None
    last = await db.scalar(
        select(AgentRun).where(AgentRun.task_id == task.id, AgentRun.workflow_role == RunRole.freestyle)
        .order_by(AgentRun.created_at.desc()).limit(1)
    )
    if last is None:
        return "replied", None
    if last.status == RunStatus.failed or (last.status == RunStatus.cancelled and last.cancelled_by is None):
        return "failed", last.reason
    reply = (await freestyle._replies(db, task, [last])).get(str(last.id)) or last.summary
    return "replied", reply[:EXCERPT_CHARS] if reply else None


async def firing_out(db: AsyncSession, firing: TriggerFiring) -> FiringOut:
    result, excerpt = await _result(db, firing)
    return FiringOut(
        id=firing.id, created_at=firing.created_at, subject=FiringSubject(**firing.subject),
        agent=await _named(db, Agent, firing.agent_id), chat_id=firing.chat_id, result=result, excerpt=excerpt,
    )


async def _try_subject(db: AsyncSession, trigger: Trigger) -> str | None:
    found = events.REGISTRY.get(trigger.event)
    payload = await found.latest(db, trigger) if found is not None and found.latest is not None else None
    return (await found.describe(db, payload)).subject["label"] if payload is not None else None


async def trigger_out(db: AsyncSession, trigger: Trigger) -> TriggerOut:
    project = await db.get(Project, trigger.project_id)
    last = await db.scalar(
        select(TriggerFiring).where(TriggerFiring.trigger_id == trigger.id)
        .order_by(TriggerFiring.created_at.desc(), TriggerFiring.id.desc()).limit(1)
    )
    return TriggerOut(
        id=trigger.id, project_key=project.key, name=trigger.name, event=trigger.event, config=trigger.config or {},
        prompt=trigger.prompt, any_agent=trigger.any_agent, agent=await _named(db, Agent, trigger.agent_id),
        keep_open=trigger.keep_open, notify_reply=trigger.notify_reply, notify_problems=trigger.notify_problems,
        paused=trigger.paused, owner=await _named(db, User, trigger.owner_id),
        created_by=await _named(db, User, trigger.created_by), created_at=trigger.created_at,
        updated_at=trigger.updated_at, broken=await broken(db, trigger),
        last_firing=await firing_out(db, last) if last else None, try_subject=await _try_subject(db, trigger),
    )


async def get_trigger(db: AsyncSession, project: Project, trigger_id: uuid.UUID, *, lock: bool = False) -> Trigger:
    stmt = select(Trigger).where(Trigger.id == trigger_id, Trigger.project_id == project.id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    trigger = (await db.execute(stmt)).scalar_one_or_none()
    if trigger is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "trigger_not_found")
    return trigger


# ---- writing ------------------------------------------------------------------------------------------------


async def _check_agent(db: AsyncSession, user: User, project: Project, agent_id: uuid.UUID | None) -> None:
    if agent_id is None:
        return
    agent = await db.get(Agent, agent_id)
    if (
        agent is None
        or not await is_usable_binding(db, agent.id, project.id)
        or not await can_use_agent(db, user, agent, project)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_not_available")


async def _clean(db: AsyncSession, project: Project, event: str, config: dict) -> dict:
    """The event's config, checked and cleaned (raises with the code otherwise)."""
    found = events.spec(event)
    if found.sprints_only and not project.sprints_enabled:
        raise events.invalid("invalid_event")
    return await found.validate(db, project, config)


def _audit_data(trigger: Trigger) -> dict:
    return {"name": trigger.name, "project_id": str(trigger.project_id), "event": trigger.event}


async def create(db: AsyncSession, user: User, project: Project, data: TriggerIn) -> Trigger:
    config = await _clean(db, project, data.event, data.config)
    await _check_agent(db, user, project, data.agent_id)
    trigger = Trigger(id=uuid.uuid4(), project_id=project.id, owner_id=user.id, created_by=user.id,
                      any_agent=data.agent_id is None, **(data.model_dump() | {"config": config}))
    db.add(trigger)
    await db.flush()
    await audit.record(db, "trigger.created", actor_id=user.id, target_type="trigger", target_id=trigger.id,
                       data=_audit_data(trigger))
    await db.refresh(trigger)
    return trigger


async def update(db: AsyncSession, user: User, project: Project, trigger: Trigger, data: TriggerPatch) -> Trigger:
    """The editor becomes the person it runs as, so the agent it ends with must be one they may use."""
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None or k == "agent_id"}
    event = changes.get("event", trigger.event)
    changes["config"] = await _clean(db, project, event, changes.get("config", trigger.config or {}))
    if "agent_id" in changes:
        trigger.any_agent = changes["agent_id"] is None
    agent_id = changes.get("agent_id", trigger.agent_id)
    if not trigger.any_agent:
        await _check_agent(db, user, project, agent_id)
    for key, value in changes.items():
        setattr(trigger, key, value)
    trigger.owner_id = user.id
    trigger.updated_at = func.now()
    await db.flush()
    await audit.record(db, "trigger.updated", actor_id=user.id, target_type="trigger", target_id=trigger.id,
                       data=_audit_data(trigger))
    await db.refresh(trigger)
    return trigger


async def set_paused(db: AsyncSession, user: User, trigger: Trigger, paused: bool) -> Trigger:
    """Pausing and resuming leave the person it runs as unchanged."""
    trigger.paused = paused
    await db.flush()
    await audit.record(db, "trigger.paused" if paused else "trigger.resumed", actor_id=user.id,
                       target_type="trigger", target_id=trigger.id, data=_audit_data(trigger))
    return trigger


async def delete(db: AsyncSession, user: User, trigger: Trigger) -> None:
    """Its firings go with it; the chats it started stay, as ordinary chats."""
    await audit.record(db, "trigger.deleted", actor_id=user.id, target_type="trigger", target_id=trigger.id,
                       data=_audit_data(trigger))
    await db.delete(trigger)
    await db.flush()
