"""Design and plan documents: agents submit versions, humans approve or reject them (WF-5, WF-7, WF-8, WF-9)."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select, update

from app.agent_runs.models import AgentRun
from app.audit import service as audit
from app.auth.models import User
from app.core.text import strip_nul
from app.kb import filing
from app.projects.models import Project
from app.tasks.models import Task, TaskType
from app.tasks.schemas import TaskCreate
from app.tasks.service import create_task, first_before_column, task_changed
from app.workflow import engine
from app.workflow.models import (
    DocKind,
    DocStatus,
    Mockup,
    Needs,
    RunRole,
    Stage,
    TaskWorkflow,
    WorkflowDocument,
    WorkflowQuestion,
    WorkflowStatus,
)

MAX_BODY = 200_000
MAX_STEPS = 50
MAX_STEP_TITLE = 200
MAX_STEP_DETAIL = 4_000
MAX_COMMENT = 4_000
MAX_SUBTASK_TITLE = 500

NEEDS_OF = {DocKind.design: Needs.design_approval, DocKind.plan: Needs.plan_approval}
# where a connect-only agent may submit each kind (AGT-32)
SUBMIT_STAGES = {DocKind.design: (Stage.brainstorm, Stage.design), DocKind.plan: (Stage.plan,)}


def _422(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


def _clean_steps(steps) -> list[dict]:
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise _422("invalid_steps")
    out = []
    for step in steps:
        if not isinstance(step, dict):
            raise _422("invalid_steps")
        title, detail = step.get("title"), step.get("detail", "")
        if not isinstance(title, str) or not isinstance(detail, str):
            raise _422("invalid_steps")
        title, detail = strip_nul(title).strip(), strip_nul(detail)
        if not title:
            raise _422("invalid_steps")
        if len(title) > MAX_STEP_TITLE or len(detail) > MAX_STEP_DETAIL:
            raise _422("too_large")
        out.append({"title": title, "detail": detail, "subtask_id": None})
    return out


async def _attached_mockups(db, task_id: uuid.UUID) -> list[str]:
    """WF-6d: the mockups whose declared choice a human picked when answering one of this task's questions."""
    rows = (
        await db.execute(
            select(Mockup.id, Mockup.choices, WorkflowQuestion.answer_choice)
            .join(Mockup, Mockup.id == WorkflowQuestion.mockup_id)
            .where(WorkflowQuestion.task_id == task_id, WorkflowQuestion.answer_choice.is_not(None))
            .order_by(WorkflowQuestion.answered_at, WorkflowQuestion.id)
        )
    ).all()
    ids: list[str] = []
    for mockup_id, choices, chosen in rows:
        if chosen in (choices or []) and str(mockup_id) not in ids:
            ids.append(str(mockup_id))
    return ids


async def submit(
    db, run: AgentRun | None, task: Task, kind: DocKind | str, body_md: str, steps: list[dict] | None = None
) -> WorkflowDocument:
    """Record the next version of the task's design or plan; older submitted versions are superseded. The caller
    commits. The workflow lock is taken first, as in questions.answer."""
    kind = DocKind(kind)
    await engine.lock_task(db, task)
    body_md = strip_nul(body_md or "")
    if not body_md.strip():
        raise _422("empty_document")
    if len(body_md) > MAX_BODY:
        raise _422("too_large")
    if kind == DocKind.plan:
        if steps is None:
            raise _422("steps_required")
        clean = _clean_steps(steps)
    else:
        if steps is not None:
            raise _422("steps_forbidden")
        clean = None
    version = (
        await db.scalar(
            select(func.max(WorkflowDocument.version)).where(
                WorkflowDocument.task_id == task.id, WorkflowDocument.kind == kind
            )
        )
        or 0
    ) + 1
    await db.execute(
        update(WorkflowDocument)
        .where(
            WorkflowDocument.task_id == task.id,
            WorkflowDocument.kind == kind,
            WorkflowDocument.status == DocStatus.submitted,
        )
        .values(status=DocStatus.superseded)
    )
    doc = WorkflowDocument(
        task_id=task.id, kind=kind, version=version, body_md=body_md, steps=clean,
        status=DocStatus.submitted, submitted_run_id=run.id if run else None,
        attached_mockup_ids=await _attached_mockups(db, task.id) if kind == DocKind.design else [],
    )
    db.add(doc)
    await db.flush()
    await engine.record_workflow_event(db, task, None, "document.submitted", {"kind": kind.value, "version": version})
    return doc


