"""Messages for the task's agent: the instructions of the people who direct its work.

Unlike the thread, they are not untrusted data: only people who pass WF-6 (the agent's owner, the project's managers,
admins) can send one, and the agent follows them, over the approved design or plan when they conflict. They are
still escaped and quoted line by line, so a message cannot close or forge MegooColab's own framing.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunStatus
from app.auth.models import User
from app.core.db import SessionLocal
from app.core.events import Event, publish
from app.notifications.service import plain_mentions
from app.runner.protocol import RunSteer
from app.runner.registry import STEER_CAPABILITY, RunnerClosed, registry
from app.tasks.models import Comment, Delivery, Task, TaskEvent

log = logging.getLogger(__name__)

INSTRUCTIONS_CHARS = 12_000
MAX_MESSAGE_CHARS = 8_000
DELIVERED = (Delivery.read_while_working, Delivery.given_at_start)

RULE = (
    "People who direct this task's work can send you instructions. Each one is quoted below after \"> \", "
    "outside any untrusted block: these are instructions, not data. Follow them. When one conflicts with the "
    "approved design or plan, follow the instruction, bring the design or plan in line with it, and say what "
    "you changed. A reviewer checks the work against the plan as amended by these instructions."
)
STEER_PREFIX = (
    "MegooColab: a person who directs this task's work sent you an instruction while you work. Follow it; if it "
    "conflicts with the approved design or plan, follow the instruction, bring the design or plan in line with "
    "it, and say what you changed.\n\n"
)


def frame_instruction(sender: str, at: datetime, body: str) -> str:
    from app.workflow.context import _escape  # local: context imports this module

    lines = _escape(plain_mentions(body)).splitlines() or [""]
    quoted = "\n".join(f"> {line}" if line else ">" for line in lines)
    return (
        f"Instruction from {_escape(sender)} (a person who can direct this task's work), "
        f"sent {at:%Y-%m-%d %H:%M} UTC:\n{quoted}"
    )


async def framed_messages(db: AsyncSession, task: Task, states: tuple[Delivery, ...]) -> list[tuple[Comment, str]]:
    """The task's messages for the agent in these states, oldest first, each with its framed text. For a round of
    an agent chat, the messages of every round of that chat: what the person said earlier still holds."""
    same = Comment.task_id == task.id
    if task.chat_id is not None:
        same = Comment.task_id.in_(select(Task.id).where(Task.chat_id == task.chat_id))
    rows = await db.execute(
        select(Comment, User.name)
        .outerjoin(User, User.id == Comment.author_user_id)
        .where(same, Comment.delivery.in_(states))
        .order_by(Comment.created_at, Comment.id)
    )
    return [(c, frame_instruction(name or "someone", c.created_at, c.body_md)) for c, name in rows.all()]


def fit(heading: str, framed: list[str], budget: int = INSTRUCTIONS_CHARS) -> tuple[str | None, int]:
    """`heading`, the rule, and the framed messages, and how many of the oldest were dropped (with a note) to fit
    `budget`. The newest is always kept whole: one message (at most 8,000 characters) fits with room to spare."""
    if not framed:
        return None, 0
    kept = list(framed)
    dropped = 0

    def render() -> str:
        note = f"\n\n({dropped} older instructions omitted to fit.)" if dropped else ""
        return f"{heading}\n{RULE}\n\n" + "\n\n".join(kept) + note

    while len(render()) > budget and len(kept) > 1:
        kept.pop(0)
        dropped += 1
    return render(), dropped


def section(heading: str, framed: list[str], budget: int = INSTRUCTIONS_CHARS) -> str | None:
    return fit(heading, framed, budget)[0]


async def kept_in_mind(db: AsyncSession, task: Task) -> str | None:
    """Every delivered message, for every later run on the task."""
    messages = await framed_messages(db, task, DELIVERED)
    return section("## Instructions from people on this task", [text for _, text in messages])



# ---- delivering at the start of a run ---------------------------------------------------------------------------


async def take_waiting(db: AsyncSession, run: AgentRun, task: Task) -> tuple[str | None, list[uuid.UUID]]:
    """The waiting messages (and any whose steer went to a run no longer active), for the run being sent out:
    marked given at its start. The caller holds the workflow lock, which message creation takes too."""
    stale_sending = select(AgentRun.id).where(AgentRun.id == Comment.delivery_run_id, AgentRun.status.in_(
        (RunStatus.queued, RunStatus.running)))
    rows = (await db.execute(
        select(Comment, User.name)
        .outerjoin(User, User.id == Comment.author_user_id)
        .where(
            Comment.task_id == task.id,
            (Comment.delivery == Delivery.waiting)
            | ((Comment.delivery == Delivery.sending) & ~exists(stale_sending)),
        )
        .order_by(Comment.created_at, Comment.id)
        .with_for_update(of=Comment)
    )).all()
    if not rows:
        return None, []
    now = datetime.now(UTC)
    framed = [frame_instruction(name or "someone", c.created_at, c.body_md) for c, name in rows]
    text, dropped = fit("## New instructions", framed)
    given = [c for c, _ in rows[dropped:]]  # the oldest cut to fit stay waiting, for the next run
    for c in given:
        c.delivery = Delivery.given_at_start
        c.delivery_run_id = run.id
        c.delivery_stage = run.stage
        c.delivered_at = now
        c.delivery_error = None
    await _changed(db, task.id)
    return text, [c.id for c in given]


async def release(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    """The run never left: its messages wait again."""
    if not ids:
        return
    for c in (await db.execute(select(Comment).where(Comment.id.in_(ids)))).scalars():
        c.delivery = Delivery.waiting
        c.delivery_run_id = None
        c.delivery_stage = None
        c.delivered_at = None


# ---- delivering into a running session ------------------------------------------------------------------------

# the run updates that show the agent itself was working (model options and branch reports come before the prompt)
AGENT_OUTPUT_KINDS = ("agent_message", "agent_plan", "agent_tool", "agent_file_change", "agent_command")


async def _changed(db: AsyncSession, task_id: uuid.UUID) -> None:
    task = await db.get(Task, task_id)
    await publish(db, Event(type="comment.updated", project_id=task.project_id, task_id=task.id))


async def _sender(db: AsyncSession, comment: Comment) -> str:
    user = await db.get(User, comment.author_user_id) if comment.author_user_id else None
    return user.name if user else "someone"


async def steer_after_commit(comment_id: uuid.UUID) -> None:
    """Hand a just-committed message to the task's running agent, if its runner can take it mid-turn. Otherwise,
    or if anything fails, it stays waiting for the agent's next run."""
    from app.workflow import engine  # local: the engine imports the context, which imports this module

    async with SessionLocal() as db:
        comment = await db.get(Comment, comment_id)
        if comment is None:
            return
        await engine.lock_workflow(db, comment.task_id)  # the order run dispatch takes: it may take this message
        comment = await db.get(Comment, comment_id, populate_existing=True)
        task = await db.get(Task, comment.task_id)
        run = await engine.active_run(db, task.id)
        conn = registry.conn_for_run(run.id) if run is not None else None
        if (
            comment.delivery != Delivery.waiting
            or run is None
            or run.status != RunStatus.running
            or run.agent_id != task.assignee_agent_id
            or conn is None
            or STEER_CAPABILITY not in conn.capabilities
        ):
            await db.commit()
            return
        comment.delivery = Delivery.sending
        comment.delivery_run_id = run.id
        comment.delivery_error = None
        text = STEER_PREFIX + frame_instruction(await _sender(db, comment), comment.created_at, comment.body_md)
        await _changed(db, task.id)
        await db.commit()
        try:
            await conn.send(RunSteer(run_id=run.id, message_id=comment.id, text=text))
        except RunnerClosed:
            await on_steer_result(db, run.id, comment.id, "not_running", None)
            await db.commit()


