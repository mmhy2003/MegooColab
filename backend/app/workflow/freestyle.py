"""A freestyle round (freestyle chats): no stages, no reviews. Each person's message is a turn, one `freestyle` run
that does what it asks and replies.

When a turn ends:
  an open question it asked       -> wait for the answer (Needs.question)
  an answer that never reached it -> deliver it (the session resumes with it)
  a message sent since it queued  -> the next turn starts on its own
  otherwise                       -> wait for the next message (Needs.reply), and tell the chat's starter once;
                                     a chat a trigger started ends here instead, unless the trigger keeps it open
A failed turn, or one cancelled by nothing a person did, waits for the next message too: never a retry, never an
escalation, and `wf.failures` is not counted (a turn that always fails cannot loop). A triggered chat stays open.
On a triggered chat's first turn the starter is told only as the trigger's switches say (notify_reply for a reply,
notify_problems for a failure); later turns are told as any other.

What a turn is told: the person's messages in freestyle's own words (instructions.FREESTYLE_RULE). A turn that
resumes the conversation's session gets only the new ones; one that starts fresh gets the conversation so far.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.projects.models import Project
from app.tasks import cards as cards_service
from app.tasks.models import Comment, Delivery, Task, TaskEvent
from app.workflow import engine, instructions, questions
from app.workflow.context import _escape, wrap_untrusted
from app.workflow.models import Needs, QuestionStatus, RunRole, Stage, TaskWorkflow, WorkflowQuestion

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
    (its last message, else the run's summary) followed by the title and text of each card it showed (the agent's own
    text: wrapped as untrusted), in order. A turn with neither is left out. The oldest
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
    cards = await cards_service.of_runs(db, [run.id for run, _ in turns])
    for run, agent in turns:
        reply = replies.get(str(run.id)) or (run.summary or "").strip()
        reply = "\n\n".join([reply, *(f"Card: {c.title}\n{c.text}" for c in cards.get(run.id, []))]).strip()
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
    await _end_if_triggered(db, wf, task)
    await _notify_replied(db, task, run)


async def _end_if_triggered(db: AsyncSession, wf: TaskWorkflow, task: Task) -> bool:
    """A chat a trigger started, and not kept open, ends once the agent replied: the round finishes as on "End
    chat", with nobody told it finished (the reply is). A chat a person is acting on (locked) or already ended stays
    as it is. Skipping a locked chat keeps the lock order chat -> task -> workflow safe."""
    from app.chats.models import Chat, ChatStatus  # local: the chats modules import the engine
    from app.triggers.service import firing_of_chat  # local: the triggers start chats
    from app.workflow import finish  # local: finish imports the engine, which imports this module

    firing = await firing_of_chat(db, task.chat_id) if task.chat_id is not None else None
    if firing is None or firing.keep_open:
        return False
    chat = (await db.execute(
        select(Chat).where(Chat.id == task.chat_id).with_for_update(skip_locked=True)
    )).scalar_one_or_none()
    if chat is None or chat.status == ChatStatus.ended:
        return False
    wf.stage = Stage.done
    await finish.finish_workflow(db, wf, task, None, tell=False)
    chat.status = ChatStatus.ended
    chat.ended_at = chat.last_activity_at = datetime.now(UTC)
    return True


async def _silenced(db: AsyncSession, task: Task, run: AgentRun, *, failed: bool) -> bool:
    """On the turn a trigger started (the round's first freestyle run), the trigger's switch says whether the
    starter hears of it."""
    from app.triggers.models import Trigger  # local: the triggers start chats
    from app.triggers.service import firing_of_chat

    firing = await firing_of_chat(db, task.chat_id) if task.chat_id is not None else None
    if firing is None:
        return False
    earlier = await db.scalar(
        select(AgentRun.id)
        .where(
            AgentRun.task_id == task.id,
            AgentRun.workflow_role == RunRole.freestyle,
            AgentRun.id != run.id,
            AgentRun.created_at <= run.created_at,
        )
        .limit(1)
    )
    if earlier is not None:
        return False
    trigger = await db.get(Trigger, firing.trigger_id)
    return not (trigger.notify_problems if failed else trigger.notify_reply)


async def _notify_replied(db: AsyncSession, task: Task, run: AgentRun, *, failed: bool = False) -> None:
    """The chat's starter hears once that the turn ended: the agent replied, or couldn't finish (unless the trigger
    that started the turn says not to). A task not in a chat (none yet starts a freestyle round) falls back to the
    agent's owner, linked to the board. A reply's body is the reply, then a line for each card the turn showed (its
    title and text), cut to SUMMARY_CHARS."""
    if await _silenced(db, task, run, failed=failed):
        return
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
        recipients, where = [starter], f"in {chat.title}"
    else:
        recipients, link = [agent.owner_id], f"/projects/{project.key}/board?task={key}"
        where = f"on {key}"
    if failed:
        title = f"{agent.name} couldn't finish {chat.title if chat is not None else key}"
        body = run.reason.replace("_", " ") if run.reason else "the run failed"
    else:
        title = f"{agent.name} replied {where}"
        reply = (await _replies(db, task, [run])).get(str(run.id)) or run.summary or ""
        cards = (await cards_service.of_runs(db, [run.id])).get(run.id, [])
        body = "\n".join(p for p in [reply, *(f"Card: {c.title}. {c.text}" for c in cards)] if p)[:SUMMARY_CHARS]
    await notifications.notify(
        db, recipients, Kind.agent_replied, title=title, body=body, link=link,
        task_id=task.id, project_id=project.id,
    )


async def wait_after_failure(db: AsyncSession, wf: TaskWorkflow, task: Task, run: AgentRun) -> None:
    """A failed turn (or one cancelled by nothing a person did) waits for the next message: no retry, no escalation,
    `wf.failures` untouched. The starter hears once, as for a reply (a long turn must not fail unnoticed)."""
    await engine.wait_for(db, wf, Needs.reply, notify=False)
    await _notify_replied(db, task, run, failed=True)


engine.ROLE_HANDLERS[RunRole.freestyle] = handle_turn_end
