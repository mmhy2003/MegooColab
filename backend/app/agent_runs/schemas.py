import uuid
from datetime import datetime

from pydantic import BaseModel

from app.agent_runs.models import RunPolicy, RunStatus
from app.agents.models import AgentProgram


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
