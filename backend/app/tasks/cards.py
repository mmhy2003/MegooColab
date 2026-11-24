"""Cards (MC-173): a read-only A2UI surface an agent shows in its task's or chat's thread, with a title and a short
text that stand in for it wherever it can't be drawn (notifications, search, other agents' prompts)."""

import uuid
from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, select

from app.a2ui import service as a2ui_service
from app.a2ui.service import CardError
from app.agent_runs.models import AgentRun
from app.auth.models import User
from app.core.events import Event, publish
from app.core.text import strip_nul
from app.tasks.models import Task, TaskCard

MAX_TITLE = 120
MAX_TEXT = 500
MAX_PER_RUN = 3
MAX_PER_TASK = 100


def _line(value: object, field: str, limit: int) -> str:
    value = strip_nul(value if isinstance(value, str) else "").strip()
    if not value:
        raise CardError("invalid_card", [{"path": field, "message": "must not be empty"}])
    if len(value) > limit:
        raise CardError("too_large", [{"path": field, "message": f"over {limit} characters"}])
    return value


async def _count(db, *where) -> int:
    return await db.scalar(select(func.count()).select_from(TaskCard).where(*where))


async def show(db, task: Task, run: AgentRun | None, user: User, title: object, text: object, card: object) -> TaskCard:
    """Store a card on the task. `run` is the calling run (locked, still running); None for a personal token, whose
    person is `user`. The task row is locked so two calls can't both pass the count limits. The caller commits."""
    title, text = _line(title, "title", MAX_TITLE), _line(text, "text", MAX_TEXT)
    surface = a2ui_service.clean_card(card)
    from app.workflow import engine  # local: the workflow imports the task modules

    if not await engine.lock_task_row(db, task.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task_not_found")
    if run is not None and await _count(db, TaskCard.run_id == run.id) >= MAX_PER_RUN:
        raise CardError("too_many_cards", [{"path": "card", "message": f"at most {MAX_PER_RUN} cards in one run"}])
    if await _count(db, TaskCard.task_id == task.id) >= MAX_PER_TASK:
        raise CardError("too_many_cards", [{"path": "card", "message": f"at most {MAX_PER_TASK} cards on one task"}])
    row = TaskCard(task_id=task.id, run_id=run.id if run else None, agent_id=run.agent_id if run else None,
                   user_id=None if run else user.id, title=title, text=text, surface=surface)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
    if task.chat_id is not None:
        from app.chats.service import touch  # local: the chats modules import the engine

        await touch(db, task.chat_id)
    return row


async def of_runs(db, run_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[TaskCard]]:
    """Each run's cards, oldest first."""
    ids = list(run_ids)
    out: dict[uuid.UUID, list[TaskCard]] = {}
    if not ids:
        return out
    rows = await db.execute(select(TaskCard).where(TaskCard.run_id.in_(ids)).order_by(TaskCard.created_at, TaskCard.id))
    for row in rows.scalars():
        out.setdefault(row.run_id, []).append(row)
    return out
