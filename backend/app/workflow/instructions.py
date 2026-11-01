"""Messages for the task's agent: the instructions of the people who direct its work.

Unlike the thread, they are not untrusted data: only people who pass WF-6 (the agent's owner, the project's managers,
admins) can send one, and the agent follows them, over the approved design or plan when they conflict. They are
still escaped and quoted line by line, so a message cannot close or forge MegooColab's own framing.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.notifications.service import plain_mentions
from app.tasks.models import Comment, Delivery, Task

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
    """The task's messages for the agent in these states, oldest first, each with its framed text."""
    rows = await db.execute(
        select(Comment, User.name)
        .outerjoin(User, User.id == Comment.author_user_id)
        .where(Comment.task_id == task.id, Comment.delivery.in_(states))
        .order_by(Comment.created_at, Comment.id)
    )
    return [(c, frame_instruction(name or "someone", c.created_at, c.body_md)) for c, name in rows.all()]


def section(heading: str, framed: list[str], budget: int = INSTRUCTIONS_CHARS) -> str | None:
    """`heading`, the rule, and the framed messages; the oldest are dropped (with a note) to fit `budget`."""
    if not framed:
        return None
    kept = list(framed)
    dropped = 0

    def render() -> str:
        note = f"\n\n({dropped} older instructions omitted to fit.)" if dropped else ""
        return f"{heading}\n{RULE}\n\n" + "\n\n".join(kept) + note

    while len(render()) > budget and len(kept) > 1:
        kept.pop(0)
        dropped += 1
    text = render()
    return text if len(text) <= budget else text[:budget]


async def kept_in_mind(db: AsyncSession, task: Task) -> str | None:
    """Every delivered message, for every later run on the task."""
    messages = await framed_messages(db, task, DELIVERED)
    return section("## Instructions from people on this task", [text for _, text in messages])
