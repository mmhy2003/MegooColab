"""Agent chats: a conversation with an agent about one project, each round of work a task kept off the board and run
by the task workflow (talk, design, plan, build, finish), as a task would be."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunStatus
from app.agents.models import Agent, AgentBinding
from app.agents.service import can_use_agent, is_usable_binding, owner_can_access
from app.auth.models import Role, User
from app.auth.schemas import UserOut
from app.chats.models import Chat, ChatStatus
from app.chats.schemas import (
    BoardDefaults,
    BoardIn,
    ChatAgentOut,
    ChatIn,
    ChatOut,
    ChatState,
    Intent,
    RoundOut,
)
from app.git.models import PR_MAIN, TaskPullRequest
from app.images.files import MessageKind
from app.images.links import images_of, link_images
from app.images.support import agent_takes_images, task_takes_images
from app.notifications import service as notifications
from app.projects.access import accessible_project_ids, get_project_for
from app.projects.models import BoardColumn, ColumnCategory, Project, ProjectRepository
from app.runner.registry import registry
from app.tasks.models import Task, TaskType
from app.tasks.schemas import TaskCreate
from app.workflow.models import (
    MERGE_WAITS,
    DocKind,
    DocStatus,
    Needs,
    QuestionStatus,
    Stage,
    TaskWorkflow,
    WorkflowDocument,
    WorkflowQuestion,
    WorkflowStatus,
)

TITLE_CHARS = 120
NEEDS_STATE: dict[Needs, ChatState] = {
    Needs.question: "question",
    Needs.design_approval: "design_approval",
    Needs.plan_approval: "plan_approval",
    Needs.escalation: "escalation",
    Needs.human_code_review: "human_code_review",
    Needs.merge_confirmation: "merging",  # an agent merged: not a wait on anyone
}


def _now() -> datetime:
    return datetime.now(UTC)


def first_line(text: str, limit: int = TITLE_CHARS) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "Chat")
    return line[:limit]


def chat_link(chat_id: uuid.UUID) -> str:
    return f"/chats/{chat_id}"


async def touch(db: AsyncSession, chat_id: uuid.UUID) -> None:
    chat = await db.get(Chat, chat_id)
    if chat is not None:
        chat.last_activity_at = _now()


async def chat_people(db: AsyncSession, task: Task) -> tuple[list[uuid.UUID | None], str]:
    """Who hears about a chat round (the person who started the chat and the agent's owner), and the link."""
    chat = await db.get(Chat, task.chat_id)
    agent_id = task.assignee_agent_id or (chat.agent_id if chat else None)
    owner = await db.scalar(select(Agent.owner_id).where(Agent.id == agent_id)) if agent_id else None
    return [chat.started_by if chat else None, owner], chat_link(task.chat_id)


# ---- who sees a chat ---------------------------------------------------------------------------------------------


async def can_see_chat(db: AsyncSession, user: User, chat: Chat) -> bool:
    """The person who started it, the agent's owner, the project's managers and admins."""
    if user.role == Role.admin:
        return True
    allowed = await accessible_project_ids(db, user)
    if allowed is not None and chat.project_id not in allowed:
        return False
    if user.role == Role.manager or chat.started_by == user.id:  # a manager in one of the project's teams
        return True
    owner = await db.scalar(select(Agent.owner_id).where(Agent.id == chat.agent_id)) if chat.agent_id else None
    return owner == user.id


async def get_chat_for(db: AsyncSession, user: User, chat_id: uuid.UUID) -> Chat:
    chat = await db.get(Chat, chat_id)
    if chat is None or not await can_see_chat(db, user, chat):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return chat


def visible_chat_ids(user: User):
    """The chats the user can see, as a subquery of ids, within projects the caller already limits to theirs:
    admins and managers every chat there, others the chats they started or whose agent is theirs."""
    stmt = select(Chat.id)
    if user.role not in (Role.admin, Role.manager):
        owned = select(Agent.id).where(Agent.owner_id == user.id)
        stmt = stmt.where(or_(Chat.started_by == user.id, Chat.agent_id.in_(owned)))
    return stmt


async def waiting_count(db: AsyncSession, user: User, project_ids: frozenset[uuid.UUID] | set[uuid.UUID] | None = None) -> int:
    """Open chats the user can see that wait on a person (a question, an approval, an escalation): the badge."""
    allowed = await accessible_project_ids(db, user)
    stmt = (
        select(func.count(func.distinct(Chat.id)))
        .join(Task, Task.chat_id == Chat.id)
        .join(TaskWorkflow, TaskWorkflow.task_id == Task.id)
        .where(Chat.status == ChatStatus.open, Chat.id.in_(visible_chat_ids(user)),
               TaskWorkflow.status == WorkflowStatus.waiting_human,
               TaskWorkflow.needs.in_((Needs.question, Needs.design_approval, Needs.plan_approval, Needs.escalation)))
    )
    if allowed is not None:
        stmt = stmt.where(Chat.project_id.in_(allowed))
    if project_ids is not None:
        stmt = stmt.where(Chat.project_id.in_(project_ids))
    return int(await db.scalar(stmt) or 0)


async def lock_chat(db: AsyncSession, chat: Chat) -> Chat:
    """Every change to a chat starts here: the chat row locked and read afresh (lock order: chat, task, workflow),
    in a project still open."""
    from app.projects.models import ProjectStatus

    chat = (await db.execute(
        select(Chat).where(Chat.id == chat.id).with_for_update().execution_options(populate_existing=True)
    )).scalar_one()
    if (await db.get(Project, chat.project_id)).status != ProjectStatus.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "project_closed")
    return chat


