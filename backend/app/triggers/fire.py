"""The trigger loop: every FIRE_SECONDS it takes the pending firings, and starts each one as a freestyle chat in the
name of its trigger's owner, or skips it with the reason (and tells the managers, when the trigger asks for it)."""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.agents.service import can_use_agent, is_usable_binding
from app.auth.models import User, UserStatus
from app.chats.models import ChatMode
from app.core.db import SessionLocal
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.projects.access import get_project_for
from app.projects.models import Project, ProjectStatus
from app.triggers.models import FiringStatus, Trigger, TriggerFiring

log = logging.getLogger(__name__)

FIRE_SECONDS = 5
HOURLY_LIMIT = 20
HOUR = timedelta(hours=1)
BATCH = 50

SKIP_TEXT = {
    "no_agent": "no agent can take it",
    "owner_gone": "the person it runs as can no longer start chats here",
    "rate_limited": f"it already started {HOURLY_LIMIT} chats in the last hour",
    "paused": "the trigger was paused",
}


async def _owner(db: AsyncSession, trigger: Trigger, project: Project) -> User | None:
    """The person the trigger runs as, while they may still start chats in the project."""
    owner = await db.get(User, trigger.owner_id) if trigger.owner_id else None
    if owner is None or owner.status != UserStatus.active:
        return None
    try:
        await get_project_for(db, owner, project.key, write=True)
    except HTTPException:
        return None
    return owner


async def _agent(db: AsyncSession, trigger: Trigger, owner: User, project: Project) -> Agent | None:
    """The chosen agent while the owner may use it here, never another one; or any agent the owner may use."""
    from app.chats.service import pick_agent  # local: the chat service imports the trigger hooks

    if not trigger.any_agent:
        agent = await db.get(Agent, trigger.agent_id) if trigger.agent_id else None
        ok = (agent is not None and await is_usable_binding(db, agent.id, project.id)
              and await can_use_agent(db, owner, agent, project))
        return agent if ok else None
    try:
        return await pick_agent(db, owner, project)
    except HTTPException:
        return None


async def _skip(db: AsyncSession, trigger: Trigger, project: Project, firing: TriggerFiring, reason: str) -> None:
    from app.crons.turns import project_managers  # local: the cron turns import the trigger hooks

    firing.status, firing.skip_reason = FiringStatus.skipped, reason
    if not trigger.notify_problems or reason == "paused":
        return
    if reason == "rate_limited":  # told once an hour, not once per event
        told = await db.scalar(
            select(TriggerFiring.id).where(
                TriggerFiring.trigger_id == trigger.id, TriggerFiring.id != firing.id,
                TriggerFiring.skip_reason == "rate_limited", TriggerFiring.created_at > datetime.now(UTC) - HOUR,
            ).limit(1)
        )
        if told is not None:
            return
    people = {trigger.owner_id} | await project_managers(db, project.id)
    await notifications.notify(db, people, Kind.needs_you, title=f"Trigger {trigger.name} skipped",
                               body=SKIP_TEXT[reason], link=f"/projects/{project.key}/triggers/{trigger.id}",
                               project_id=project.id)


async def fire_one(db: AsyncSession, firing: TriggerFiring) -> None:
    """Starts one pending firing as a freestyle chat, or skips it with the reason."""
    from app.chats.service import open_chat  # local: the chat service imports the trigger hooks

    trigger = await db.get(Trigger, firing.trigger_id)
    project = await db.get(Project, trigger.project_id)
    if project.status != ProjectStatus.active:
        await db.delete(firing)  # a closed project fires nothing
        return
    if trigger.paused and not firing.tried:
        await _skip(db, trigger, project, firing, "paused")
        return
    owner = await _owner(db, trigger, project)
    if owner is None:
        await _skip(db, trigger, project, firing, "owner_gone")
        return
    now = datetime.now(UTC)
    started = await db.scalar(
        select(func.count()).select_from(TriggerFiring).where(
            TriggerFiring.trigger_id == trigger.id, TriggerFiring.status == FiringStatus.started,
            TriggerFiring.started_at > now - HOUR,
        )
    )
    if started >= HOURLY_LIMIT:
        await _skip(db, trigger, project, firing, "rate_limited")
        return
    agent = await _agent(db, trigger, owner, project)
    if agent is None:
        await _skip(db, trigger, project, firing, "no_agent")
        return
    chat, _ = await open_chat(db, owner, project, agent, trigger.prompt, ChatMode.freestyle,
                              title=f"{trigger.name} · {firing.subject['label']}"[:200])
    firing.status, firing.started_at = FiringStatus.started, now
    firing.chat_id, firing.agent_id, firing.keep_open = chat.id, agent.id, trigger.keep_open


async def tick() -> None:
    from app.workflow import engine  # local: the engine imports the chat service, which calls into this package

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(TriggerFiring).where(TriggerFiring.status == FiringStatus.pending)
                .order_by(TriggerFiring.created_at).limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        for firing in rows:
            await fire_one(db, firing)
        await db.commit()
        await engine.dispatch_queued(db)


async def trigger_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await tick()
        except Exception:
            log.exception("trigger firing failed")
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), FIRE_SECONDS)
