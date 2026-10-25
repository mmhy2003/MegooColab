import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import service as audit
from app.auth.deps import AdminUser, AuthedUser
from app.core.db import DbSession
from app.core.text import NoNulStr
from app.projects.access import get_project_for
from app.projects.models import Project
from app.tasks.models import Task
from app.tasks.service import get_task_for
from app.workflow import documents, engine, methodology, questions
from app.workflow.models import (
    DocKind,
    DocStatus,
    Driver,
    Enforcement,
    FinishingOption,
    MethodologyVersion,
    Mockup,
    QuestionStatus,
    RunRole,
    Stage,
    TaskWorkflow,
    WorkflowDocument,
    WorkflowQuestion,
    WorkflowStatus,
)
from app.workflow.schemas import (
    DocumentDecisionIn,
    DocumentInfo,
    DocumentOut,
    EscalationDecisionIn,
    ManualWorkflowIn,
    WorkflowDocumentBrief,
    WorkflowOut,
    WorkflowStepOut,
)

router = APIRouter(tags=["workflow"])


class MethodologyOut(BaseModel):
    key: str
    stage: Stage
    version: int
    body_md: str
    updated_at: datetime
    updated_by: uuid.UUID | None


class MethodologyVersionInfo(BaseModel):
    version: int
    created_at: datetime
    created_by: uuid.UUID | None


class MethodologyVersionOut(MethodologyVersionInfo):
    key: str
    body_md: str


class MethodologyIn(BaseModel):
    body_md: NoNulStr = Field(min_length=1, max_length=50_000)


def _out(row: MethodologyVersion) -> MethodologyOut:
    return MethodologyOut(
        key=row.key, stage=methodology.STAGE_OF[row.key], version=row.version,
        body_md=row.body_md, updated_at=row.created_at, updated_by=row.created_by,
    )


def _known(key: str) -> None:
    if key not in methodology.STAGE_OF:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "methodology_not_found")


@router.get("/api/methodology")
async def list_methodology(user: AuthedUser, db: DbSession) -> list[MethodologyOut]:
    return [_out(row) for row in await methodology.current_all(db)]


@router.get("/api/methodology/{key}/versions")
async def list_versions(key: str, user: AuthedUser, db: DbSession) -> list[MethodologyVersionInfo]:
    _known(key)
    rows = (
        await db.execute(
            select(MethodologyVersion).where(MethodologyVersion.key == key).order_by(MethodologyVersion.version.desc())
        )
    ).scalars()
    return [MethodologyVersionInfo(version=r.version, created_at=r.created_at, created_by=r.created_by) for r in rows]


@router.get("/api/methodology/{key}/versions/{v}")
async def get_version(key: str, v: int, user: AuthedUser, db: DbSession) -> MethodologyVersionOut:
    _known(key)
    row = (
        await db.execute(
            select(MethodologyVersion).where(MethodologyVersion.key == key, MethodologyVersion.version == v)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "methodology_not_found")
    return MethodologyVersionOut(
        version=row.version, created_at=row.created_at, created_by=row.created_by, key=row.key, body_md=row.body_md
    )


@router.put("/api/methodology/{key}")
async def update_methodology(key: str, body: MethodologyIn, user: AdminUser, db: DbSession) -> MethodologyOut:
    _known(key)
    try:
        prev = await methodology.current(db, key)
        n = prev.version + 1
    except LookupError:
        n = 1
    row = MethodologyVersion(key=key, version=n, body_md=body.body_md, created_by=user.id)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "methodology_conflict")
    await audit.record(
        db, "methodology.updated", actor_id=user.id, target_type="methodology", target_id=row.id,
        data={"key": key, "version": n},
    )
    await db.refresh(row)
    return _out(row)


# ---- task workflows (WF-1..WF-11) ----------------------------------------------------------

_STEP_RUN_STATE = {RunRole.implement: "running", RunRole.step_fix: "running", RunRole.step_review: "in_review"}


