"""Knowledge Base drafts written with an agent: starting one, the person's own edits, keeping or undoing the agent's
changes, choosing the agent, and discarding. The agent's turns are in turns.py."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_runs.models import ACTIVE_STATUSES, AgentRun, RunStatus
from app.agents.models import Agent, AgentBinding
from app.agents.service import can_use_agent, is_usable_binding, owner_can_access
from app.auth.models import User
from app.core.events import Event, publish
from app.images.support import runner_has
from app.kb import access
from app.kb import service as kb
from app.kb.models import KbDocument, KbSpace, SpaceKind
from app.kb.schemas import Named
from app.kb_drafts import blocks
from app.kb_drafts.models import KbDraft, KbDraftMessage
from app.kb_drafts.schemas import (
    DocSource,
    DraftAgentOut,
    DraftDocument,
    DraftIn,
    DraftMessageOut,
    DraftOut,
    DraftSummary,
    Segment,
    TaskSource,
)
from app.projects.models import Project
from app.runner.registry import DRAFTS_CAPABILITY, registry
from app.tasks.service import get_task_for

SOURCES_CHARS_MAX = 500_000


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "draft_not_found")


# -- agents ----------------------------------------------------------------------------------------


async def usable_agents(db: AsyncSession, user: User, space: KbSpace) -> list[Agent]:
    """A project's space: the project's agents the person may use, as in chats. Any other space: the person's own."""
    if space.kind == SpaceKind.project:
        project = await db.get(Project, space.project_id)
        agents = (
            await db.execute(
                select(Agent)
                .join(AgentBinding, AgentBinding.agent_id == Agent.id)
                .where(AgentBinding.project_id == project.id, owner_can_access(project.id))
            )
        ).scalars().all()
        agents = [a for a in agents if await can_use_agent(db, user, a, project)]
    else:
        agents = (await db.execute(select(Agent).where(Agent.owner_id == user.id))).scalars().all()
    return sorted(agents, key=lambda a: (not registry.is_available(a.id), a.name.lower()))


async def check_agent(db: AsyncSession, user: User, space: KbSpace, agent_id: uuid.UUID | None) -> Agent:
    agent = await db.get(Agent, agent_id) if agent_id else None
    if agent is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_not_available")
    if space.kind == SpaceKind.project:
        project = await db.get(Project, space.project_id)
        ok = await is_usable_binding(db, agent.id, project.id) and await can_use_agent(db, user, agent, project)
    else:
        ok = agent.owner_id == user.id
    if not ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_not_available")
    return agent


async def agent_out(db: AsyncSession, agent: Agent) -> DraftAgentOut:
    return DraftAgentOut(id=agent.id, name=agent.name, online=registry.is_available(agent.id),
                         runner_ok=await runner_has(db, agent, DRAFTS_CAPABILITY))


async def list_agents(db: AsyncSession, user: User, space_id: uuid.UUID) -> list[DraftAgentOut]:
    space = await access.get_space_for(db, user, space_id, write=True)
    return [await agent_out(db, a) for a in await usable_agents(db, user, space)]


# -- reading and locking ---------------------------------------------------------------------------