async def visible_chats(db: AsyncSession, user: User, project_key: str | None = None) -> list[Chat]:
    stmt = select(Chat)
    if project_key:
        project = await get_project_for(db, user, project_key)
        stmt = stmt.where(Chat.project_id == project.id)
    if user.role != Role.admin:
        allowed = await accessible_project_ids(db, user) or set()
        stmt = stmt.where(Chat.project_id.in_(allowed))
        if user.role != Role.manager:
            owned = select(Agent.id).where(Agent.owner_id == user.id)
            stmt = stmt.where(or_(Chat.started_by == user.id, Chat.agent_id.in_(owned)))
    return list((await db.execute(stmt.order_by(Chat.last_activity_at.desc()))).scalars())


# ---- starting a chat -----------------------------------------------------------------------------------------------


async def pick_agent(db: AsyncSession, user: User, project: Project) -> Agent:
    """Any free agent the person may use on the project: online first, then the least busy, then by name."""
    agents = (
        await db.execute(
            select(Agent)
            .join(AgentBinding, AgentBinding.agent_id == Agent.id)
            .where(AgentBinding.project_id == project.id, owner_can_access(project.id))
        )
    ).scalars().all()
    usable = [a for a in agents if await can_use_agent(db, user, a, project)]
    if not usable:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no_agent")
    counts = dict(
        (await db.execute(
            select(AgentRun.agent_id, func.count())
            .where(AgentRun.agent_id.in_([a.id for a in usable]), AgentRun.status.in_(ACTIVE_STATUSES))
            .group_by(AgentRun.agent_id)
        )).all()
    )
    return min(usable, key=lambda a: (not registry.is_available(a.id), counts.get(a.id, 0), a.name.lower()))


