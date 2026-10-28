import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from app.auth.deps import AuthedUser
from app.auth.models import User
from app.core.db import DbSession
from app.kb import access, search, service
from app.kb.models import KbDocument, KbFolder, KbLink, KbRevision, KbSpace, SpaceKind
from app.kb.schemas import (
    DocRef,
    DocumentIn,
    DocumentUpdate,
    FolderIn,
    FolderOut,
    FolderPatch,
    KbDocumentOut,
    KbMoveIn,
    Resolved,
    ResolveIn,
    RevisionOut,
    RevisionSummary,
    SearchOut,
    SpaceOut,
    TreeDoc,
    TreeOut,
)
from app.ratelimit.deps import check_ai
from app.tasks.service import get_task_for

router = APIRouter(tags=["kb"])

_KIND_ORDER = {SpaceKind.org: 0, SpaceKind.team: 1, SpaceKind.project: 2}


async def document_out(db, user: User, doc: KbDocument, space: KbSpace) -> KbDocumentOut:
    latest = (
        await db.execute(
            select(KbRevision).where(KbRevision.document_id == doc.id, KbRevision.revision == doc.latest_revision)
        )
    ).scalar_one_or_none()
    return KbDocumentOut(
        id=doc.id,
        space=await service.space_ref(db, space),
        folder_id=doc.folder_id,
        path=await service.folder_path(db, doc.folder_id),
        title=doc.title,
        body_md=doc.body_md,
        latest_revision=doc.latest_revision,
        created_by=doc.created_by,
        updated_at=doc.updated_at,
        updated_by=await service.author(db, latest.author_user_id if latest else None,
                                        latest.author_agent_id if latest else None),
        can_write=await access.can_write(db, user, space),
        can_delete=await access.can_delete_document(db, user, doc, space),
    )


async def _doc_refs(db, user: User, doc_ids_stmt) -> list[DocRef]:
    readable = await access.readable_space_ids(db, user)
    docs = (
        await db.execute(
            select(KbDocument).where(KbDocument.id.in_(doc_ids_stmt), KbDocument.space_id.in_(readable))
            .order_by(KbDocument.title)
        )
    ).scalars()
    return [DocRef(id=d.id, title=d.title, space=await service.space_ref(db, await db.get(KbSpace, d.space_id)))
            for d in docs]


async def _folder_for(db, user: User, folder_id: uuid.UUID) -> KbFolder:
    folder = await db.get(KbFolder, folder_id)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "folder_not_found")
    space = await db.get(KbSpace, folder.space_id)
    if not await access.can_read(db, user, space):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "folder_not_found")
    await access.get_space_for(db, user, space.id, write=True)
    return folder


# -- spaces and folders ------------------------------------------------------------------------------


@router.get("/api/kb/spaces")
async def list_spaces(user: AuthedUser, db: DbSession) -> list[SpaceOut]:
    await access.ensure_spaces(db)
    readable = await access.readable_space_ids(db, user)
    spaces = (await db.execute(select(KbSpace).where(KbSpace.id.in_(readable)))).scalars().all()
    out = [
        SpaceOut(id=s.id, kind=s.kind, name=await service.space_name(db, s), team_id=s.team_id,
                 project_id=s.project_id, can_write=await access.can_write(db, user, s))
        for s in spaces
    ]
    return sorted(out, key=lambda s: (_KIND_ORDER[s.kind], s.name.lower()))


@router.get("/api/kb/spaces/{space_id}/tree")
async def space_tree(space_id: uuid.UUID, user: AuthedUser, db: DbSession) -> TreeOut:
    space = await access.get_space_for(db, user, space_id)
    folders = (await db.execute(select(KbFolder).where(KbFolder.space_id == space.id).order_by(KbFolder.name))).scalars()
    docs = (
        await db.execute(select(KbDocument).where(KbDocument.space_id == space.id).order_by(KbDocument.title))
    ).scalars()
    return TreeOut(
        folders=[FolderOut(id=f.id, parent_id=f.parent_id, name=f.name) for f in folders],
        documents=[TreeDoc(id=d.id, folder_id=d.folder_id, title=d.title, latest_revision=d.latest_revision,
                           updated_at=d.updated_at) for d in docs],
    )


