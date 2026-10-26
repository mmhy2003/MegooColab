import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, tuple_

from app.auth.deps import AuthedUser
from app.auth.models import Role, User
from app.auth.schemas import UserOut
from app.core.config import get_settings
from app.core.db import DbSession
from app.core.events import Event, publish
from app.core.text import NoNulStr, strip_nul
from app.projects.access import get_project_for
from app.tasks.models import Attachment, Comment, Task, TaskEvent
from app.tasks.service import get_task_for
from app.workflow.models import Mockup, WorkflowQuestion

router = APIRouter(tags=["activity"])

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
CHUNK = 1024 * 1024


class CommentIn(BaseModel):
    body_md: NoNulStr = Field(min_length=1, max_length=50_000)


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    author_user_id: uuid.UUID | None
    body_md: str
    created_at: datetime
    edited_at: datetime | None


class ActivityItem(BaseModel):
    type: Literal["comment", "event", "question"]
    id: uuid.UUID
    at: datetime
    actor: UserOut | None
    body_md: str | None = None
    edited_at: datetime | None = None
    kind: str | None = None
    data: dict | None = None
    # type "question": {id, body, choices, status, mockup: {id, version, title}|None, answered_by,
    # answer_choice, answer_text}
    question: dict | None = None


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    filename: str
    content_type: str
    size: int
    uploaded_by: uuid.UUID | None
    created_at: datetime


def safe_filename(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1].strip().strip(".")
    base = re.sub(r"[\x00-\x1f]", "", base)
    return base[:255] or "file"


async def _task_for_project_object(db, user: User, task_id: uuid.UUID, write: bool = False) -> Task:
    """Loads a task by id and checks the caller can access its project (404 otherwise)."""
    task = await db.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    await get_project_for(db, user, str(task.project_id), write=write)
    return task


async def _changed(db, task: Task, kind: str) -> None:
    await publish(db, Event(type=kind, project_id=task.project_id, task_id=task.id))


# ---- activity ---------------------------------------------------------------


async def activity_items(
    db, task: Task, limit: int = 50, before: datetime | None = None, before_id: uuid.UUID | None = None
) -> list[ActivityItem]:
    c_stmt = select(Comment).where(Comment.task_id == task.id)
    # the question item shows its own asked/answered state, so those events are not repeated
    e_stmt = select(TaskEvent).where(TaskEvent.task_id == task.id, TaskEvent.kind.not_like("question.%"))
    q_stmt = select(WorkflowQuestion).where(WorkflowQuestion.task_id == task.id)
    if before and before_id:
        # (at, id) cursor: items written in one transaction share a timestamp
        cursor = (before, before_id)
        c_stmt = c_stmt.where(tuple_(Comment.created_at, Comment.id) < cursor)
        e_stmt = e_stmt.where(tuple_(TaskEvent.created_at, TaskEvent.id) < cursor)
        q_stmt = q_stmt.where(tuple_(WorkflowQuestion.created_at, WorkflowQuestion.id) < cursor)
    elif before:
        c_stmt = c_stmt.where(Comment.created_at < before)
        e_stmt = e_stmt.where(TaskEvent.created_at < before)
        q_stmt = q_stmt.where(WorkflowQuestion.created_at < before)
    comments = (await db.execute(c_stmt.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit))).scalars().all()
    events = (await db.execute(e_stmt.order_by(TaskEvent.created_at.desc(), TaskEvent.id.desc()).limit(limit))).scalars().all()
    questions = (
        await db.execute(
            q_stmt.order_by(WorkflowQuestion.created_at.desc(), WorkflowQuestion.id.desc()).limit(limit)
        )
    ).scalars().all()
    mockup_ids = {q.mockup_id for q in questions if q.mockup_id}
    mockups = {
        m.id: {"id": str(m.id), "version": m.version, "title": m.title}
        for m in (await db.execute(select(Mockup).where(Mockup.id.in_(mockup_ids)))).scalars()
    } if mockup_ids else {}
    answerers = {
        u.id: {"id": str(u.id), "name": u.name}
        for u in (
            await db.execute(select(User).where(User.id.in_({q.answered_by for q in questions if q.answered_by})))
        ).scalars()
    }
    actor_ids = {c.author_user_id for c in comments} | {e.actor_user_id for e in events}
    actor_ids.discard(None)
    actors = {
        u.id: UserOut.model_validate(u)
        for u in (await db.execute(select(User).where(User.id.in_(actor_ids)))).scalars()
    }
    items = [
        ActivityItem(type="comment", id=c.id, at=c.created_at, actor=actors.get(c.author_user_id),
                     body_md=c.body_md, edited_at=c.edited_at)
        for c in comments
    ] + [
        ActivityItem(type="event", id=e.id, at=e.created_at, actor=actors.get(e.actor_user_id),
                     kind=e.kind, data=e.data)
        for e in events
    ] + [
        ActivityItem(
            type="question", id=q.id, at=q.created_at, actor=None,
            question={
                "id": str(q.id), "body": q.body, "choices": list(q.choices or []), "status": str(q.status),
                "mockup": mockups.get(q.mockup_id), "answered_by": answerers.get(q.answered_by),
                "answer_choice": q.answer_choice, "answer_text": q.answer_text,
            },
        )
        for q in questions
    ]
    items.sort(key=lambda i: (i.at, i.id), reverse=True)
    return list(reversed(items[:limit]))