async def _chosen_agent(db: AsyncSession, user: User, project: Project, agent_id: uuid.UUID | None) -> Agent:
    if agent_id is None:
        return await pick_agent(db, user, project)
    agent = await db.get(Agent, agent_id)
    if (
        agent is None
        or not await is_usable_binding(db, agent.id, project.id)
        or not await can_use_agent(db, user, agent, project)
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_not_available")
    return agent


async def create_round(
    db: AsyncSession, user: User, chat: Chat, message: str, *, branch_from: str | None = None
) -> Task:
    """The next round: a task kept off the board, assigned to the chat's agent, its workflow started."""
    from app.tasks.service import create_task  # local: the task modules import this one
    from app.workflow import engine

    project = await db.get(Project, chat.project_id)
    n = (await db.scalar(select(Task.chat_round).where(Task.chat_id == chat.id).order_by(Task.chat_round.desc()))) or 0
    title = chat.title if n == 0 else first_line(message, 500)
    task = await create_task(
        db, user, project,
        TaskCreate(title=title, type=TaskType.task, description_md=message, assignee_agent_id=chat.agent_id,
                   branch_from=branch_from),
        chat_id=chat.id, chat_round=n + 1,
    )
    await engine.start(db, user, task)
    chat.last_activity_at = _now()
    return task


async def start_chat(db: AsyncSession, user: User, data: ChatIn) -> Chat:
    project = await get_project_for(db, user, data.project_key, write=True)
    agent = await _chosen_agent(db, user, project, data.agent_id)
    chat = Chat(project_id=project.id, started_by=user.id, agent_id=agent.id, title=first_line(data.message))
    db.add(chat)
    await db.flush()
    task = await create_round(db, user, chat, data.message)
    await link_images(db, user, data.image_ids, task, MessageKind.first_message, task.id)
    return chat


# ---- what a chat shows ---------------------------------------------------------------------------------------------


async def rounds_of(db: AsyncSession, chat: Chat) -> list[tuple[Task, TaskWorkflow | None]]:
    rows = await db.execute(
        select(Task, TaskWorkflow)
        .outerjoin(TaskWorkflow, TaskWorkflow.task_id == Task.id)
        .where(Task.chat_id == chat.id)
        .order_by(Task.chat_round)
    )
    return [(t, wf) for t, wf in rows.all()]


async def _steps_total(db: AsyncSession, task_id: uuid.UUID) -> int | None:
    plan = await db.scalar(
        select(WorkflowDocument)
        .where(WorkflowDocument.task_id == task_id, WorkflowDocument.kind == DocKind.plan,
               WorkflowDocument.status == DocStatus.approved)
        .order_by(WorkflowDocument.version.desc())
        .limit(1)
    )
    return len(plan.steps or []) if plan else None


def chat_state(chat: Chat, wf: TaskWorkflow | None, *, run_queued: bool, agent_online: bool) -> ChatState:
    if chat.status == ChatStatus.ended:
        return "ended"
    if wf is None:
        return "talking"
    if wf.status == WorkflowStatus.finished:
        return "finished"
    if wf.needs is not None:
        return NEEDS_STATE[Needs(wf.needs)]
    if run_queued and not agent_online:
        return "offline"
    if wf.stage == Stage.review:
        return "in_review"
    if wf.stage == Stage.build:
        return "building"
    return "talking"


def _board(task: Task, wf: TaskWorkflow | None, chat: Chat) -> str | None:
    if task.chat_board:
        return task.chat_board
    done = wf is not None and wf.status == WorkflowStatus.finished
    return "pending" if done or chat.status == ChatStatus.ended else None


async def chat_out(db: AsyncSession, chat: Chat, viewer: User | None) -> ChatOut:
    from app.workflow import engine
    from app.workflow.rules import can_act

    project = await db.get(Project, chat.project_id)
    agent = await db.get(Agent, chat.agent_id) if chat.agent_id else None
    starter = await db.get(User, chat.started_by) if chat.started_by else None
    rounds = await rounds_of(db, chat)
    first_images = await images_of(db, [t.id for t, _ in rounds])  # each round's first message's
    out_rounds = [
        RoundOut(
            n=t.chat_round or 0, key=f"{project.key}-{t.number}", title=t.title,
            stage=wf.stage if wf else None, status=wf.status if wf else None, needs=wf.needs if wf else None,
            current_step=wf.current_step if wf else None, steps_total=await _steps_total(db, t.id),
            finish_outcome=wf.finish_outcome if wf else None, pr_url=wf.pr_url if wf else None,
            branch=wf.branch if wf else None, branch_from=t.branch_from, board=_board(t, wf, chat),
            images=first_images.get(t.id, []),
        )
        for t, wf in rounds
    ]
    latest, latest_wf = rounds[-1] if rounds else (None, None)
    run = await engine.active_run(db, latest.id) if latest is not None else None
    state = chat_state(
        chat, latest_wf, run_queued=run is not None and run.status == RunStatus.queued,
        agent_online=agent is not None and registry.is_available(agent.id),
    )
    # an ended chat still asks its people about the board; intent() closes the message box
    acting = viewer is not None and latest is not None and can_act(
        viewer, latest, latest_wf, await engine.manages(db, viewer, project), agent.owner_id if agent else None
    )
    return ChatOut(
        id=chat.id, project_key=project.key, title=chat.title, status=chat.status,
        agent=ChatAgentOut(id=agent.id, name=agent.name, program=agent.program) if agent else None,
        started_by=UserOut.model_validate(starter) if starter else None,
        created_at=chat.created_at, last_activity_at=chat.last_activity_at, state=state, can_act=acting,
        intent=await intent(db, chat, latest, latest_wf) if acting else "closed", rounds=out_rounds,
        takes_images=await task_takes_images(db, latest) if latest is not None else await agent_takes_images(db, agent),
    )


WAITING: tuple[ChatState, ...] = ("question", "design_approval", "plan_approval", "escalation")


async def chats_out(db: AsyncSession, chats: list[Chat], viewer: User) -> list[ChatOut]:
    """Chats waiting on the viewer first, then the most recently active."""
    out = [await chat_out(db, c, viewer) for c in chats]
    return sorted(out, key=lambda c: (not (c.can_act and c.state in WAITING), -c.last_activity_at.timestamp()))


# ---- a message typed in the chat ----------------------------------------------------------------------------------

DECIDED_BY_MESSAGE = {Needs.design_approval: DocKind.design, Needs.plan_approval: DocKind.plan}


async def intent(db: AsyncSession, chat: Chat, task: Task | None, wf: TaskWorkflow | None) -> Intent:
    """What a message typed now does: answer the agent's question, ask for changes to the design or plan waiting,
    tell the working agent, start it again, or start the next round."""
    from app.workflow import engine

    if chat.status == ChatStatus.ended or task is None or wf is None:
        return "closed"
    if wf.status == WorkflowStatus.finished:
        return "new_round"
    if wf.needs == Needs.question:
        return "answer"
    if wf.needs in DECIDED_BY_MESSAGE:
        return "changes"
    if await engine.active_run(db, task.id) is not None:
        return "tell"
    if wf.status == WorkflowStatus.paused:  # cancelled, or an escalation decided as pause: the message resumes it
        return "restart"
    if wf.needs is None and wf.status == WorkflowStatus.running:
        return "restart"
    return "tell"  # an escalation or a code review waits: the agent gets it at its next run


async def latest_round(db: AsyncSession, chat: Chat) -> Task | None:
    return await db.scalar(select(Task).where(Task.chat_id == chat.id).order_by(Task.chat_round.desc()).limit(1))


async def start_next_round(db: AsyncSession, user: User, chat: Chat, message: str) -> Task:
    """The next round, once the last one finished. It builds on the last round's branch while that round's pull
    request is still open, so the changes stack; otherwise it starts from the default branch."""
    prev = await latest_round(db, chat)
    wf = await db.get(TaskWorkflow, prev.id) if prev is not None else None
    if wf is None or wf.status != WorkflowStatus.finished:
        raise HTTPException(status.HTTP_409_CONFLICT, "round_not_finished")
    branch_from = None
    # stacking needs a repository the runner can start the branch in (Branch from); without one, start afresh
    has_repository = await db.scalar(
        select(ProjectRepository.id).where(ProjectRepository.project_id == chat.project_id).limit(1)
    )
    if wf.finish_outcome == "pr_opened" and wf.branch and has_repository:
        pr_state = await db.scalar(
            select(TaskPullRequest.state).where(TaskPullRequest.task_id == prev.id, TaskPullRequest.kind == PR_MAIN)
        )
        if pr_state != "merged":
            branch_from = wf.branch
    return await create_round(db, user, chat, message, branch_from=branch_from)


async def send_message(
    db: AsyncSession, user: User, chat: Chat, body: str, images: Sequence[uuid.UUID] = ()
) -> tuple[Intent, Task, uuid.UUID | None]:
    """Does what the chat waits for, decided under the round's lock. Returns the intent, the round, and the id of a
    message for the agent to hand into its running session after the commit."""
    from app.tasks.activity import create_comment
    from app.workflow import documents, engine, questions

    chat = await lock_chat(db, chat)  # an End chat or a new round in between is seen
    task = await latest_round(db, chat)
    if chat.status == ChatStatus.ended or task is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "chat_ended")
    wf = await engine.lock_task(db, task)
    await engine.require_actor(db, user, task, wf)
    # replying is acting on the chat: what its latest round told this person is dealt with
    await notifications.read_by_acting(db, user.id, task_id=task.id)
    project = await db.get(Project, task.project_id)
    key = f"{project.key}-{task.number}"
    what = await intent(db, chat, task, wf)
    steer = None
    if what == "answer":
        qid = await db.scalar(
            select(WorkflowQuestion.id)
            .where(WorkflowQuestion.task_id == task.id, WorkflowQuestion.status == QuestionStatus.open)
            .order_by(WorkflowQuestion.created_at.desc())
            .limit(1)
        )
        await questions.answer(db, user, task, qid, None, body, images)
    elif what == "changes":
        kind = DECIDED_BY_MESSAGE[Needs(wf.needs)]
        version = await db.scalar(
            select(WorkflowDocument.version)
            .where(WorkflowDocument.task_id == task.id, WorkflowDocument.kind == kind,
                   WorkflowDocument.status == DocStatus.submitted)
            .order_by(WorkflowDocument.version.desc())
            .limit(1)
        )
        await documents.decide(db, user, task, kind, version, False, body, images)
    elif what == "tell":
        steer = (await create_comment(db, user, key, body, to_agent=True, image_ids=images)).id
    elif what == "restart" and wf.status == WorkflowStatus.paused:
        await engine.resume(db, user, task)
        # the resumed run takes it at its start (or a wait it returns to keeps it for the next run)
        await create_comment(db, user, key, body, to_agent=True, image_ids=images)
    elif what == "restart":
        run = await engine.hand_to_agent(
            db, wf, task, engine.STAGE_ROLE[Stage(wf.stage)], resume_kind="nudge", payload={"text": body},
            requested_by=user.id,
        )
        # the images go with the run the message starts (a connect-only round has none: then with the round)
        await link_images(db, user, images, task, MessageKind.nudge, run.id if run is not None else task.id)
    elif what == "new_round":
        task = await start_next_round(db, user, chat, body)
        await link_images(db, user, images, task, MessageKind.first_message, task.id)
    chat.last_activity_at = _now()
    return what, task, steer


