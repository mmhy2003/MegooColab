"""Agent questions to humans: choices, sandboxed HTML mockups, and answers that resume the asking session
(WF-5, WF-6, WF-6d)."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update

from app.agent_runs.models import AgentRun
from app.audit import service as audit
from app.auth.models import User
from app.core.text import strip_nul
from app.tasks.models import Task
from app.workflow import engine
from app.workflow.models import (
    Mockup,
    Needs,
    QuestionStatus,
    RunRole,
    Stage,
    TaskWorkflow,
    WorkflowQuestion,
    WorkflowStatus,
)

MAX_BODY = 4_000
MAX_CHOICES = 6
MAX_LABEL = 80
MAX_DESCRIPTION = 300
MAX_ANSWER_TEXT = 4_000
MAX_MOCKUP_BYTES = 2 * 1024 * 1024
MAX_MOCKUP_CHOICES = 12
MAX_MOCKUP_TITLE = 200
CHOICE_ID = re.compile(r"[a-z0-9_-]{1,40}")

# Appended to the mockup HTML: elements with data-megoo-choice post that choice to the parent frame.
CHOICE_SCRIPT = (
    "<script>document.addEventListener('click',function(e){var t=e.target&&e.target.closest"
    "?e.target.closest('[data-megoo-choice]'):null;if(t){parent.postMessage({type:'megoo-choice',"
    "choice:t.getAttribute('data-megoo-choice')},'*')}});</script>"
)
_BODY_CLOSE = re.compile(r"</body\s*>", re.IGNORECASE)


def _422(code: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, code)


def _clean_choices(choices: list[dict] | None) -> list[dict]:
    choices = choices or []
    if len(choices) > MAX_CHOICES:
        raise _422("too_many_choices")
    out, seen, recommended = [], set(), 0
    for c in choices:
        if not isinstance(c, dict):
            raise _422("invalid_choice")
        cid = strip_nul(str(c.get("id") or ""))
        label = strip_nul(str(c.get("label") or ""))
        description = strip_nul(str(c.get("description") or ""))
        if not CHOICE_ID.fullmatch(cid) or cid in seen or not label.strip():
            raise _422("invalid_choice")
        if len(label) > MAX_LABEL or len(description) > MAX_DESCRIPTION:
            raise _422("too_large")
        seen.add(cid)
        rec = c.get("recommended", False)
        if not isinstance(rec, bool):
            raise _422("invalid_choice")
        recommended += rec
        out.append({"id": cid, "label": label, "description": description, "recommended": rec})
    if recommended > 1:
        raise _422("invalid_choice")
    return out


def _clean_mockup(mockup: dict[str, Any]) -> dict[str, Any]:
    html = mockup.get("html")
    html = strip_nul(html) if isinstance(html, str) else None
    if not html or not html.strip():
        raise _422("invalid_mockup")
    if len(html.encode("utf-8")) > MAX_MOCKUP_BYTES:
        raise _422("too_large")
    title = strip_nul(str(mockup.get("title") or "")).strip()
    if not title:
        raise _422("invalid_mockup")
    if len(title) > MAX_MOCKUP_TITLE:
        raise _422("too_large")
    ids = mockup.get("choices") or []
    if not isinstance(ids, list):
        raise _422("invalid_mockup")
    if len(ids) > MAX_MOCKUP_CHOICES:
        raise _422("too_many_choices")
    ids = [strip_nul(i) if isinstance(i, str) else i for i in ids]
    if any(not isinstance(i, str) or not CHOICE_ID.fullmatch(i) for i in ids) or len(set(ids)) != len(ids):
        raise _422("invalid_mockup")
    return {"title": title, "html": html, "choices": ids}


async def ask(
    db, run: AgentRun | None, task: Task, body: str, choices: list[dict] | None, mockup: dict[str, Any] | None
) -> WorkflowQuestion:
    """Record a question from an agent run. It replaces (withdraws) any older open question on the task, and
    its mockup is stored as the task's next version. The caller commits."""
    body = strip_nul(body or "")
    if not body.strip():
        raise _422("empty_question")
    if len(body) > MAX_BODY:
        raise _422("too_large")
    clean_choices = _clean_choices(choices)
    clean_mockup = _clean_mockup(mockup) if mockup else None

    await db.execute(
        update(WorkflowQuestion)
        .where(WorkflowQuestion.task_id == task.id, WorkflowQuestion.status == QuestionStatus.open)
        .values(status=QuestionStatus.withdrawn)
    )
    await retire_answers(db, task.id)  # an answer the asking run never saw is moot once it asks again
    mockup_row = None
    if clean_mockup:
        version = (await db.scalar(select(func.max(Mockup.version)).where(Mockup.task_id == task.id)) or 0) + 1
        mockup_row = Mockup(task_id=task.id, version=version, **clean_mockup)
        db.add(mockup_row)
        await db.flush()
    wf = await db.get(TaskWorkflow, task.id)
    stage = Stage(run.stage) if run is not None and run.stage else (wf.stage if wf else Stage.brainstorm)
    q = WorkflowQuestion(
        task_id=task.id, run_id=run.id if run else None, stage=stage, body=body, choices=clean_choices,
        mockup_id=mockup_row.id if mockup_row else None, status=QuestionStatus.open,
    )
    db.add(q)
    await db.flush()
    await engine.record_workflow_event(db, task, None, "question.asked", {"question_id": str(q.id), "has_mockup": bool(mockup_row)})
    return q