async def get_draft_for(db: AsyncSession, user: User, draft_id: uuid.UUID, *, lock: bool = False) -> KbDraft:
    """The person's own draft (404 for anyone else's), in a space they may still write in (403)."""
    stmt = select(KbDraft).where(KbDraft.id == draft_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    draft = (await db.execute(stmt)).scalar_one_or_none()
    if draft is None or draft.user_id != user.id:
        raise _not_found()
    space = await db.get(KbSpace, draft.space_id)
    if space is None or not await access.can_write(db, user, space):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return draft


async def active_run(db: AsyncSession, draft_id: uuid.UUID) -> AgentRun | None:
    return (
        await db.execute(
            select(AgentRun)
            .where(AgentRun.draft_id == draft_id, AgentRun.status.in_(ACTIVE_STATUSES))
            .order_by(AgentRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def refuse_while_writing(db: AsyncSession, draft: KbDraft) -> None:
    if await active_run(db, draft.id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "agent_writing")


async def touch(db: AsyncSession, draft: KbDraft) -> None:
    draft.last_activity_at = func.now()
    await publish(db, Event(type="kb_draft.updated", user_id=draft.user_id))
    await db.flush()


def add_message(db: AsyncSession, draft: KbDraft, author: str, text: str, *, target: dict | None = None,
                run_id: uuid.UUID | None = None) -> KbDraftMessage:
    message = KbDraftMessage(id=uuid.uuid4(), draft_id=draft.id, author=author, text=text, target=target,
                             run_id=run_id)
    db.add(message)
    return message


async def draft_out(db: AsyncSession, draft: KbDraft) -> DraftOut:
    await db.refresh(draft)
    messages = (
        await db.execute(
            select(KbDraftMessage).where(KbDraftMessage.draft_id == draft.id)
            .order_by(KbDraftMessage.created_at, KbDraftMessage.id)
        )
    ).scalars().all()
    agent = await db.get(Agent, draft.agent_id) if draft.agent_id else None
    space = await db.get(KbSpace, draft.space_id)
    document = await db.get(KbDocument, draft.document_id) if draft.document_id else None
    run = await active_run(db, draft.id)
    state = "idle"
    if run is not None:
        offline = run.status == RunStatus.queued and not registry.is_available(run.agent_id)
        state = "waiting" if offline else "writing"
    return DraftOut(
        id=draft.id, title=draft.title, body_md=draft.body_md,
        segments=[Segment(**s) for s in blocks.segments(draft.turn, draft.body_md)],
        open_marks=blocks.open_count(draft.turn),
        messages=[DraftMessageOut(id=m.id, author=m.author, text=m.text, target=m.target, created_at=m.created_at)
                  for m in messages],
        agent=await agent_out(db, agent) if agent else None,
        space=await kb.space_ref(db, space), folder_id=draft.folder_id,
        folder_path=await kb.folder_path(db, draft.folder_id),
        document=DraftDocument(id=document.id, latest_revision=document.latest_revision) if document else None,
        base_revision=draft.base_revision, state=state, last_activity_at=draft.last_activity_at,
    )


async def my_drafts(db: AsyncSession, user: User) -> list[DraftSummary]:
    drafts = (
        await db.execute(
            select(KbDraft).where(KbDraft.user_id == user.id).order_by(KbDraft.last_activity_at.desc())
        )
    ).scalars().all()
    out = []
    for d in drafts:
        space = await db.get(KbSpace, d.space_id)
        if not await access.can_read(db, user, space):
            continue
        agent = await db.get(Agent, d.agent_id) if d.agent_id else None
        out.append(DraftSummary(
            id=d.id, title=d.title, space=await kb.space_ref(db, space), document_id=d.document_id,
            agent=Named(id=agent.id, name=agent.name) if agent else None, last_activity_at=d.last_activity_at,
        ))
    return out


# -- starting --------------------------------------------------------------------------------------


async def _read_sources(db: AsyncSession, user: User, sources: list[TaskSource | DocSource]) -> list[dict]:
    """What the agent should read first, read now with the person's own access."""
    out = []
    for s in sources:
        try:
            if isinstance(s, TaskSource):
                task, project = await get_task_for(db, user, s.key)
                out.append({"kind": "task", "ref": f"{project.key}-{task.number}", "title": task.title,
                            "text": task.description_md})
            else:
                doc, _ = await access.get_document_for(db, user, s.id)
                out.append({"kind": "doc", "ref": str(doc.id), "title": doc.title, "text": doc.body_md})
        except HTTPException as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "source_not_found") from None
            raise
    if sum(len(s["title"]) + len(s["text"]) for s in out) > SOURCES_CHARS_MAX:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "sources_too_large")
    return out


async def start_draft(db: AsyncSession, user: User, data: DraftIn) -> tuple[KbDraft, bool]:
    """A new draft, or the person's existing draft of the document (created False)."""
    document = None
    if data.document_id is not None:
        document, space = await access.get_document_for(db, user, data.document_id, write=True)
        existing = await db.scalar(
            select(KbDraft).where(KbDraft.user_id == user.id, KbDraft.document_id == document.id)
        )
        if existing is not None:
            return existing, False
    else:
        space = await access.get_space_for(db, user, data.space_id, write=True)
        await kb._check_folder(db, space.id, data.folder_id)
    agent = await check_agent(db, user, space, data.agent_id)
    draft = KbDraft(
        id=uuid.uuid4(), user_id=user.id, agent_id=agent.id, space_id=space.id,
        folder_id=document.folder_id if document else data.folder_id,
        document_id=document.id if document else None,
        base_revision=document.latest_revision if document else None,
        title=document.title if document else "", body_md=document.body_md if document else "",
        brief=data.brief, sources=await _read_sources(db, user, data.sources),
    )
    db.add(draft)
    await db.flush()
    add_message(db, draft, "person", data.brief)
    await touch(db, draft)
    return draft, True


# -- the person's edits and the marks --------------------------------------------------------------


def settle(draft: KbDraft) -> None:
    """Keeps every open change: the draft stays as shown, and the marks clear."""
    draft.turn = None


async def edit(db: AsyncSession, draft: KbDraft, *, title: str | None, body: str | None) -> None:
    await refuse_while_writing(db, draft)
    if body is not None:
        kb.check_body(body)
    settle(draft)
    if title is not None:
        draft.title = title.strip()
    if body is not None:
        draft.body_md = body
    await touch(db, draft)


def _set_status(draft: KbDraft, statuses: dict[str, str]) -> None:
    turn = {**draft.turn, "status": statuses}
    draft.body_md = blocks.compose(turn)
    draft.turn = turn if blocks.open_count(turn) else None


async def set_mark(db: AsyncSession, draft: KbDraft, mark_id: int, to: str) -> None:
    statuses = dict((draft.turn or {}).get("status", {}))
    if statuses.get(str(mark_id)) != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "mark_not_found")
    statuses[str(mark_id)] = to
    _set_status(draft, statuses)
    await touch(db, draft)


async def set_all(db: AsyncSession, draft: KbDraft, to: str) -> None:
    if draft.turn is not None:
        _set_status(draft, {k: (to if v == "open" else v) for k, v in draft.turn["status"].items()})
    await touch(db, draft)


async def change_agent(db: AsyncSession, user: User, draft: KbDraft, agent_id: uuid.UUID) -> None:
    await refuse_while_writing(db, draft)
    agent = await check_agent(db, user, await db.get(KbSpace, draft.space_id), agent_id)
    if agent.id != draft.agent_id:
        draft.agent_id = agent.id
        draft.session_ref = None  # another agent cannot resume this one's session
    await touch(db, draft)


async def discard(db: AsyncSession, draft: KbDraft) -> None:
    from app.kb_drafts.turns import stop_runs_of  # local: turns imports this module

    await stop_runs_of(db, [draft.id])
    await publish(db, Event(type="kb_draft.updated", user_id=draft.user_id))
    await db.delete(draft)
    await db.flush()


async def save(db: AsyncSession, user: User, draft: KbDraft, *, summary: str | None, force: bool) -> KbDocument:
    """The draft becomes a revision of its document (a new one for a new document), credited to the person with the
    agent; then the draft is gone. A newer revision saved meanwhile refuses (409 kb_conflict) unless `force`."""
    await refuse_while_writing(db, draft)
    title = draft.title.strip()
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "title_required")
    agent = await db.get(Agent, draft.agent_id) if draft.agent_id else None
    summary = (summary or "").strip() or (f"Written with {agent.name}" if agent else None)
    if draft.document_id is None:
        doc = await kb.create_document(db, user, await db.get(KbSpace, draft.space_id), draft.folder_id, title,
                                       draft.body_md, agent_id=draft.agent_id, summary=summary)
    else:
        doc = await kb.lock_document(db, draft.document_id)
        base = doc.latest_revision if force else draft.base_revision
        doc = await kb.update_document(db, user, doc, base_revision=base, title=title, body=draft.body_md,
                                       summary=summary, agent_id=draft.agent_id)
    from app.notifications.service import read_by_acting  # local: notifications import the KB

    await read_by_acting(db, user.id, link=f"/kb/drafts/{draft.id}")
    await discard(db, draft)
    return doc
