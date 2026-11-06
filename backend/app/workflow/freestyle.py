"""A freestyle round (freestyle chats): no stages, no reviews. Each person's message is a turn, one `freestyle` run
that does what it asks and replies.

When a turn ends:
  an open question it asked       -> wait for the answer (Needs.question)
  an answer that never reached it -> deliver it (the session resumes with it)
  a message sent since it queued  -> the next turn starts on its own
  otherwise                       -> wait for the next message (Needs.reply), and tell the chat's starter once
A failed turn, or one cancelled by nothing a person did, waits for the next message too: never a retry, never an
escalation, and `wf.failures` is not counted (a turn that always fails cannot loop).

What a turn is told: the person's messages in freestyle's own words (instructions.FREESTYLE_RULE). A turn that
resumes the conversation's session gets only the new ones; one that starts fresh gets the conversation so far.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.auth.models import User
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.projects.models import Project
from app.tasks.models import Comment, Delivery, Task
from app.workflow import engine, instructions, questions
from app.workflow.context import _escape, wrap_untrusted
from app.workflow.models import Needs, QuestionStatus, RunRole, TaskWorkflow, WorkflowQuestion

SUMMARY_CHARS = 500
CONVERSATION_CHARS = 12_000
CONVERSATION_HEADING = "## Conversation so far"
CONVERSATION_NOTE = "Earlier in this conversation, oldest first: the person's messages and your replies."


async def conversation_so_far(db: AsyncSession, task: Task) -> str | None:
    """For a turn starting a fresh session: every message the agent was given and, for every ended turn, its reply
    (the run's summary, the agent's own text: wrapped as untrusted), in order. The oldest are cut to fit
    CONVERSATION_CHARS; the newest is always kept whole. The messages still waiting come with the turn itself
    (take_waiting's "New instructions"), and the first message is the task's description."""
    entries: list[tuple[datetime, str]] = []
    messages = (await db.execute(
        select(Comment, User.name)
        .outerjoin(User, User.id == Comment.author_user_id)
        .where(Comment.task_id == task.id, Comment.delivery.in_(instructions.DELIVERED))
        .order_by(Comment.created_at, Comment.id)
    )).all()
    images = await instructions._image_names(db, [c.id for c, _ in messages])
    for c, name in messages:
        entries.append((c.created_at, instructions.frame_instruction(
            name or "someone", c.created_at, c.body_md, images.get(c.id, ()))))
    replies = (await db.execute(
        select(AgentRun, Agent.name)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(
            AgentRun.task_id == task.id,
            AgentRun.workflow_role == RunRole.freestyle,
            AgentRun.status.in_((RunStatus.completed, RunStatus.failed)),
            AgentRun.summary.is_not(None),
        )
        .order_by(AgentRun.created_at, AgentRun.id)
    )).all()
    for run, agent in replies:
        if not run.summary.strip():
            continue
        at = run.finished_at or run.started_at or run.created_at
        entries.append((at, f"[reply by {_escape(agent)} at {at:%Y-%m-%d %H:%M}]\n"
                        + wrap_untrusted("agent_reply", run.summary)))
    if not entries:
        return None
    entries.sort(key=lambda e: e[0])  # stable: at the same instant a message stays before a reply
    kept = [text for _, text in entries]
    dropped = 0

    def render() -> str:
        note = f"\n({dropped} older messages omitted to fit.)" if dropped else ""
        return f"{CONVERSATION_HEADING}\n{CONVERSATION_NOTE}{note}\n\n" + "\n\n".join(kept)

    while len(render()) > CONVERSATION_CHARS and len(kept) > 1:
        kept.pop(0)
        dropped += 1
    return render()


async def queue_turn(db: AsyncSession, wf: TaskWorkflow, task: Task, *, requested_by) -> AgentRun:
    """The next turn. No resume text: the person's message rides along as a waiting comment, taken at its start."""
    return await engine.enqueue(db, wf, task, RunRole.freestyle, requested_by=requested_by)


async def handle_turn_end(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    asked = await db.scalar(
        select(WorkflowQuestion.id)
        .where(WorkflowQuestion.run_id == run.id, WorkflowQuestion.status == QuestionStatus.open)
        .limit(1)
    )
    if asked is not None:
        await engine.wait_for(db, wf, Needs.question)
        return
    pending = await questions.undelivered_answer(db, task.id, run.id)
    if pending is not None:  # answered while the turn still ran: the session resumes with the answer
        await questions.deliver(db, wf, task, pending, requested_by=await engine.owner_id(db, run))
        return
    # a message sent after this turn was queued, and still unread (it came while the turn was queued, or couldn't be
    # read while it worked), is the next turn. One the turn started with and gave back unread (an agent that never
    # worked, release_on_run_end) waits for the turn the person's next message starts: it must not loop.
    waiting = await db.scalar(
        select(Comment.id)
        .where(
            Comment.task_id == task.id,
            Comment.to_agent_id.is_not(None),
            Comment.delivery == Delivery.waiting,
            Comment.created_at > run.created_at,
        )
        .limit(1)
    )
    if waiting is not None:
        await queue_turn(db, wf, task, requested_by=await engine.owner_id(db, run))
        return
    await engine.wait_for(db, wf, Needs.reply, notify=False)  # not a Needs you item: the turn just replied
    await _notify_replied(db, task, run)


async def _notify_replied(db: AsyncSession, task: Task, run: AgentRun) -> None:
    """The chat's starter hears once that the agent replied. A task not in a chat (none yet starts a freestyle
    round) falls back to the agent's owner, linked to the board."""
    agent = await db.get(Agent, run.agent_id)
    project = await db.get(Project, task.project_id)
    key = f"{project.key}-{task.number}"
    chat = None
    if task.chat_id is not None:
        from app.chats.models import Chat  # local: the chats modules import the engine
        from app.chats.service import chat_people

        chat = await db.get(Chat, task.chat_id)
    if chat is not None:
        (starter, _owner), link = await chat_people(db, task)
        recipients, title = [starter], f"{agent.name} replied in {chat.title}"
    else:
        recipients, link = [agent.owner_id], f"/projects/{project.key}/board?task={key}"
        title = f"{agent.name} replied on {key}"
    await notifications.notify(
        db, recipients, Kind.agent_replied, title=title, body=(run.summary or "")[:SUMMARY_CHARS], link=link,
        task_id=task.id, project_id=project.id,
    )


async def wait_after_failure(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    """A failed turn (or one cancelled by nothing a person did) waits for the next message: no retry, no escalation,
    nothing sent (the failure shows in the conversation), `wf.failures` untouched."""
    await engine.wait_for(db, wf, Needs.reply, notify=False)


engine.ROLE_HANDLERS[RunRole.freestyle] = handle_turn_end