async def submit_connect_only(
    db, wf: TaskWorkflow, task: Task, kind: DocKind | str, body_md: str, steps: list[dict] | None = None
) -> WorkflowDocument:
    """AGT-32: a connect-only agent submits its design (Brainstorm or Design) or plan (Plan) while the workflow
    runs with no open question. The stage is checked here, as `submit` does not; the workflow then waits for
    approval, as the runner-driven handler would. The caller holds the workflow lock (engine.lock_connect_only)
    and commits."""
    kind = DocKind(kind)
    await engine.require_connect_only_running(db, wf)
    if wf.stage not in SUBMIT_STAGES[kind]:
        raise HTTPException(status.HTTP_409_CONFLICT, "wrong_stage")
    doc = await submit(db, None, task, kind, body_md, steps)
    if kind == DocKind.design:
        await engine.set_stage(db, wf, task, Stage.design)
    engine.wait_for(wf, NEEDS_OF[kind])
    return doc


async def decide(
    db, user: User, task: Task, kind: DocKind | str, version: int, approve: bool, comment: str | None
) -> None:
    """A human approves or rejects the document (WF-6 roles). The first decision wins (409 already_decided)."""
    kind = DocKind(kind)
    wf = await engine.lock_task(db, task)  # lock order: task, workflow, then the document row
    await engine.require_actor(db, user, task, wf)
    comment = strip_nul(comment).strip() if comment else None
    if comment and len(comment) > MAX_COMMENT:
        raise _422("too_large")
    if not approve and not comment:
        raise _422("comment_required")
    doc = (
        await db.execute(
            select(WorkflowDocument)
            .where(
                WorkflowDocument.task_id == task.id,
                WorkflowDocument.kind == kind,
                WorkflowDocument.version == version,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document_not_found")
    if doc.status != DocStatus.submitted:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_decided")
    if wf is None or wf.status != WorkflowStatus.waiting_human or wf.needs != NEEDS_OF[kind]:
        raise HTTPException(status.HTTP_409_CONFLICT, "not_waiting_for_decision")

    doc.status = DocStatus.approved if approve else DocStatus.rejected
    doc.decided_by = user.id
    doc.decided_at = datetime.now(UTC)
    doc.decision_comment = comment
    data = {"kind": kind.value, "version": version}
    if approve:
        await engine.record_workflow_event(db, task, user.id, "document.approved", data)
    else:
        await engine.record_workflow_event(db, task, user.id, "document.rejected", {**data, "comment": comment})
    await audit.record(
        db, "workflow.approve" if approve else "workflow.reject", actor_id=user.id, target_type="task",
        target_id=task.id, data={**data, "document_id": str(doc.id)},
    )
    if approve:
        await filing.file_document(db, task, kind, doc, user)  # WF-9: never undoes the approval

    if not approve:  # the same session revises it: the brainstorm session for a design, the plan session for a plan
        role = RunRole.brainstorm if kind == DocKind.design else RunRole.plan
        await engine.hand_to_agent(
            db, wf, task, role, resume_kind="rejection", payload={"comment": comment, "kind": kind.value},
            requested_by=user.id,
        )
    elif kind == DocKind.design:
        await engine.set_stage(db, wf, task, Stage.plan)  # the plan session is fresh
        await engine.hand_to_agent(db, wf, task, RunRole.plan, requested_by=user.id)
    else:
        await _start_build(db, user, wf, task, doc)


async def _start_build(db, user: User, wf, task: Task, doc: WorkflowDocument) -> None:
    """WF-7: one subtask per plan step, in the first before-work column, then Build starts at step 1. Runs once:
    the document is no longer submitted for the next decision."""
    project = await db.get(Project, task.project_id)
    column = await first_before_column(db, project)
    steps = []
    for n, step in enumerate(doc.steps or [], start=1):
        subtask = await create_task(
            db, user, project,
            TaskCreate(
                title=f"Step {n}: {step['title']}"[:MAX_SUBTASK_TITLE], type=TaskType.subtask,
                description_md=step.get("detail", ""), column_id=column.id, parent_id=task.id,
            ),
        )
        await task_changed(db, subtask, "task.created")  # live boards show the new subtask
        steps.append({**step, "subtask_id": str(subtask.id)})
    doc.steps = steps  # a new list: edits inside nested dicts are not tracked
    await engine.set_stage(db, wf, task, Stage.build)
    engine.set_step(wf, 1)
    await engine.hand_to_agent(db, wf, task, RunRole.implement, step=1, requested_by=user.id)
