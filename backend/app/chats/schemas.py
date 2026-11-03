import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.auth.schemas import UserOut
from app.chats.models import ChatStatus
from app.core.text import NoNulStr
from app.images.files import ImageRef

MAX_MESSAGE = 8_000

ChatState = Literal[
    "talking", "question", "design_approval", "plan_approval", "building", "in_review", "human_code_review",
    "escalation", "offline", "finished", "ended",
]
# what a message typed in the chat does now (for the viewer); "closed": it can't be sent
Intent = Literal["answer", "changes", "tell", "restart", "new_round", "closed"]


class ChatIn(BaseModel):
    project_key: NoNulStr = Field(min_length=1, max_length=20)
    agent_id: uuid.UUID | None = None  # None: any free agent the person may use on the project
    message: NoNulStr = Field(min_length=1, max_length=MAX_MESSAGE)
    image_ids: list[uuid.UUID] = Field(default=[], max_length=6)  # unsent images (POST /api/images) it sends


class MessageIn(BaseModel):
    body: NoNulStr = Field(min_length=1, max_length=MAX_MESSAGE)
    image_ids: list[uuid.UUID] = Field(default=[], max_length=6)  # unsent images (POST /api/images) it sends


class MessageOut(BaseModel):
    intent: Intent
    round_key: str


class BoardDefaults(BaseModel):
    title: str
    description_md: str
    column_id: uuid.UUID


class BoardIn(BaseModel):
    add: bool
    title: NoNulStr | None = Field(default=None, min_length=1, max_length=500)
    description_md: NoNulStr | None = None
    column_id: uuid.UUID | None = None


class ChatAgentOut(BaseModel):
    id: uuid.UUID
    name: str
    program: str


class RoundOut(BaseModel):
    n: int
    key: str
    title: str
    stage: str | None
    status: str | None
    needs: str | None
    current_step: int | None
    steps_total: int | None
    finish_outcome: str | None
    pr_url: str | None
    branch: str | None
    branch_from: str | None
    # "pending": finished, or the chat ended, with nothing decided yet; None: the round is still going
    board: Literal["pending", "added", "declined"] | None
    images: list[ImageRef] = []  # sent with its first message


class ChatOut(BaseModel):
    id: uuid.UUID
    project_key: str
    title: str
    status: ChatStatus
    agent: ChatAgentOut | None
    started_by: UserOut | None
    created_at: datetime
    last_activity_at: datetime
    state: ChatState
    intent: Intent = "closed"
    can_act: bool
    rounds: list[RoundOut]
    takes_images: bool = False  # its messages may carry images (the latest round's agent can be sent them)