async def workflow_out(db, task: Task) -> WorkflowOut:
    wf = (
        await db.execute(
            select(TaskWorkflow).where(TaskWorkflow.task_id == task.id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if wf is None:  # never started: shown as an idle runner workflow at brainstorm
        wf = TaskWorkflow(
            task_id=task.id, driver=Driver.runner, stage=Stage.brainstorm, status=WorkflowStatus.idle,
            enforcement=Enforcement.enforced,
        )
    project = await db.get(Project, task.project_id)
    if project.require_human_code_review:
        finishing = FinishingOption.pull_request
    else:
        finishing = wf.finishing_override or project.finishing_option
    docs = (
        await db.execute(
            select(WorkflowDocument)
            .where(WorkflowDocument.task_id == task.id)
            .order_by(WorkflowDocument.kind, WorkflowDocument.version)
        )
    ).scalars().all()
    plan = next(
        (d for d in reversed(docs) if d.kind == DocKind.plan and d.status == DocStatus.approved), None
    )
    open_question_id = await db.scalar(
        select(WorkflowQuestion.id)
        .where(WorkflowQuestion.task_id == task.id, WorkflowQuestion.status == QuestionStatus.open)
        .order_by(WorkflowQuestion.created_at.desc())
        .limit(1)
    )
    active = await engine.active_run(db, task.id)
    steps = []
    for n, step in enumerate((plan.steps or []) if plan else [], start=1):
        if wf.status == WorkflowStatus.finished or wf.stage in (Stage.review, Stage.done):
            state = "done"
        elif wf.stage != Stage.build or wf.current_step is None or n > wf.current_step:
            state = "pending"
        elif n < wf.current_step:
            state = "done"
        elif active is not None and active.step == n and active.workflow_role:
            state = _STEP_RUN_STATE.get(RunRole(active.workflow_role), "pending")
        else:
            state = "pending"
        steps.append(WorkflowStepOut(n=n, title=step.get("title", ""), state=state))
    return WorkflowOut(
        driver=wf.driver,
        stage=wf.stage,
        status=wf.status,
        needs=wf.needs,
        enforcement=wf.enforcement,
        current_step=wf.current_step,
        steps_total=len(plan.steps or []) if plan else None,
        escalation_reason=wf.escalation_reason,
        finishing_option=finishing,
        branch=wf.branch,
        pr_url=wf.pr_url,
        documents=[WorkflowDocumentBrief(kind=d.kind, version=d.version, status=d.status) for d in docs],
        open_question_id=open_question_id,
        steps=steps,
    )


@router.get("/api/tasks/{key}/workflow")
async def get_workflow(key: str, user: AuthedUser, db: DbSession) -> WorkflowOut:
    task, _ = await get_task_for(db, user, key)
    return await workflow_out(db, task)


@router.post("/api/tasks/{key}/workflow/start")
async def start_workflow(key: str, user: AuthedUser, db: DbSession) -> WorkflowOut:
    task, _ = await get_task_for(db, user, key, write=True)
    await engine.start(db, user, task)
    await engine.dispatch_queued(db)
    return await workflow_out(db, task)


@router.post("/api/tasks/{key}/workflow/pause")
async def pause_workflow(key: str, user: AuthedUser, db: DbSession) -> WorkflowOut:
    task, _ = await get_task_for(db, user, key, write=True)
    await engine.pause(db, user, task)
    return await workflow_out(db, task)


@router.post("/api/tasks/{key}/workflow/resume")
async def resume_workflow(key: str, user: AuthedUser, db: DbSession) -> WorkflowOut:
    task, _ = await get_task_for(db, user, key, write=True)
    await engine.resume(db, user, task)
    await engine.dispatch_queued(db)
    return await workflow_out(db, task)


@router.post("/api/tasks/{key}/workflow/escalation")
async def decide_escalation(key: str, body: EscalationDecisionIn, user: AuthedUser, db: DbSession) -> WorkflowOut:
    task, _ = await get_task_for(db, user, key, write=True)
    await engine.decide_escalation(db, user, task, body.action)
    await engine.dispatch_queued(db)
    return await workflow_out(db, task)


@router.patch("/api/tasks/{key}/workflow")
async def set_manual_workflow(key: str, body: ManualWorkflowIn, user: AuthedUser, db: DbSession) -> WorkflowOut:
    """WF-11: a human's checklist on their own (or an unassigned) task."""
    task, _ = await get_task_for(db, user, key, write=True)
    await engine.set_manual(db, user, task, body.stage)
    return await workflow_out(db, task)


# ---- questions and mockups (WF-6, WF-6d) ------------------------------------------------------------


class AnswerIn(BaseModel):
    choice: NoNulStr | None = None
    text: NoNulStr | None = None


class MockupOut(BaseModel):
    id: uuid.UUID
    version: int
    title: str
    choices: list[str]
    created_at: datetime


MOCKUP_HEADERS = {
    "Content-Security-Policy": (
        "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
        "style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
        "img-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "private, no-store",
}


@router.post("/api/tasks/{key}/questions/{question_id}/answer")
async def answer_question(
    key: str, question_id: uuid.UUID, body: AnswerIn, user: AuthedUser, db: DbSession
) -> WorkflowOut:
    task, _ = await get_task_for(db, user, key, write=True)
    await questions.answer(db, user, task, question_id, body.choice, body.text)
    await engine.dispatch_queued(db)
    return await workflow_out(db, task)


@router.get("/api/tasks/{key}/mockups")
async def list_mockups(key: str, user: AuthedUser, db: DbSession) -> list[MockupOut]:
    task, _ = await get_task_for(db, user, key)
    rows = (await db.execute(select(Mockup).where(Mockup.task_id == task.id).order_by(Mockup.version))).scalars()
    return [
        MockupOut(id=m.id, version=m.version, title=m.title, choices=list(m.choices or []), created_at=m.created_at)
        for m in rows
    ]


@router.get("/api/mockups/{mockup_id}/view")
async def view_mockup(mockup_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    mockup = await db.get(Mockup, mockup_id)
    if mockup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    task = await db.get(Task, mockup.task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    await get_project_for(db, user, str(task.project_id))
    return Response(
        questions.inject_choice_script(mockup.html), media_type="text/html; charset=utf-8", headers=MOCKUP_HEADERS
    )


# ---- design and plan documents (WF-5, WF-7, WF-9) ---------------------------------------------------------


def _doc_info(d: WorkflowDocument) -> DocumentInfo:
    return DocumentInfo(
        kind=d.kind, version=d.version, status=d.status, created_at=d.created_at, decided_by=d.decided_by,
        decision_comment=d.decision_comment,
    )


@router.get("/api/tasks/{key}/documents")
async def list_documents(key: str, user: AuthedUser, db: DbSession) -> list[DocumentInfo]:
    task, _ = await get_task_for(db, user, key)
    rows = (
        await db.execute(
            select(WorkflowDocument)
            .where(WorkflowDocument.task_id == task.id)
            .order_by(WorkflowDocument.kind, WorkflowDocument.version)
        )
    ).scalars()
    return [_doc_info(d) for d in rows]


@router.get("/api/tasks/{key}/documents/{kind}/{version}")
async def get_document(key: str, kind: DocKind, version: int, user: AuthedUser, db: DbSession) -> DocumentOut:
    task, _ = await get_task_for(db, user, key)
    d = (
        await db.execute(
            select(WorkflowDocument).where(
                WorkflowDocument.task_id == task.id, WorkflowDocument.kind == kind, WorkflowDocument.version == version
            )
        )
    ).scalar_one_or_none()
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document_not_found")
    return DocumentOut(
        **_doc_info(d).model_dump(), body_md=d.body_md, steps=d.steps, attached_mockup_ids=d.attached_mockup_ids or []
    )


@router.post("/api/tasks/{key}/documents/{kind}/{version}/decision")
async def decide_document(
    key: str, kind: DocKind, version: int, body: DocumentDecisionIn, user: AuthedUser, db: DbSession
) -> WorkflowOut:
    task, _ = await get_task_for(db, user, key, write=True)
    await documents.decide(db, user, task, kind, version, body.approve, body.comment)
    await engine.dispatch_queued(db)
    return await workflow_out(db, task)
