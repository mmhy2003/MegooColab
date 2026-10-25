import uuid
from typing import Literal

from pydantic import BaseModel

from app.workflow.models import (
    DocKind,
    DocStatus,
    Driver,
    Enforcement,
    FinishingOption,
    Needs,
    Stage,
    WorkflowStatus,
)


class TaskWorkflowOut(BaseModel):
    driver: Driver
    stage: Stage
    status: WorkflowStatus
    needs: Needs | None
    enforcement: Enforcement
    current_step: int | None
    steps_total: int | None
    escalation_reason: str | None


class WorkflowDocumentBrief(BaseModel):
    kind: DocKind
    version: int
    status: DocStatus


class WorkflowStepOut(BaseModel):
    n: int
    title: str
    state: Literal["pending", "running", "in_review", "done"]


class WorkflowOut(TaskWorkflowOut):
    finishing_option: FinishingOption  # the effective option
    branch: str | None
    pr_url: str | None
    documents: list[WorkflowDocumentBrief]
    open_question_id: uuid.UUID | None
    steps: list[WorkflowStepOut]


class EscalationDecisionIn(BaseModel):
    action: Literal["retry", "accept", "pause"]


class ManualWorkflowIn(BaseModel):
    driver: Literal["manual"]
    stage: Stage
