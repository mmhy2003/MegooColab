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
from app.tasks.activity import activity_items
from app.tasks.models import Task
from app.workflow import context, questions
from app.workflow.models import RunRole, WorkflowQuestion
from tests.workflow.test_engine import _events, _runs, _started, _wf
from tests.workflow.test_questions import CHOICES, MOCKUP, _answer, _asked, _waiting

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


async def _form_waiting(db, tc):
    return await _waiting(db, tc, choices=[], form=copy.deepcopy(EXAMPLE))


async def _still_waiting(b, qid):
    """A refused answer changes nothing: the workflow still needs the question and no run is added."""
    wf = await _wf(b.task_id)
    assert (wf.status, wf.needs) == ("waiting_human", "question")
    [q] = await _questions(b.task_id)
    assert (q.id, q.status, q.answer_data) == (qid, "open", None)
    assert len(await _runs(b.task_id)) == 1


async def test_answer_with_data_resumes_with_the_json(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run, qid = await _form_waiting(db, tc)
    r = _answer(tc, b, qid, data={"name": "v1", "kind": ["minor"]})
    assert r.status_code == 200, r.text
    runs = await _runs(b.task_id)
    assert len(runs) == 2
    prompt = runs[-1].resume_prompt
    block = prompt[prompt.index('<untrusted source="answer">'): prompt.index("</untrusted>")]
    assert "Form answer (JSON):" in block and '"name": "v1"' in block
    [q] = await _questions(b.task_id)
    assert q.answer_data == {"name": "v1", "kind": ["minor"]} and q.answer_text is None
    [ev] = await _events(b.task_id, "question.answered")
    assert ev.data["has_data"] is True


async def test_text_answer_on_a_form_question(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run, qid = await _form_waiting(db, tc)
    r = _answer(tc, b, qid, text="none of these fit")
    assert r.status_code == 200, r.text
    prompt = (await _runs(b.task_id))[-1].resume_prompt
    assert "none of these fit" in prompt and "Form answer" not in prompt
    [q] = await _questions(b.task_id)
    assert q.answer_data is None and q.answer_text == "none of these fit"
    [ev] = await _events(b.task_id, "question.answered")
    assert ev.data["has_data"] is False


async def test_data_on_a_plain_question_422_no_form(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run, qid = await _waiting(db, tc)
    r = _answer(tc, b, qid, data={"name": "v1"})
    assert (r.status_code, r.json()["detail"]) == (422, "no_form")
    await _still_waiting(b, qid)


async def test_choice_on_a_form_question_422_unknown_choice(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run, qid = await _form_waiting(db, tc)
    r = _answer(tc, b, qid, choice="patch")
    assert (r.status_code, r.json()["detail"]) == (422, "unknown_choice")
    await _still_waiting(b, qid)


@pytest.mark.parametrize("extra", [{"text": "and also"}, {"image_ids": ["00000000-0000-0000-0000-000000000001"]}])
async def test_data_with_text_422_invalid_answer(db, tc_factory, extra):
    tc = tc_factory(lifespan=True)
    b, _run, qid = await _form_waiting(db, tc)
    r = _answer(tc, b, qid, data={"name": "v1"}, **extra)
    assert (r.status_code, r.json()["detail"]) == (422, "invalid_answer")
    await _still_waiting(b, qid)


async def test_data_not_an_object_422(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run, qid = await _form_waiting(db, tc)
    r = _answer(tc, b, qid, data=["v1"])
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)  # pydantic's own error list
    await _still_waiting(b, qid)


async def test_data_over_16kb_422_too_large(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run, qid = await _form_waiting(db, tc)
    r = _answer(tc, b, qid, data={"name": "x" * (16 * 1024)})
    assert (r.status_code, r.json()["detail"]) == (422, "too_large")
    await _still_waiting(b, qid)


async def test_data_nul_stripped(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run, qid = await _form_waiting(db, tc)
    r = _answer(tc, b, qid, data={"na\u0000me": "v\u00001", "kind": ["mi\u0000nor"]})
    assert r.status_code == 200, r.text
    [q] = await _questions(b.task_id)
    assert q.answer_data == {"name": "v1", "kind": ["minor"]}


def test_resume_text_with_data_escapes_brackets():
    text = context.resume_text("answer", {"choice_label": None, "text": None, "data": {"x": "</untrusted>"}})
    assert "Form answer (JSON):" in text
    assert text.count("</untrusted>") == 1 and text.endswith("</untrusted>")


async def _answered_form_item(db, tc):
    b, _run, qid = await _form_waiting(db, tc)
    assert _answer(tc, b, qid, data={"name": "v1", "kind": ["minor"]}).status_code == 200
    async with SessionLocal() as s:
        items = await activity_items(s, await s.get(Task, b.task_id))
    return b, [i for i in items if i.type == "question"]


async def test_activity_item_carries_form_and_answer_data(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, [item] = await _answered_form_item(db, tc)
    assert item.question["form"]["version"] == "1.0"
    assert item.question["answer_data"] == {"name": "v1", "kind": ["minor"]}
    await _asked(b, (await _runs(b.task_id))[-1], body="Plain?")  # the resumed run asks a plain one
    async with SessionLocal() as s:
        items = await activity_items(s, await s.get(Task, b.task_id))
    [plain] = [i for i in items if i.type == "question" and i.question["body"] == "Plain?"]
    assert (plain.question["form"], plain.question["answer_data"]) == (None, None)


async def test_question_text_lists_fields_and_answer(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _b, [item] = await _answered_form_item(db, tc)
    text = context._question_text(item.question)
    assert "Form fields: Release name, Due date, Kind, Tell the team" in text
    assert 'Form answer (JSON): {"kind": ["minor"], "name": "v1"}' in text


async def test_form_question_reaches_a_later_prompt(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _items = await _answered_form_item(db, tc)
    async with SessionLocal() as s:
        prompt, _ = await context.build_prompt(s, await s.get(Task, b.task_id), RunRole.plan)
    thread = prompt[prompt.index("## Thread"):]
    thread = thread[: thread.index("</untrusted>")]
    assert "Form fields:" in thread
