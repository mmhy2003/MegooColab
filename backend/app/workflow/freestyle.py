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
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.projects.models import Project
from app.tasks.models import Comment, Delivery, Task, TaskEvent
from app.workflow import engine, instructions, questions
from app.workflow.context import _escape, wrap_untrusted
from app.workflow.models import Needs, QuestionStatus, RunRole, TaskWorkflow, WorkflowQuestion

SUMMARY_CHARS = 500
CONVERSATION_CHARS = 12_000
CONVERSATION_HEADING = "## Conversation so far"
CONVERSATION_NOTE = "Earlier in this conversation, oldest first: the person's messages and your replies."
REPLY_CHARS = 4_000
# what the agent streams while it works: a reply is the messages after the last of the others
STREAMED_KINDS = (*instructions.AGENT_OUTPUT_KINDS, "agent_permission")


async def _replies(db: AsyncSession, task: Task, runs: list[AgentRun]) -> dict[str, str]:
    """Each turn's reply, by run id: its last message, the newest REPLY_CHARS. The runner streams a message in
    chunks (fragments of one text: joined as they are) and reports only the last one as the run's summary, so the
    reply is the turn's last unbroken run of message updates. A turn that streamed no message has none here."""
    if not runs:
        return {}
    rows = (await db.execute(
        select(TaskEvent.kind, TaskEvent.data)
        .where(
            TaskEvent.task_id == task.id,
            TaskEvent.kind.in_(STREAMED_KINDS),
            TaskEvent.data["run_id"].astext.in_([str(r.id) for r in runs]),
        )
        .order_by(TaskEvent.created_at, TaskEvent.id)
    )).all()
    last: dict[str, list[str]] = {}
    broken: set[str] = set()  # runs whose message was interrupted since: the next message starts a new one
    for kind, data in rows:
        run_id = str(data.get("run_id"))
        if kind != "agent_message":
            broken.add(run_id)
            continue
        if run_id in broken or run_id not in last:
            last[run_id] = []
            broken.discard(run_id)
        last[run_id].append(str(data.get("text") or ""))
    return {run_id: text[-REPLY_CHARS:] for run_id, chunks in last.items() if (text := "".join(chunks).strip())}


async def conversation_so_far(db: AsyncSession, task: Task) -> str | None:
    """For a turn starting a fresh session: every message the agent was given and, for every ended turn, its reply
    (its last message, else the run's summary; the agent's own text: wrapped as untrusted), in order. The oldest
    are cut to fit CONVERSATION_CHARS; the newest is always kept whole. The messages still waiting come with the
    turn itself (take_waiting's "New instructions"), and the first message is the task's description."""
    entries: list[tuple[datetime, str]] = [
        (c.created_at, text) for c, text in await instructions.framed_messages(db, task, instructions.DELIVERED)
    ]
    turns = (await db.execute(
        select(AgentRun, Agent.name)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(
            AgentRun.task_id == task.id,
            AgentRun.workflow_role == RunRole.freestyle,
            AgentRun.status.in_((RunStatus.completed, RunStatus.failed)),
        )
        .order_by(AgentRun.created_at, AgentRun.id)
    )).all()
    replies = await _replies(db, task, [run for run, _ in turns])
    for run, agent in turns:
        reply = replies.get(str(run.id)) or (run.summary or "").strip()
        if not reply:
            continue
        at = run.finished_at or run.started_at or run.created_at
        entries.append((at, f"[reply by {_escape(agent)} at {at:%Y-%m-%d %H:%M}]\n"
                        + wrap_untrusted("agent_reply", reply)))
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
