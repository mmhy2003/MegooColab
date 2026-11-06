"""A freestyle round (freestyle chats): no stages, no reviews. Each person's message is a turn, one `freestyle` run
that does what it asks and replies.

When a turn ends:
  an open question it asked      -> wait for the answer (Needs.question)
  an answer that never reached it -> deliver it (the session resumes with it)
  a message still waiting          -> the next turn starts on its own
  otherwise                        -> wait for the next message (Needs.reply), and tell the chat's starter once
A failed turn, or one cancelled by nothing a person did, waits for the next message too: never a retry, never an
escalation, and `wf.failures` is not counted (a turn that always fails cannot loop).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import AgentRun
from app.agents.models import Agent
from app.notifications import service as notifications
from app.notifications.models import Kind
from app.projects.models import Project
from app.tasks.models import Comment, Delivery, Task
from app.workflow import engine, questions
from app.workflow.models import Needs, QuestionStatus, RunRole, TaskWorkflow, WorkflowQuestion

SUMMARY_CHARS = 500


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
    waiting = await db.scalar(
        select(Comment.id).where(Comment.task_id == task.id, Comment.delivery == Delivery.waiting).limit(1)
    )
    if waiting is not None:  # sent while the turn was queued, or never read while it worked: it is the next turn
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
