import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.core.text import NoNulStr
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


class HumanReviewIn(BaseModel):
    approved: Literal[True]


class FinishingIn(BaseModel):
    option: FinishingOption | None


class ManualWorkflowIn(BaseModel):
    driver: Literal["manual"]
    stage: Stage


class DocumentInfo(BaseModel):
    kind: DocKind
    version: int
    status: DocStatus
    created_at: datetime
    decided_by: uuid.UUID | None
    decision_comment: str | None


class DocumentStepOut(BaseModel):
    title: str
    detail: str
    subtask_id: uuid.UUID | None


class DocumentOut(DocumentInfo):
    body_md: str
    steps: list[DocumentStepOut] | None
    attached_mockup_ids: list[uuid.UUID]


class DocumentDecisionIn(BaseModel):
    approve: bool
    comment: NoNulStr | None = None