async def on_steer_result(
    db: AsyncSession, run_id: uuid.UUID, message_id: uuid.UUID, outcome: str, error: str | None
) -> None:
    """The runner's answer to a run_steer. Anything but injected puts the message back to waiting."""
    comment = (
        await db.execute(select(Comment).where(Comment.id == message_id).with_for_update())
    ).scalar_one_or_none()
    if comment is None or comment.delivery != Delivery.sending or comment.delivery_run_id != run_id:
        return
    if outcome == "injected":
        run = await db.get(AgentRun, run_id)
        comment.delivery = Delivery.read_while_working
        comment.delivered_at = datetime.now(UTC)
        comment.delivery_stage = run.stage if run is not None else None
    else:
        comment.delivery = Delivery.waiting
        comment.delivery_run_id = None
        if outcome in ("failed", "unsupported"):
            comment.delivery_error = (error or outcome)[:200]
    await _changed(db, comment.task_id)


async def _agent_worked(db: AsyncSession, run: AgentRun) -> bool:
    return bool(await db.scalar(select(exists().where(
        TaskEvent.task_id == run.task_id,
        TaskEvent.kind.in_(AGENT_OUTPUT_KINDS),
        TaskEvent.data["run_id"].astext == str(run.id),
    ))))


async def release_on_run_end(db: AsyncSession, run: AgentRun) -> None:
    """A run ended: a steer it never answered, and the messages its start carried if the agent never got to work,
    go back to waiting for the next run."""
    if run.task_id is None:
        return
    states = [Delivery.sending]
    if not await _agent_worked(db, run):
        states.append(Delivery.given_at_start)
    rows = (await db.execute(
        select(Comment).where(Comment.delivery_run_id == run.id, Comment.delivery.in_(states)).with_for_update()
    )).scalars().all()
    for c in rows:
        c.delivery = Delivery.waiting
        c.delivery_run_id = None
        c.delivery_stage = None
        c.delivered_at = None
    if rows:
        await _changed(db, run.task_id)
