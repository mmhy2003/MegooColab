"""A runner downloads the images of the runs it runs (capability images/1), with its own token."""

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.agent_runs.models import AgentRun, RunStatus
from app.agents.models import Agent
from app.auth.deps import bearer_token
from app.auth.models import TokenScope
from app.auth.tokens import resolve_bearer
from app.core.config import get_settings
from app.core.db import DbSession
from app.tasks.models import Attachment, Task

router = APIRouter(tags=["runner"])


@router.get("/api/runner/images/{image_id}")
async def runner_image(image_id: uuid.UUID, request: Request, db: DbSession) -> FileResponse:
    """The image, when a run of one of this runner's agents is running on its task (or, for a chat, on a round of
    that chat: messages to the agent are kept across rounds). 404 otherwise, as for an image that doesn't exist."""
    raw = bearer_token(request)
    resolved = await resolve_bearer(db, raw, scope=TokenScope.runner) if raw else None
    if resolved is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")
    token = resolved[1]
    att = await db.get(Attachment, image_id)
    task = await db.get(Task, att.task_id) if att is not None and att.task_id is not None else None
    if task is None or not att.image:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    tasks = select(Task.id).where(Task.chat_id == task.chat_id) if task.chat_id else select(Task.id).where(Task.id == task.id)
    running = await db.scalar(
        select(AgentRun.id)
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(AgentRun.task_id.in_(tasks), AgentRun.status == RunStatus.running, Agent.runner_token_id == token.id)
        .limit(1)
    )
    path = Path(get_settings().upload_dir) / att.storage_key
    if running is None or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    return FileResponse(path, media_type=att.content_type, headers={"X-Content-Type-Options": "nosniff"})