# ---- ending, and the board -------------------------------------------------------------------------------------


async def end_chat(db: AsyncSession, user: User, chat: Chat) -> Chat:
    """Ends the chat for good. A round still working stops (its branch keeps what was done); a round in code
    review keeps waiting, so its pull request is still followed; so does an agent's merge that couldn't be confirmed
    (a later read that sees the merge still finishes it)."""
    from app.workflow import engine

    chat = await lock_chat(db, chat)
    task = await latest_round(db, chat)
    if chat.status == ChatStatus.ended:
        raise HTTPException(status.HTTP_409_CONFLICT, "chat_ended")
    if task is not None:
        wf = await engine.lock_task(db, task)
        await engine.require_actor(db, user, task, wf)
        await notifications.read_by_acting(db, user.id, task_id=task.id)
        unconfirmed = wf is not None and wf.needs == Needs.escalation and wf.escalation_reason == "merge_not_confirmed"
        if wf is not None and wf.status in engine.ACTIVE and wf.needs not in MERGE_WAITS and not unconfirmed:
            await engine.pause(db, user, task)
    chat.status = ChatStatus.ended
    chat.ended_at = _now()
    chat.last_activity_at = chat.ended_at
    return chat


async def _round_n(db: AsyncSession, chat: Chat, n: int) -> tuple[Task, TaskWorkflow | None]:
    task = await db.scalar(select(Task).where(Task.chat_id == chat.id, Task.chat_round == n))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return task, await db.get(TaskWorkflow, task.id)