@router.get("/api/tasks/{key}/activity")
async def task_activity(
    key: str,
    user: AuthedUser,
    db: DbSession,
    before: datetime | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActivityItem]:
    """Newest `limit` items, oldest first. Page back with the first item's (at, id) as the cursor."""
    task, _ = await get_task_for(db, user, key)
    return await activity_items(db, task, limit, before, before_id)


# ---- comments ---------------------------------------------------------------


async def create_comment(db, user: User, key: str, body_md: str) -> Comment:
    body_md = strip_nul(body_md)  # also reached by MCP, which bypasses CommentIn
    task, _ = await get_task_for(db, user, key, write=True)
    comment = Comment(task_id=task.id, author_user_id=user.id, body_md=body_md)
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    await _changed(db, task, "comment.created")
    # local: memory imports the task modules
    from app.memory.sources import queue_extract

    await queue_extract(db, "comment", comment.id)
    return comment


@router.post("/api/tasks/{key}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(key: str, body: CommentIn, user: AuthedUser, db: DbSession) -> CommentOut:
    return CommentOut.model_validate(await create_comment(db, user, key, body.body_md))


async def _own_comment(db, user: User, comment_id: uuid.UUID, allow_admin: bool) -> tuple[Comment, Task]:
    comment = await db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    task = await _task_for_project_object(db, user, comment.task_id)
    if comment.author_user_id != user.id and not (allow_admin and user.role == Role.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    return comment, task


@router.patch("/api/comments/{comment_id}")
async def edit_comment(comment_id: uuid.UUID, body: CommentIn, user: AuthedUser, db: DbSession) -> CommentOut:
    comment, task = await _own_comment(db, user, comment_id, allow_admin=False)
    comment.body_md = body.body_md
    comment.edited_at = datetime.now(UTC)
    await _changed(db, task, "comment.updated")
    # local: memory imports the task modules
    from app.memory.sources import queue_extract

    await queue_extract(db, "comment", comment.id)
    return CommentOut.model_validate(comment)


@router.delete("/api/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(comment_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    comment, task = await _own_comment(db, user, comment_id, allow_admin=True)
    await db.delete(comment)
    await _changed(db, task, "comment.deleted")
    # local: memory imports the task modules
    from app.memory.sources import queue_forget

    await queue_forget(db)


# ---- attachments ------------------------------------------------------------


def _upload_root() -> Path:
    return Path(get_settings().upload_dir)


@router.get("/api/tasks/{key}/attachments")
async def list_attachments(key: str, user: AuthedUser, db: DbSession) -> list[AttachmentOut]:
    task, _ = await get_task_for(db, user, key)
    rows = await db.execute(
        select(Attachment).where(Attachment.task_id == task.id).order_by(Attachment.created_at)
    )
    return [AttachmentOut.model_validate(a) for a in rows.scalars()]


@router.post("/api/tasks/{key}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(key: str, file: UploadFile, user: AuthedUser, db: DbSession) -> AttachmentOut:
    task, _ = await get_task_for(db, user, key, write=True)
    storage_key = f"{task.id}/{uuid.uuid4().hex}"
    dest = _upload_root() / storage_key
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > MAX_ATTACHMENT_BYTES:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "attachment_too_large")
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    att = Attachment(
        task_id=task.id,
        filename=safe_filename(file.filename),
        content_type=(file.content_type or "application/octet-stream")[:200],
        size=size,
        storage_key=storage_key,
        uploaded_by=user.id,
    )
    db.add(att)
    await db.flush()
    await db.refresh(att)
    await _changed(db, task, "task.updated")
    return AttachmentOut.model_validate(att)


async def _attachment(db, user: User, attachment_id: uuid.UUID, write: bool = False) -> tuple[Attachment, Task]:
    att = await db.get(Attachment, attachment_id)
    if att is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    task = await _task_for_project_object(db, user, att.task_id, write=write)
    return att, task


@router.get("/api/attachments/{attachment_id}")
async def download_attachment(attachment_id: uuid.UUID, user: AuthedUser, db: DbSession) -> FileResponse:
    att, _ = await _attachment(db, user, attachment_id)
    path = _upload_root() / att.storage_key
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file_missing")
    return FileResponse(path, media_type=att.content_type, filename=att.filename,
                        content_disposition_type="attachment")


@router.delete("/api/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(attachment_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    att, task = await _attachment(db, user, attachment_id, write=True)
    (_upload_root() / att.storage_key).unlink(missing_ok=True)
    await db.delete(att)
    await _changed(db, task, "task.updated")
