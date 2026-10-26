"""Knowledge Base writes, links and diffs. Callers check access; these functions only enforce consistency."""

import difflib
import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.audit import service as audit
from app.auth.models import User
from app.core.events import Event, publish
from app.jobs import queue
from app.kb.models import KbDocument, KbFolder, KbLink, KbRevision, KbSpace, SpaceKind
from app.kb.schemas import Author, Named, SpaceRef
from app.projects.models import Project
from app.tasks.models import Task
from app.teams.models import Team

BODY_MAX = 500_000
TITLE_MAX = 200
CONTEXT_LINES = 3
# above this many line pairs in the changed part, the diff is one coarse replacement (difflib is quadratic)
MAX_DIFF_CELLS = 4_000_000

_TASK_LINK = r"\[\[([A-Z][A-Z0-9]{1,9}-\d{1,9})\]\]"
_DOC_LINK = r"\[\[doc:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:\|[^\]\n]{0,200})?\]\]"
LINK_RE = re.compile(f"{_TASK_LINK}|{_DOC_LINK}")


def parse_links(body: str) -> tuple[set[str], set[uuid.UUID]]:
    tasks: set[str] = set()
    docs: set[uuid.UUID] = set()
    for m in LINK_RE.finditer(body):
        if m.group(1):
            tasks.add(m.group(1))
        else:
            docs.add(uuid.UUID(m.group(2)))
    return tasks, docs


def check_body(body: str) -> None:
    if len(body) > BODY_MAX:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_large")


async def _flush_unique(db: AsyncSession, code: str) -> None:
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, code) from None


async def _check_folder(db: AsyncSession, space_id: uuid.UUID, folder_id: uuid.UUID | None) -> None:
    if folder_id is None:
        return
    folder = await db.get(KbFolder, folder_id)
    if folder is None or folder.space_id != space_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "folder_not_found")


# -- naming and paths -----------------------------------------------------------------------------


async def space_name(db: AsyncSession, space: KbSpace) -> str:
    if space.kind == SpaceKind.team:
        team = await db.get(Team, space.team_id)
        return team.name if team else "Team"
    if space.kind == SpaceKind.project:
        project = await db.get(Project, space.project_id)
        return f"{project.key} — {project.name}" if project else "Project"
    return "Organization"


async def space_ref(db: AsyncSession, space: KbSpace) -> SpaceRef:
    return SpaceRef(id=space.id, kind=space.kind, name=await space_name(db, space))


async def folder_path(db: AsyncSession, folder_id: uuid.UUID | None) -> str:
    if folder_id is None:
        return ""
    rows = await db.execute(
        text(
            "WITH RECURSIVE up(id, parent_id, name, depth) AS ("
            " SELECT id, parent_id, name, 0 FROM kb_folders WHERE id = :id"
            " UNION ALL SELECT f.id, f.parent_id, f.name, up.depth + 1 FROM kb_folders f"
            " JOIN up ON f.id = up.parent_id WHERE up.depth < 100)"
            " SELECT name FROM up ORDER BY depth DESC"
        ),
        {"id": folder_id},
    )
    return "/".join(rows.scalars())


async def author(db: AsyncSession, user_id: uuid.UUID | None, agent_id: uuid.UUID | None) -> Author:
    user = await db.get(User, user_id) if user_id else None
    agent = await db.get(Agent, agent_id) if agent_id else None
    return Author(
        user=Named(id=user.id, name=user.name) if user else None,
        agent=Named(id=agent.id, name=agent.name) if agent else None,
    )


# -- side effects of a save ------------------------------------------------------------------------


def space_event(space: KbSpace) -> Event:
    return Event(type="kb.updated", space_id=space.id, team_id=space.team_id, project_id=space.project_id)


async def _changed(db: AsyncSession, doc: KbDocument, *spaces: KbSpace) -> None:
    for space in spaces:
        await publish(db, space_event(space))


async def enqueue_embed(db: AsyncSession, doc_id: uuid.UUID) -> None:
    await queue.enqueue(db, "kb.embed", {"document_id": str(doc_id)}, dedupe_key=f"kb.embed:{doc_id}")


async def refresh_links(db: AsyncSession, doc: KbDocument) -> None:
    """Stores links to tasks and documents that exist (in any space); visibility is applied on read."""
    await db.execute(delete(KbLink).where(KbLink.document_id == doc.id))
    keys, doc_ids = parse_links(doc.body_md)
    task_ids: set[uuid.UUID] = set()
    if keys:
        pairs = [(k.rsplit("-", 1)[0], int(k.rsplit("-", 1)[1])) for k in keys]
        rows = await db.execute(
            select(Task.id, Project.key, Task.number).join(Project, Project.id == Task.project_id)
            .where(Project.key.in_({p for p, _ in pairs}))
            .where(Task.number.in_({n for _, n in pairs}))
        )
        wanted = set(pairs)
        task_ids = {tid for tid, key, number in rows if (key, number) in wanted}
    doc_ids.discard(doc.id)
    if doc_ids:
        doc_ids = set((await db.execute(select(KbDocument.id).where(KbDocument.id.in_(doc_ids)))).scalars())
    db.add_all([KbLink(document_id=doc.id, target_task_id=t) for t in task_ids])
    db.add_all([KbLink(document_id=doc.id, target_document_id=d) for d in doc_ids])