async def answer(db, user: User, task: Task, question_id: uuid.UUID, choice: str | None, text: str | None) -> None:
    """A human answers a question (WF-6 roles). The first answer wins (409 already_decided). If the workflow is
    waiting on this question, the asking role's session resumes; otherwise the answer is only recorded."""
    wf = await engine.lock_task(db, task)  # lock order: task, workflow, then the question row
    await engine.require_actor(db, user, task, wf)
    choice = strip_nul(choice) if choice else None
    text = strip_nul(text) if text else None
    if not choice and not text:
        raise _422("empty_answer")
    if text and len(text) > MAX_ANSWER_TEXT:
        raise _422("too_large")
    q = (
        await db.execute(
            select(WorkflowQuestion)
            .where(WorkflowQuestion.id == question_id, WorkflowQuestion.task_id == task.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "question_not_found")
    if q.status != QuestionStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_decided")
    if choice:
        await _choice_label(db, q, choice)  # 422 unknown_choice
    # Only the task's latest open question is "current". ask() withdraws older ones under the same row lock
    # order, so this holds whenever q is open; it is checked explicitly so a delivery never targets a stale one.
    current = await db.scalar(
        select(WorkflowQuestion.id)
        .where(WorkflowQuestion.task_id == task.id, WorkflowQuestion.status == QuestionStatus.open)
        .order_by(WorkflowQuestion.created_at.desc(), WorkflowQuestion.id.desc())
        .limit(1)
    )
    q.status = QuestionStatus.answered
    q.answered_by = user.id
    q.answer_choice = choice
    q.answer_text = text
    q.answered_at = datetime.now(UTC)
    await engine.record_workflow_event(
        db, task, user.id, "question.answered", {"question_id": str(q.id), "choice": choice, "has_text": bool(text)}
    )
    await audit.record(
        db, "workflow.answer", actor_id=user.id, target_type="question", target_id=q.id, data={"task_id": str(task.id)}
    )
    # Delivered now only when the workflow is waiting on this very question. Otherwise (the asking run is still
    # running, or the workflow is paused) the answer waits: undelivered_answer() hands it over when that run
    # ends or the workflow resumes.
    if wf is not None and wf.status == WorkflowStatus.waiting_human and wf.needs == Needs.question and current == q.id:
        await deliver(db, wf, task, q, requested_by=user.id)


async def _choice_label(db, q: WorkflowQuestion, choice: str) -> str:
    by_id = {c["id"]: c for c in q.choices or []}
    if choice in by_id:
        return by_id[choice]["label"]
    mockup = await db.get(Mockup, q.mockup_id) if q.mockup_id else None
    if mockup is not None and choice in (mockup.choices or []):
        return choice  # a mockup choice has no label: its id stands in
    raise _422("unknown_choice")


async def retire_answers(db, task_id: uuid.UUID, *, keep: uuid.UUID | None = None) -> None:
    """Mark every pending answer of the task as superseded. `delivered_at` therefore means "delivered or
    superseded": an answer the agent can no longer be handed (a newer question, a delivery, a stage change)
    is stamped so that no later run end or resume sends it to the wrong role or stage."""
    stmt = update(WorkflowQuestion).where(
        WorkflowQuestion.task_id == task_id,
        WorkflowQuestion.status == QuestionStatus.answered,
        WorkflowQuestion.delivered_at.is_(None),
    )
    if keep is not None:
        stmt = stmt.where(WorkflowQuestion.id != keep)
    await db.execute(stmt.values(delivered_at=datetime.now(UTC)))


async def undelivered_answer(db, task_id: uuid.UUID, run_id: uuid.UUID) -> WorkflowQuestion | None:
    """The latest answer to a question that `run_id` asked and that never reached it (withdrawn ones never
    count)."""
    return (
        await db.execute(
            select(WorkflowQuestion)
            .where(
                WorkflowQuestion.task_id == task_id,
                WorkflowQuestion.run_id == run_id,
                WorkflowQuestion.status == QuestionStatus.answered,
                WorkflowQuestion.delivered_at.is_(None),
            )
            .order_by(WorkflowQuestion.answered_at.desc(), WorkflowQuestion.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def deliver(db, wf: TaskWorkflow, task: Task, q: WorkflowQuestion, *, requested_by: uuid.UUID):
    """Resume the asking role's session with the answer and mark it delivered. The caller holds the locks."""
    label = None
    if q.answer_choice:
        try:
            label = await _choice_label(db, q, q.answer_choice)
        except HTTPException:  # run-end and resume paths must not fail: fall back to the raw id
            label = q.answer_choice
    asked_by = await db.get(AgentRun, q.run_id) if q.run_id else None
    if asked_by is not None and asked_by.workflow_role:
        role, step = RunRole(asked_by.workflow_role), asked_by.step
    else:
        role, step = (RunRole.plan if wf.stage == Stage.plan else RunRole.brainstorm), None
    run = await engine.enqueue(
        db, wf, task, role, step=step, resume_kind="answer",
        payload={"choice_label": label, "text": q.answer_text}, requested_by=requested_by,
    )
    q.delivered_at = datetime.now(UTC)
    await retire_answers(db, q.task_id, keep=q.id)
    return run


def inject_choice_script(html: str) -> str:
    """The choice script goes just before the last </body>, or at the end when there is none."""
    last = None
    for last in _BODY_CLOSE.finditer(html):
        pass
    if last is None:
        return html + CHOICE_SCRIPT
    return html[: last.start()] + CHOICE_SCRIPT + html[last.start():]
