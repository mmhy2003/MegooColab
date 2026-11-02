"""Linking unsent images to the message that sends them, and finding a message's images to show."""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.core.config import get_settings
from app.core.events import Event, publish
from app.images.files import AGENT_KINDS, MAX_IMAGES_PER_MESSAGE, ImageRef, MessageKind
from app.images.support import task_takes_images
from app.tasks.models import Attachment, Task


async def link_images(
    db: AsyncSession, user: User, ids: Sequence[uuid.UUID], task: Task, kind: MessageKind, message_id: uuid.UUID
) -> list[Attachment]:
    """Each id must be one of `user`'s unsent images (422 image_not_found), at most 6 (422 too_many_images); images
    for the agent need an agent that can be sent them (409 images_not_supported). Called in the transaction that
    records the message, so a refusal leaves no message behind."""
    if not ids:
        return []
    if len(ids) > MAX_IMAGES_PER_MESSAGE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "too_many_images")
    if kind in AGENT_KINDS and not await task_takes_images(db, task):
        raise HTTPException(status.HTTP_409_CONFLICT, "images_not_supported")
    rows = {
        a.id: a
        for a in (
            await db.execute(
                select(Attachment)
                .where(Attachment.id.in_(ids), Attachment.uploaded_by == user.id, Attachment.task_id.is_(None))
                .with_for_update()
            )
        ).scalars()
    }
    if len(rows) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "image_not_found")
    root = Path(get_settings().upload_dir)
    linked = []
    for image_id in dict.fromkeys(ids):  # in the order they were added, once each
        att = rows[image_id]
        key = f"{task.id}/{uuid.uuid4().hex}"
        (root / key).parent.mkdir(parents=True, exist_ok=True)
        (root / att.storage_key).replace(root / key)
        att.storage_key, att.task_id, att.message_kind, att.message_id = key, task.id, kind.value, message_id
        linked.append(att)
    await db.flush()
    await publish(db, Event(type="task.updated", project_id=task.project_id, task_id=task.id))
    return linked


async def images_of(db: AsyncSession, message_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[ImageRef]]:
    """The images sent with each message, in the order they were added."""
    ids = set(message_ids)
    if not ids:
        return {}
    out: dict[uuid.UUID, list[ImageRef]] = defaultdict(list)
    rows = await db.execute(
        select(Attachment)
        .where(Attachment.message_id.in_(ids), Attachment.task_id.is_not(None))
        .order_by(Attachment.created_at, Attachment.id)
    )
    for att in rows.scalars():
        out[att.message_id].append(ImageRef.model_validate(att))
    return out


async def unlink_message(db: AsyncSession, message_id: uuid.UUID) -> None:
    """The message is gone: its images stay as files of the task."""
    for att in (await db.execute(select(Attachment).where(Attachment.message_id == message_id))).scalars():
        att.message_kind = att.message_id = None