async def _first_column(db: AsyncSession, project_id: uuid.UUID, category: ColumnCategory) -> BoardColumn | None:
    return await db.scalar(
        select(BoardColumn)
        .where(BoardColumn.project_id == project_id, BoardColumn.category == category)
        .order_by(BoardColumn.position)
        .limit(1)
    )


def _board_outcome(wf: TaskWorkflow | None) -> str:
    from app.chats.context import outcome_line

    if wf is not None and wf.needs in MERGE_WAITS:
        return f"in code review ({wf.pr_url})" if wf.pr_url else "in code review"
    return outcome_line(wf)


async def board_defaults(db: AsyncSession, chat: Chat, n: int) -> BoardDefaults:
    """What "Add this to the board?" proposes: the round's title, a description of what was asked and done, and the
    column that matches where the work is."""
    task, wf = await _round_n(db, chat, n)
    if wf is not None and wf.status == WorkflowStatus.finished:
        column = await _first_column(db, task.project_id, ColumnCategory.done)
    elif wf is not None and (wf.needs in MERGE_WAITS or wf.stage == Stage.review):
        column = await _first_column(db, task.project_id, ColumnCategory.review)
    else:
        column = None
    column = column or await _first_column(db, task.project_id, ColumnCategory.before)
    description = (
        f"{task.description_md}\n\n**Outcome:** {_board_outcome(wf)}\n\nFrom the chat: {chat_link(chat.id)}"
    )
    return BoardDefaults(title=task.title, description_md=description, column_id=column.id)