# -- documents ---------------------------------------------------------------------------------------


async def create_document(
    db: AsyncSession,
    user: User,
    space: KbSpace,
    folder_id: uuid.UUID | None,
    title: str,
    body: str,
    *,
    agent_id: uuid.UUID | None = None,
    summary: str | None = None,
) -> KbDocument:
    check_body(body)
    await _check_folder(db, space.id, folder_id)
    doc = KbDocument(
        id=uuid.uuid4(), space_id=space.id, folder_id=folder_id, title=title, body_md=body,
        latest_revision=1, created_by=user.id,
    )
    db.add(doc)
    await _flush_unique(db, "title_taken")
    db.add(KbRevision(document_id=doc.id, revision=1, title=title, body_md=body, summary=summary,
                      author_user_id=user.id, author_agent_id=agent_id))
    await refresh_links(db, doc)
    await enqueue_embed(db, doc.id)
    await _changed(db, doc, space)
    await db.flush()
    return doc


async def lock_document(db: AsyncSession, doc_id: uuid.UUID) -> KbDocument:
    doc = (
        await db.execute(
            select(KbDocument).where(KbDocument.id == doc_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document_not_found")
    return doc


async def update_document(
    db: AsyncSession,
    user: User,
    doc: KbDocument,
    *,
    base_revision: int,
    title: str | None = None,
    body: str | None = None,
    summary: str | None = None,
    agent_id: uuid.UUID | None = None,
) -> KbDocument:
    """Saves a new revision when `base_revision` is still the latest (409 kb_conflict otherwise)."""
    if body is not None:
        check_body(body)
    doc = await lock_document(db, doc.id)
    if doc.latest_revision != base_revision:
        raise HTTPException(status.HTTP_409_CONFLICT, "kb_conflict")
    new_title = title if title is not None else doc.title
    new_body = body if body is not None else doc.body_md
    if new_title == doc.title and new_body == doc.body_md:
        return doc
    body_changed = new_body != doc.body_md
    doc.title = new_title
    doc.body_md = new_body
    doc.latest_revision += 1
    doc.updated_at = func.now()
    await _flush_unique(db, "title_taken")
    db.add(KbRevision(document_id=doc.id, revision=doc.latest_revision, title=new_title, body_md=new_body,
                      summary=summary, author_user_id=user.id, author_agent_id=agent_id))
    if body_changed:
        await refresh_links(db, doc)
    await enqueue_embed(db, doc.id)
    await _changed(db, doc, await db.get(KbSpace, doc.space_id))
    await db.flush()
    await db.refresh(doc)
    return doc


async def move_document(
    db: AsyncSession, user: User, doc: KbDocument, *, space: KbSpace, folder_id: uuid.UUID | None
) -> KbDocument:
    await _check_folder(db, space.id, folder_id)
    doc = await lock_document(db, doc.id)
    old_space = await db.get(KbSpace, doc.space_id)
    doc.space_id = space.id
    doc.folder_id = folder_id
    doc.updated_at = func.now()
    await _flush_unique(db, "title_taken")
    await audit.record(db, "kb.document.moved", actor_id=user.id, target_type="kb_document", target_id=doc.id,
                       data={"from_space": str(old_space.id), "to_space": str(space.id)})
    await _changed(db, doc, old_space, *([space] if space.id != old_space.id else []))
    await db.flush()
    await db.refresh(doc)
    return doc


async def delete_document(db: AsyncSession, user: User, doc: KbDocument) -> None:
    space = await db.get(KbSpace, doc.space_id)
    await audit.record(db, "kb.document.deleted", actor_id=user.id, target_type="kb_document", target_id=doc.id,
                       data={"title": doc.title, "space_id": str(doc.space_id)})
    await db.delete(doc)
    await _changed(db, doc, space)
    await db.flush()


# -- folders -----------------------------------------------------------------------------------------


async def create_folder(
    db: AsyncSession, user: User, space: KbSpace, parent_id: uuid.UUID | None, name: str
) -> KbFolder:
    await _check_folder(db, space.id, parent_id)
    folder = KbFolder(id=uuid.uuid4(), space_id=space.id, parent_id=parent_id, name=name, created_by=user.id)
    db.add(folder)
    await _flush_unique(db, "folder_name_taken")
    await publish(db, space_event(space))
    return folder


async def ensure_folder(
    db: AsyncSession, user: User | None, space: KbSpace, parent_id: uuid.UUID | None, name: str
) -> KbFolder:
    """The named folder under `parent_id`, created if missing (safe against a concurrent create)."""
    await db.execute(
        insert(KbFolder)
        .values(id=uuid.uuid4(), space_id=space.id, parent_id=parent_id, name=name,
                created_by=user.id if user else None)
        .on_conflict_do_nothing(constraint="kb_folders_space_parent_name_key")
    )
    return (
        await db.execute(
            select(KbFolder).where(
                KbFolder.space_id == space.id, KbFolder.parent_id.is_not_distinct_from(parent_id),
                KbFolder.name == name,
            )
        )
    ).scalar_one()


async def rename_folder(db: AsyncSession, user: User, folder: KbFolder, name: str) -> KbFolder:
    folder.name = name
    await _flush_unique(db, "folder_name_taken")
    await publish(db, space_event(await db.get(KbSpace, folder.space_id)))
    return folder


async def _descendant_folder_ids(db: AsyncSession, folder_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.execute(
        text(
            "WITH RECURSIVE down(id) AS (SELECT id FROM kb_folders WHERE id = :id"
            " UNION ALL SELECT f.id FROM kb_folders f JOIN down ON f.parent_id = down.id)"
            " SELECT id FROM down"
        ),
        {"id": folder_id},
    )
    return list(rows.scalars())


async def free_title(db: AsyncSession, space_id: uuid.UUID, folder_id: uuid.UUID | None, title: str) -> str:
    taken = set(
        (
            await db.execute(
                select(KbDocument.title).where(
                    KbDocument.space_id == space_id, KbDocument.folder_id.is_not_distinct_from(folder_id)
                )
            )
        ).scalars()
    )
    if title not in taken:
        return title
    n = 2
    while True:
        suffix = f" ({n})"
        candidate = title[: TITLE_MAX - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1


async def delete_folder(db: AsyncSession, user: User, folder: KbFolder, *, recursive: bool) -> None:
    """Without `recursive`, only an empty folder is deleted. With it, every document inside moves up
    to the folder's parent (renamed "Title (2)" on a clash) and the subfolders are deleted."""
    ids = await _descendant_folder_ids(db, folder.id)
    docs = (
        await db.execute(select(KbDocument).where(KbDocument.folder_id.in_(ids)).with_for_update())
    ).scalars().all()
    if not recursive and (docs or len(ids) > 1):
        raise HTTPException(status.HTTP_409_CONFLICT, "folder_not_empty")
    for doc in docs:
        doc.title = await free_title(db, folder.space_id, folder.parent_id, doc.title)
        doc.folder_id = folder.parent_id
        await db.flush()
    await db.delete(folder)
    await publish(db, space_event(await db.get(KbSpace, folder.space_id)))
    await db.flush()


# -- diff --------------------------------------------------------------------------------------------


def _op(op: str, a_start: int, b_start: int, a_lines: list[str], b_lines: list[str]) -> dict:
    return {"op": op, "a_start": a_start + 1, "b_start": b_start + 1, "a_lines": a_lines, "b_lines": b_lines}


def _opcodes(a: list[str], b: list[str]) -> list[tuple[str, int, int, int, int]]:
    """difflib opcodes for the part between the common head and tail. difflib is quadratic in the worst case
    (many repeated lines), so a changed part larger than MAX_DIFF_CELLS is reported as one replacement."""
    head = 0
    while head < min(len(a), len(b)) and a[head] == b[head]:
        head += 1
    tail = 0
    while tail < min(len(a), len(b)) - head and a[-1 - tail] == b[-1 - tail]:
        tail += 1
    a_mid, b_mid = a[head : len(a) - tail], b[head : len(b) - tail]
    codes: list[tuple[str, int, int, int, int]] = []
    if head:
        codes.append(("equal", 0, head, 0, head))
    if len(a_mid) * len(b_mid) > MAX_DIFF_CELLS:
        codes.append(("replace", head, head + len(a_mid), head, head + len(b_mid)))
    elif a_mid or b_mid:
        for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(None, a_mid, b_mid, autojunk=False).get_opcodes():
            codes.append((tag, a1 + head, a2 + head, b1 + head, b2 + head))
    if tail:
        codes.append(("equal", len(a) - tail, len(a), len(b) - tail, len(b)))
    return codes


def diff(a: str, b: str) -> list[dict]:
    """Line diff of two texts. Unchanged runs longer than 2×CONTEXT_LINES keep CONTEXT_LINES of context next
    to each change and report the rest as {"op": "collapsed", "count": n}."""
    a_lines, b_lines = a.split("\n"), b.split("\n")
    codes = _opcodes(a_lines, b_lines)
    out: list[dict] = []
    for i, (tag, a1, a2, b1, b2) in enumerate(codes):
        if tag != "equal":
            out.append(_op(tag, a1, b1, a_lines[a1:a2], b_lines[b1:b2]))
            continue
        n = a2 - a1
        head = 0 if i == 0 else CONTEXT_LINES
        tail = 0 if i == len(codes) - 1 else CONTEXT_LINES
        if n <= 2 * CONTEXT_LINES or n <= head + tail:
            out.append(_op("equal", a1, b1, a_lines[a1:a2], b_lines[b1:b2]))
            continue
        if head:
            out.append(_op("equal", a1, b1, a_lines[a1 : a1 + head], b_lines[b1 : b1 + head]))
        out.append({"op": "collapsed", "count": n - head - tail})
        if tail:
            out.append(_op("equal", a2 - tail, b2 - tail, a_lines[a2 - tail : a2], b_lines[b2 - tail : b2]))
    return out
