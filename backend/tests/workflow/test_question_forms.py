"""Questions that carry an A2UI form instead of choices (MC-172)."""

import copy
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

import app.a2ui
from app.a2ui.service import CATALOG_ID
from app.core.db import SessionLocal
from app.tasks.models import Task
from app.workflow import questions
from app.workflow.models import WorkflowQuestion
from tests.workflow.test_engine import _events, _started
from tests.workflow.test_questions import CHOICES, MOCKUP, _asked

EXAMPLE = json.loads((Path(app.a2ui.__file__).parent / "example.json").read_text())


async def _ask_form(b, run, form, *, choices=(), mockup=None) -> WorkflowQuestion:
    async with SessionLocal() as s:
        task = await s.get(Task, b.task_id)
        q = await questions.ask(s, run, task, "A few details?", list(choices), mockup, form=form)
        await s.commit()
        return q


async def _questions(task_id) -> list[WorkflowQuestion]:
    async with SessionLocal() as s:
        rows = await s.execute(
            select(WorkflowQuestion).where(WorkflowQuestion.task_id == task_id).order_by(WorkflowQuestion.created_at)
        )
        return list(rows.scalars())


async def test_ask_with_a_form_stores_the_wrapped_message(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    q = await _ask_form(b, run, copy.deepcopy(EXAMPLE))
    [stored] = await _questions(b.task_id)
    assert stored.id == q.id
    assert stored.form["createSurface"]["catalogId"] == CATALOG_ID
    assert stored.form["createSurface"]["components"] == EXAMPLE["components"]
    assert stored.form["createSurface"]["dataModel"] == EXAMPLE["data"]
    assert stored.choices == []
    [ev] = await _events(b.task_id, "question.asked")
    assert ev.data["has_form"] is True


async def test_question_without_a_form_says_so(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    qid = await _asked(b, run)
    [stored] = await _questions(b.task_id)
    assert stored.id == qid and stored.form is None
    [ev] = await _events(b.task_id, "question.asked")
    assert ev.data["has_form"] is False


@pytest.mark.parametrize("extra", [{"choices": CHOICES}, {"mockup": MOCKUP}])
async def test_form_with_choices_422(db, tc_factory, extra):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    with pytest.raises(HTTPException) as e:
        await _ask_form(b, run, copy.deepcopy(EXAMPLE), **extra)
    assert (e.value.status_code, e.value.detail) == (422, "form_with_choices")
    assert await _questions(b.task_id) == []


async def test_form_with_a_mockup_without_choices_is_fine(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    await _ask_form(b, run, copy.deepcopy(EXAMPLE), mockup={**MOCKUP, "choices": []})
    [stored] = await _questions(b.task_id)
    assert stored.form is not None and stored.mockup_id is not None


async def test_invalid_form_stores_nothing(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    older = await _asked(b, run)
    form = copy.deepcopy(EXAMPLE)
    form["components"][0]["children"].append("nowhere")
    with pytest.raises(HTTPException) as e:
        await _ask_form(b, run, form)
    assert e.value.status_code == 422 and e.value.detail.startswith("invalid_form\n")
    [only] = await _questions(b.task_id)
    assert (only.id, only.status) == (older, "open")