async def _step_cards(db: AsyncSession, user: User, task: Task, wf: TaskWorkflow | None) -> None:
    """The plan's steps as subtasks, as tasks get them, each in the state its step reached."""
    from app.tasks.service import create_task, task_changed
    from app.workflow.documents import MAX_SUBTASK_TITLE

    plan = await db.scalar(
        select(WorkflowDocument)
        .where(WorkflowDocument.task_id == task.id, WorkflowDocument.kind == DocKind.plan,
               WorkflowDocument.status == DocStatus.approved)
        .order_by(WorkflowDocument.version.desc())
        .limit(1)
        .with_for_update()
    )
    if plan is None or not plan.steps:
        return
    project = await db.get(Project, task.project_id)
    done = await _first_column(db, task.project_id, ColumnCategory.done)
    before = await _first_column(db, task.project_id, ColumnCategory.before)
    # finished, or past the build (in review, or waiting for a person's code review): every step was done
    finished = wf is not None and (
        wf.status == WorkflowStatus.finished or wf.stage in (Stage.review, Stage.done)
        or wf.needs in MERGE_WAITS
    )
    current = (wf.current_step or 1) if wf is not None else 1
    steps = []
    for n, step in enumerate(plan.steps, start=1):
        column = done if finished or n < current else before
        sub = await create_task(db, user, project, TaskCreate(
            title=f"Step {n}: {step.get('title', '')}"[:MAX_SUBTASK_TITLE], type=TaskType.subtask,
            description_md=step.get("detail", ""), column_id=column.id, parent_id=task.id,
        ))
        await task_changed(db, sub, "task.created")
        steps.append({**step, "subtask_id": str(sub.id)})
    plan.steps = steps  # a new list: edits inside nested dicts are not tracked


async def decide_board(db: AsyncSession, user: User, chat: Chat, n: int, data: BoardIn) -> Task:
    """Adds a finished round (or a round of an ended chat) to the board as an ordinary task, or leaves it out.
    Decided once."""
    from app.tasks.service import apply_column, end_position, get_column, task_changed
    from app.workflow import engine

    chat = await lock_chat(db, chat)
    task, _ = await _round_n(db, chat, n)
    wf = await engine.lock_task(db, task)
    await engine.require_actor(db, user, task, wf)
    await notifications.read_by_acting(db, user.id, task_id=task.id)
    task = await db.get(Task, task.id, populate_existing=True)
    if task.chat_board:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_decided")
    if not ((wf is not None and wf.status == WorkflowStatus.finished) or chat.status == ChatStatus.ended):
        raise HTTPException(status.HTTP_409_CONFLICT, "round_not_finished")
    if not data.add:
        task.chat_board = "declined"
        return task
    defaults = await board_defaults(db, chat, n)
    project = await db.get(Project, task.project_id)
    column = await get_column(db, project, data.column_id or defaults.column_id)
    task.in_chat = False
    task.chat_board = "added"
    task.title = data.title or defaults.title
    task.description_md = data.description_md if data.description_md is not None else defaults.description_md
    if task.column_id != column.id:
        task.position = await end_position(db, column.id)
        apply_column(task, column)
    await db.flush()
    await _step_cards(db, user, task, wf)
    await task_changed(db, task, "task.created")
    return task


async def round_out(db: AsyncSession, chat: Chat, task: Task) -> RoundOut:
    out = await chat_out(db, chat, None)
    return next(r for r in out.rounds if r.n == task.chat_round)
