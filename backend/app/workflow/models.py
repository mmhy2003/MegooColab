import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.db import Base, IdMixin


class Stage(StrEnum):
    brainstorm = "brainstorm"
    design = "design"
    plan = "plan"
    build = "build"
    review = "review"
    done = "done"


class WorkflowStatus(StrEnum):
    idle = "idle"
    running = "running"
    waiting_human = "waiting_human"
    paused = "paused"
    finished = "finished"


class Needs(StrEnum):
    question = "question"
    design_approval = "design_approval"
    plan_approval = "plan_approval"
    escalation = "escalation"
    human_code_review = "human_code_review"


class Driver(StrEnum):
    runner = "runner"
    connect_only = "connect_only"
    manual = "manual"


class Enforcement(StrEnum):
    enforced = "enforced"
    partially_enforced = "partially_enforced"
    unenforced = "unenforced"


class RunRole(StrEnum):
    brainstorm = "brainstorm"
    plan = "plan"
    implement = "implement"
    step_review = "step_review"
    step_fix = "step_fix"
    final_review = "final_review"
    final_fix = "final_fix"
    finish = "finish"


class FinishingOption(StrEnum):
    merge_local = "merge_local"
    pull_request = "pull_request"
    keep_branch = "keep_branch"


class DocKind(StrEnum):
    design = "design"
    plan = "plan"


class DocStatus(StrEnum):
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"


class QuestionStatus(StrEnum):
    open = "open"
    answered = "answered"
    withdrawn = "withdrawn"


class ReviewScope(StrEnum):
    step = "step"
    final = "final"


class Verdict(StrEnum):
    approved = "approved"
    changes_requested = "changes_requested"


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskWorkflow(Base):
    __tablename__ = "task_workflows"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    driver: Mapped[Driver] = mapped_column(String(20), default=Driver.runner)
    stage: Mapped[Stage] = mapped_column(String(20), default=Stage.brainstorm)
    status: Mapped[WorkflowStatus] = mapped_column(String(20), default=WorkflowStatus.idle)
    needs: Mapped[Needs | None] = mapped_column(String(30))
    enforcement: Mapped[Enforcement] = mapped_column(String(30), default=Enforcement.enforced)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    current_step: Mapped[int | None]
    review_round: Mapped[int] = mapped_column(default=0)
    failures: Mapped[int] = mapped_column(default=0)
    nudged: Mapped[bool] = mapped_column(default=False)
    escalation_reason: Mapped[str | None] = mapped_column(String(100))
    finishing_override: Mapped[FinishingOption | None] = mapped_column(String(20))
    branch: Mapped[str | None] = mapped_column(String(300))
    pr_url: Mapped[str | None] = mapped_column(String(1000))
    finish_outcome: Mapped[str | None] = mapped_column(String(100))
    # frozen when the Done stage begins: was human code review required (WF-6a)? None before that
    finish_requires_human_review: Mapped[bool | None]
    # role-or-"implement:<n>" -> ACP session id
    sessions: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # when the current wait for a person began (set by engine.wait_for); None while not waiting
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @validates("status")
    def _leaving_a_wait_clears_waiting_since(self, _key: str, value: WorkflowStatus) -> WorkflowStatus:
        if value != WorkflowStatus.waiting_human:
            self.waiting_since = None
        return value


class WorkflowDocument(IdMixin, Base):
    __tablename__ = "workflow_documents"
    __table_args__ = (UniqueConstraint("task_id", "kind", "version"),)

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[DocKind] = mapped_column(String(20))
    version: Mapped[int]
    body_md: Mapped[str] = mapped_column(Text)
    # [{title, detail, subtask_id}] for plans
    steps: Mapped[list | None] = mapped_column(MutableList.as_mutable(JSONB))
    status: Mapped[DocStatus] = mapped_column(String(20), default=DocStatus.submitted)
    # designs: ids of the mockups whose choice a human picked while answering (WF-6d)
    attached_mockup_ids: Mapped[list] = mapped_column(
        MutableList.as_mutable(JSONB), default=list, server_default=text("'[]'::jsonb")
    )
    # designs: the task's newest mockup when the design was submitted (approving the design approves it)
    mockup_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_mockups.id", ondelete="SET NULL"))
    submitted_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class Mockup(IdMixin, Base):
    __tablename__ = "workflow_mockups"
    __table_args__ = (UniqueConstraint("task_id", "version"),)

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    version: Mapped[int]  # per task, starting at 1
    title: Mapped[str] = mapped_column(String(200))
    html: Mapped[str] = mapped_column(Text)
    choices: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)  # list of ids
    created_at: Mapped[datetime] = _created_at()


class WorkflowQuestion(IdMixin, Base):
    __tablename__ = "workflow_questions"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    stage: Mapped[Stage] = mapped_column(String(20))
    body: Mapped[str] = mapped_column(Text)
    choices: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    mockup_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workflow_mockups.id", ondelete="SET NULL"))
    status: Mapped[QuestionStatus] = mapped_column(String(20), default=QuestionStatus.open)
    answered_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    answer_choice: Mapped[str | None] = mapped_column(String(40))
    answer_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # when the answer was sent to the agent's session; null while an answer waits for the run to end or a resume
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StepReview(IdMixin, Base):
    __tablename__ = "workflow_step_reviews"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"))
    scope: Mapped[ReviewScope] = mapped_column(String(10))
    step: Mapped[int | None]
    round: Mapped[int]
    verdict: Mapped[Verdict] = mapped_column(String(20))
    findings: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    created_at: Mapped[datetime] = _created_at()


class MethodologyVersion(IdMixin, Base):
    __tablename__ = "methodology_versions"
    __table_args__ = (UniqueConstraint("key", "version"),)

    key: Mapped[str] = mapped_column(String(40))
    version: Mapped[int]
    body_md: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created_at()


class WorkflowDecision(IdMixin, Base):
    """A decision an agent made on its own during a run (the plan said X, I did Y), shown on the task."""

    __tablename__ = "workflow_decisions"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    # connect-only: the person whose personal-token agent posted it (no run, no agent row)
    posted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    stage: Mapped[Stage] = mapped_column(String(20))
    step: Mapped[int | None]
    decision: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    cost_if_wrong: Mapped[str] = mapped_column(Text)
    plan_said: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class WorkflowTestRun(IdMixin, Base):
    """A test run an agent reported: the command, its counts and failing test names, never its output (NFR-2)."""

    __tablename__ = "workflow_test_runs"

    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    posted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    stage: Mapped[Stage] = mapped_column(String(20))
    step: Mapped[int | None]
    command: Mapped[str] = mapped_column(String(200))
    passed: Mapped[bool]
    total: Mapped[int | None]
    failed: Mapped[int | None]
    skipped: Mapped[int | None]
    failing: Mapped[list] = mapped_column(MutableList.as_mutable(JSONB), default=list)
    created_at: Mapped[datetime] = _created_at()


Index("ix_workflow_decisions_task_stage_step", WorkflowDecision.task_id, WorkflowDecision.stage, WorkflowDecision.step)
Index("ix_workflow_test_runs_task_stage_step", WorkflowTestRun.task_id, WorkflowTestRun.stage, WorkflowTestRun.step)
