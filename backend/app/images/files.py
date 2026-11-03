"""Images sent with messages: what is accepted (by the file's bytes, never its name or the browser's word), how
an upload is saved, and the kinds of message an image can go with."""

import uuid
from enum import StrEnum
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGES_PER_MESSAGE = 6
MAX_IMAGES_PER_RUN = 10  # in one run's prompt, or one MCP call
# and at most this many bytes of them in one prompt, steer or MCP call: base64 adds a third, and model APIs cap
# a request's size
MAX_IMAGE_BYTES_PER_RUN = 20 * 1024 * 1024
CHUNK = 1024 * 1024
HEAD = 16  # enough bytes to recognise every accepted type

EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


class MessageKind(StrEnum):
    comment = "comment"  # a plain task comment: its images are for people
    agent_message = "agent_message"  # a message for the task's agent (a comment with to_agent)
    answer = "answer"  # an answer to the agent's question (message_id: the question)
    change_request = "change_request"  # changes asked of a design or plan (message_id: that document)
    first_message = "first_message"  # a chat round's first message, its task's description (message_id: the task)
    nudge = "nudge"  # a chat message that restarts the agent (message_id: the run it starts)


# kinds whose images the agent gets
AGENT_KINDS = frozenset(MessageKind) - {MessageKind.comment}


class ImageRef(BaseModel):
    """An image as a message shows it: /api/attachments/{id} serves it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    size: int


def sniff(head: bytes) -> str | None:
    """The image type the bytes start with: PNG, JPEG, GIF or WebP; None for anything else (SVG, HTML, PDF…)."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


async def save_upload(file: UploadFile, dest: Path, limit: int, too_large: str) -> tuple[int, bytes]:
    """Streams the upload to `dest` (removed again on any failure); returns its size and first bytes. Over `limit`
    it is refused with 413 `too_large`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    head = b""
    try:
        with dest.open("wb") as out:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, too_large)
                if len(head) < HEAD:
                    head += chunk[: HEAD - len(head)]
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return size, head
