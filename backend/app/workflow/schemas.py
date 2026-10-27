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


class PullRequestOut(BaseModel):
    """GIT-5: the pull request a task's Finish run opened, as last read from the git host."""

    url: str
    state: str
    checks: str
    review: str
    tracked: bool


class TaskWorkflowOut(BaseModel):
    driver: Driver
    stage: Stage
    status: WorkflowStatus
    needs: Needs | None
    enforcement: Enforcement
    current_step: int | None
    steps_total: int | None
    escalation_reason: str | None
    can_act: bool = False  # for the viewing user (WF-6)


class WorkflowDocumentBrief(BaseModel):
    kind: DocKind
    version: int
    status: DocStatus


class WorkflowStepOut(BaseModel):
    n: int
    title: str
    state: Literal["pending", "running", "in_review", "done"]


class KbFiled(BaseModel):
    kind: str
    document_id: uuid.UUID


class WorkflowOut(TaskWorkflowOut):
    finishing_option: FinishingOption  # the effective option
    finishing_forced: bool = False  # human code review forces a pull request
    can_set_manual: bool = False  # WF-11: the viewer may switch this task to the checklist
    branch: str | None
    pr_url: str | None
    pull_request: PullRequestOut | None = None  # GIT-5: as last read from the git host
    documents: list[WorkflowDocumentBrief]
    open_question_id: uuid.UUID | None
    steps: list[WorkflowStepOut]
    kb_documents: list[KbFiled] = []  # WF-9: the Knowledge Base copies of approved documents and reviews


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
    mockup_id: uuid.UUID | None = None  # designs: the mockup it was submitted with (approved with it)


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


class Finding(BaseModel):
    severity: Literal["critical", "important", "minor"]
    file: str | None
    line: int | None
    summary: str


class ReviewOut(BaseModel):
    scope: Literal["step", "final"]
    step: int | None
    round: int
    verdict: Literal["approved", "changes_requested"]
    findings: list[Finding]
