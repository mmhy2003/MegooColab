import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.agent_runs.models import RunPolicy, RunStatus
from app.agents.models import AgentProgram
from app.workflow.models import Stage

RunKind = Literal["task", "chat", "question", "cron", "draft"]


class RunAgentOut(BaseModel):
    id: uuid.UUID
    name: str
    program: AgentProgram


class RunOut(BaseModel):
    id: uuid.UUID
    task_key: str
    agent: RunAgentOut
    policy: RunPolicy
    status: RunStatus
    workflow_role: str | None = None
    step: int | None = None
    reason: str | None
    summary: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunningItem(BaseModel):
    """A run at work now, as the Dashboard's Running now and the Agents pages list it."""

    run_id: uuid.UUID
    agent_name: str
    started_at: datetime | None
    kind: RunKind
    title: str | None = None  # the task's title, the chat's title or the cron's name
    task_key: str | None
    question_key: str | None = None  # answering runs: <KEY>-Q<n>
    stage: Stage | None
    step: int | None
    steps_total: int | None
    review_round: int | None
    question_from: str | None  # answering runs: the asking task's project key
    link: str | None  # None: a Knowledge Base draft, or a run in a project the viewer cannot open
    chat_id: uuid.UUID | None = None
