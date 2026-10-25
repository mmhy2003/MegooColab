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
        rec = bool(c.get("recommended", False))
        recommended += rec
        out.append({"id": cid, "label": label, "description": description, "recommended": rec})
    if recommended > 1:
        raise _422("invalid_choice")
    return out


def _clean_mockup(mockup: dict[str, Any]) -> dict[str, Any]:
    html = mockup.get("html")
    if not isinstance(html, str) or not html.strip():
        raise _422("invalid_mockup")
    html = strip_nul(html)
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
    await engine._event(db, task, None, "question.asked", {"question_id": str(q.id), "has_mockup": bool(mockup_row)})
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
    label = None
    if choice:
        by_id = {c["id"]: c for c in q.choices or []}
        mockup = await db.get(Mockup, q.mockup_id) if q.mockup_id else None
        if choice in by_id:
            label = by_id[choice]["label"]
        elif mockup is not None and choice in (mockup.choices or []):
            label = choice  # a mockup choice has no label: its id stands in
        else:
            raise _422("unknown_choice")
    q.status = QuestionStatus.answered
    q.answered_by = user.id
    q.answer_choice = choice
    q.answer_text = text
    q.answered_at = datetime.now(UTC)
    await engine._event(
        db, task, user.id, "question.answered", {"question_id": str(q.id), "choice": choice, "has_text": bool(text)}
    )
    await audit.record(
        db, "workflow.answer", actor_id=user.id, target_type="question", target_id=q.id, data={"task_id": str(task.id)}
    )
    if wf is None or wf.status != WorkflowStatus.waiting_human or wf.needs != Needs.question:
        return
    asked_by = await db.get(AgentRun, q.run_id) if q.run_id else None
    if asked_by is not None and asked_by.workflow_role:
        role, step = RunRole(asked_by.workflow_role), asked_by.step
    else:
        role, step = (RunRole.plan if wf.stage == Stage.plan else RunRole.brainstorm), None
    await engine.enqueue(
        db, wf, task, role, step=step, resume_kind="answer",
        payload={"choice_label": label, "text": text}, requested_by=user.id,
    )


def inject_choice_script(html: str) -> str:
    """The choice script goes just before the last </body>, or at the end when there is none."""
    last = None
    for last in _BODY_CLOSE.finditer(html):
        pass
    if last is None:
        return html + CHOICE_SCRIPT
    return html[: last.start()] + CHOICE_SCRIPT + html[last.start():]