@router.post("/api/kb/spaces/{space_id}/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(space_id: uuid.UUID, body: FolderIn, user: AuthedUser, db: DbSession) -> FolderOut:
    space = await access.get_space_for(db, user, space_id, write=True)
    f = await service.create_folder(db, user, space, body.parent_id, body.name)
    return FolderOut(id=f.id, parent_id=f.parent_id, name=f.name)


@router.patch("/api/kb/folders/{folder_id}")
async def rename_folder(folder_id: uuid.UUID, body: FolderPatch, user: AuthedUser, db: DbSession) -> FolderOut:
    f = await service.rename_folder(db, user, await _folder_for(db, user, folder_id), body.name)
    return FolderOut(id=f.id, parent_id=f.parent_id, name=f.name)


@router.delete("/api/kb/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(folder_id: uuid.UUID, user: AuthedUser, db: DbSession, recursive: bool = False) -> Response:
    await service.delete_folder(db, user, await _folder_for(db, user, folder_id), recursive=recursive)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- documents ---------------------------------------------------------------------------------------


@router.post("/api/kb/spaces/{space_id}/documents", status_code=status.HTTP_201_CREATED)
async def create_document(space_id: uuid.UUID, body: DocumentIn, user: AuthedUser, db: DbSession) -> KbDocumentOut:
    space = await access.get_space_for(db, user, space_id, write=True)
    doc = await service.create_document(db, user, space, body.folder_id, body.title, body.body_md, summary=body.summary)
    return await document_out(db, user, doc, space)


@router.get("/api/kb/documents/{doc_id}")
async def get_document(doc_id: uuid.UUID, user: AuthedUser, db: DbSession) -> KbDocumentOut:
    doc, space = await access.get_document_for(db, user, doc_id)
    return await document_out(db, user, doc, space)


@router.put("/api/kb/documents/{doc_id}")
async def update_document(doc_id: uuid.UUID, body: DocumentUpdate, user: AuthedUser, db: DbSession) -> KbDocumentOut:
    doc, space = await access.get_document_for(db, user, doc_id, write=True)
    doc = await service.update_document(
        db, user, doc, base_revision=body.base_revision, title=body.title, body=body.body_md, summary=body.summary
    )
    return await document_out(db, user, doc, space)


@router.post("/api/kb/documents/{doc_id}/move")
async def move_document(doc_id: uuid.UUID, body: KbMoveIn, user: AuthedUser, db: DbSession) -> KbDocumentOut:
    doc, _ = await access.get_document_for(db, user, doc_id, write=True)
    target = await access.get_space_for(db, user, body.space_id, write=True)
    doc = await service.move_document(db, user, doc, space=target, folder_id=body.folder_id)
    return await document_out(db, user, doc, target)


@router.delete("/api/kb/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    doc, space = await access.get_document_for(db, user, doc_id, write=True)
    if not await access.can_delete_document(db, user, doc, space):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    await service.delete_document(db, user, doc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- revisions ---------------------------------------------------------------------------------------


async def _revision(db, doc: KbDocument, n: int) -> KbRevision:
    rev = (
        await db.execute(select(KbRevision).where(KbRevision.document_id == doc.id, KbRevision.revision == n))
    ).scalar_one_or_none()
    if rev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "revision_not_found")
    return rev


@router.get("/api/kb/documents/{doc_id}/revisions")
async def list_revisions(doc_id: uuid.UUID, user: AuthedUser, db: DbSession) -> list[RevisionSummary]:
    doc, _ = await access.get_document_for(db, user, doc_id)
    revs = (
        await db.execute(
            select(KbRevision).where(KbRevision.document_id == doc.id).order_by(KbRevision.revision.desc())
        )
    ).scalars()
    return [
        RevisionSummary(revision=r.revision, title=r.title, summary=r.summary, created_at=r.created_at,
                        author=await service.author(db, r.author_user_id, r.author_agent_id))
        for r in revs
    ]


@router.get("/api/kb/documents/{doc_id}/revisions/{n}")
async def get_revision(doc_id: uuid.UUID, n: int, user: AuthedUser, db: DbSession) -> RevisionOut:
    doc, _ = await access.get_document_for(db, user, doc_id)
    r = await _revision(db, doc, n)
    return RevisionOut(revision=r.revision, title=r.title, summary=r.summary, created_at=r.created_at,
                       body_md=r.body_md, author=await service.author(db, r.author_user_id, r.author_agent_id))


@router.get("/api/kb/documents/{doc_id}/revisions/{a}/diff/{b}")
async def diff_revisions(doc_id: uuid.UUID, a: int, b: int, user: AuthedUser, db: DbSession) -> list[dict]:
    doc, _ = await access.get_document_for(db, user, doc_id)
    ra, rb = await _revision(db, doc, a), await _revision(db, doc, b)
    # CPU-bound: off the event loop, so one large diff cannot stall every other request
    return await asyncio.to_thread(service.diff, ra.body_md, rb.body_md)


# -- links -------------------------------------------------------------------------------------------


@router.get("/api/kb/documents/{doc_id}/backlinks")
async def backlinks(doc_id: uuid.UUID, user: AuthedUser, db: DbSession) -> list[DocRef]:
    doc, _ = await access.get_document_for(db, user, doc_id)
    return await _doc_refs(db, user, select(KbLink.document_id).where(KbLink.target_document_id == doc.id))


@router.get("/api/tasks/{key}/kb-references")
async def task_references(key: str, user: AuthedUser, db: DbSession) -> list[DocRef]:
    task, _ = await get_task_for(db, user, key)
    return await _doc_refs(db, user, select(KbLink.document_id).where(KbLink.target_task_id == task.id))


@router.post("/api/kb/resolve")
async def resolve(body: ResolveIn, user: AuthedUser, db: DbSession) -> dict[str, Resolved]:
    readable = await access.readable_space_ids(db, user)
    found = {
        d.id: d.title
        for d in (
            await db.execute(
                select(KbDocument).where(KbDocument.id.in_(body.doc_ids), KbDocument.space_id.in_(readable))
            )
        ).scalars()
    }
    return {str(i): Resolved(title=found.get(i), readable=i in found) for i in body.doc_ids}


@router.get("/api/kb/search")
async def search_kb(
    request: Request,
    user: AuthedUser,
    db: DbSession,
    q: str = Query(min_length=1, max_length=500),
    space: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=50),
) -> SearchOut:
    await check_ai(request)  # semantic search embeds the query
    return SearchOut(**await search.search(db, user, q, space_ids={space} if space else None, limit=limit))
