import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.core.text import NoNulStr

BODY_MAX = 4000
CONTEXT_MAX = 8000
TITLE_MAX = 200
ANSWER_MAX = 20000


class AskIn(BaseModel):
    project_key: str = Field(min_length=1, max_length=10)
    body: NoNulStr = Field(min_length=1, max_length=BODY_MAX)
    title: NoNulStr | None = Field(default=None, max_length=TITLE_MAX)
    context: NoNulStr = Field(default="", max_length=CONTEXT_MAX)
    task_key: str | None = Field(default=None, max_length=30)


class SuggestIn(BaseModel):
    project_key: str = Field(min_length=1, max_length=10)
    body: NoNulStr = Field(min_length=1, max_length=BODY_MAX)


class Suggestion(BaseModel):
    kind: str
    id: uuid.UUID
    title: str
    snippet: str
    link: str


class Target(BaseModel):
    key: str
    name: str


class Ref(BaseModel):
    id: uuid.UUID
    name: str


class Who(BaseModel):
    user: Ref | None
    agent: Ref | None


class TaskRef(BaseModel):
    key: str
    title: str


class Citation(BaseModel):
    path: NoNulStr = Field(min_length=1, max_length=500)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)


class Draft(BaseModel):
    answer_md: str
    citations: list[Citation]
    agent: Ref | None


class QuestionOut(BaseModel):
    id: uuid.UUID
    ref: str
    target: Target
    title: str
    body: str
    context: str
    status: str
    answer_md: str | None
    citations: list[Citation]
    answer_source: str | None
    answered_by: Who
    answering: Who | None  # routed: the agent at work; draft: the agent whose owner approves
    draft: Draft | None
    reject_reason: str | None
    redacted: bool
    attempts: int
    from_task: TaskRef | None
    asked_by: Who
    kb_document_id: uuid.UUID | None
    kb_document_readable: bool  # the Q&A document lives in the target project's space
    created_at: datetime
    answered_at: datetime | None
    can_answer: bool
    can_approve: bool
    can_withdraw: bool


class AskQuestionOut(BaseModel):
    question: QuestionOut
    suggestions: list[Suggestion]


class AnswerIn(BaseModel):
    answer_md: NoNulStr = Field(min_length=1, max_length=ANSWER_MAX)
    citations: list[Citation] = Field(default=[], max_length=50)


class ApproveIn(BaseModel):
    answer_md: NoNulStr | None = Field(default=None, min_length=1, max_length=ANSWER_MAX)


class RejectIn(BaseModel):
    reason: NoNulStr = Field(min_length=1, max_length=500)
