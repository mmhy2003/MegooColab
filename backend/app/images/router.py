"""Uploading an image for a message before it is sent: it is kept as the uploader's, unsent, until the send that
carries its id links it to its task and message (app.images.links)."""

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.auth.deps import AuthedUser
from app.core.config import get_settings
from app.core.db import DbSession
from app.images.files import EXTENSIONS, MAX_IMAGE_BYTES, save_upload, sniff
from app.tasks.activity import safe_filename
from app.tasks.models import Attachment

router = APIRouter(tags=["images"])

MAX_PENDING = 30  # unsent images one person may hold at once


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size: int


@router.post("/api/images", status_code=status.HTTP_201_CREATED)
async def upload_image(file: UploadFile, user: AuthedUser, db: DbSession) -> ImageOut:
    pending = await db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.uploaded_by == user.id, Attachment.task_id.is_(None))
    )
    if pending >= MAX_PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, "too_many_pending")
    storage_key = f"pending/{user.id}/{uuid.uuid4().hex}"
    dest = Path(get_settings().upload_dir) / storage_key
    size, head = await save_upload(file, dest, MAX_IMAGE_BYTES, "image_too_large")
    kind = sniff(head)
    if kind is None:
        dest.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not_an_image")
    name = safe_filename(file.filename)
    if name == "file":  # nothing usable in the name
        name = f"image.{EXTENSIONS[kind]}"
    att = Attachment(task_id=None, filename=name, content_type=kind, size=size, storage_key=storage_key,
                     uploaded_by=user.id, image=True)
    db.add(att)
    await db.flush()
    return ImageOut.model_validate(att)
