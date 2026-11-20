import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.text import NoNulStr
from app.git.models import GitKind
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
    error: str | None = None  # why the last read failed; never "branch_mismatch"
    limited: str | None = None  # what the token could not read: "checks", "review" or "checks,review"
    host: GitKind | None = None  # the connection's kind; None when untracked
    next_check_at: datetime | None = None


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


class ProjectWaitOut(BaseModel):
    """A question to another project the task waits for, and what the viewer may do about it."""
    question_id: uuid.UUID
    ref: str
    project_key: str
    title: str
    status: str
    can_answer: bool
    can_withdraw: bool


class FinishFailureOut(BaseModel):
    name: str
    kind: Literal["new", "base", "flaky"]


class FinishTestsOut(BaseModel):
    """MC-97: the finish run's failing tests, as it reported them, and how the finish settled."""

    failures: list[FinishFailureOut] = []
    failing_total: int | None = None
    diagnosis: str | None = None
    delivered: bool = False
    settled: Literal["known", "accepted"] | None = None
    accepted_by: str | None = None  # the person's name
    fix_round: int | None = None  # MC-98: the running fix round


class WorkflowOut(TaskWorkflowOut):
    # changes requested on the pull request (piece 3): rounds used, and what asked last
    pr_fix_rounds: int = 0
    pr_fix_trigger: dict | None = None
    # fix rounds on the tests that failed at finish (MC-98): used, and allowed
    finish_fix_rounds: int = 0
    finish_fix_max: int = 2
    finishing_option: FinishingOption  # the effective option
    takes_images: bool = False  # messages to its agent may carry images (app.images.support)
    finishing_forced: bool = False  # human code review forces a pull request
    can_set_manual: bool = False  # WF-11: the viewer may switch this task to the checklist
    branch: str | None
    pr_url: str | None
    pull_request: PullRequestOut | None = None  # GIT-5: as last read from the git host
    # Branch from: where the work started and, for a production fix, its second delivery into the default branch
    back_merge_branch: str | None = None
    back_merge_pr_url: str | None = None
    back_merge_pull_request: PullRequestOut | None = None
    finish_outcome: str | None = None
    finish_tests: FinishTestsOut | None = None  # MC-97: null until a finish reports failing tests
    branch_from: str | None = None
    start_branch: str | None = None
    back_merge_into: str | None = None
    documents: list[WorkflowDocumentBrief]
    open_question_id: uuid.UUID | None
    project_waits: list[ProjectWaitOut] = []  # the other projects' answers it waits for
    steps: list[WorkflowStepOut]
    kb_documents: list[KbFiled] = []  # WF-9: the Knowledge Base copies of approved documents and reviews


class EscalationDecisionIn(BaseModel):
    action: Literal["retry", "accept", "pause", "fix"]


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
    follow_up_count: int = 0  # designs: how many follow-up tasks the version proposes


class DocumentStepOut(BaseModel):
    title: str
    detail: str
    subtask_id: uuid.UUID | None


class FollowUpOut(BaseModel):
    title: str
    type: str
    description_md: str
    created: bool
    task_key: str | None  # None when not created, or created and deleted since


class FollowUpRef(BaseModel):
    key: str
    title: str


class FollowUpPlace(BaseModel):
    column: str
    epic: FollowUpRef | None


class DocumentOut(DocumentInfo):
    body_md: str
    steps: list[DocumentStepOut] | None
    attached_mockup_ids: list[uuid.UUID]
    follow_ups: list[FollowUpOut] = []
    earlier_follow_ups: list[FollowUpRef] = []  # what earlier approved versions created
    creates_in: FollowUpPlace | None = None  # a submitted design: where approving would create the tasks


class FollowUpReviewIn(BaseModel):
    """One row of the reviewed follow-up list sent with a design approval (MC-81); checked by the service."""
    title: NoNulStr = ""
    type: str = "task"
    description_md: NoNulStr = ""
    create: bool


class DocumentDecisionIn(BaseModel):
    image_ids: list[uuid.UUID] = Field(default=[], max_length=6)  # unsent images (POST /api/images) a change request sends
    approve: bool
    comment: NoNulStr | None = None
    follow_ups: list[FollowUpReviewIn] | None = None  # a design approval: the whole reviewed list, in order


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


class DecisionOut(BaseModel):
    id: uuid.UUID
    stage: Stage
    step: int | None
    decision: str
    reason: str
    cost_if_wrong: str
    plan_said: str | None
    author: str  # the agent's name, or "<person>'s connected agent"
    created_at: datetime


class TestRunOut(BaseModel):
    id: uuid.UUID
    stage: Stage
    step: int | None
    command: str
    passed: bool
    total: int | None
    failed: int | None
    skipped: int | None
    failing: list[str]
    on_base: bool = False
    baseline: bool = False
    marks: list[Literal["new", "baseline", "unlisted"]] | None = None  # one per name in `failing`; None: not compared
    known_only: bool = False
    author: str
    created_at: datetime


class RecordsOut(BaseModel):
    decisions: list[DecisionOut]
    test_runs: list[TestRunOut]
    unverified_steps: list[int]  # claimed passing tests with no passing test run recorded
