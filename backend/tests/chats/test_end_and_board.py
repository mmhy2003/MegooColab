"""Ending a chat, and adding one of its rounds to the board."""

import uuid

from sqlalchemy import select, update

from app.projects.models import BoardColumn
from app.tasks.models import Task
from app.workflow.models import (
    DocKind, DocStatus, Needs, Stage, TaskWorkflow, WorkflowDocument, WorkflowStatus,
)
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round
from tests.chats.test_rounds import _finished


async def _category(db, column_id) -> str:
    return (await db.get(BoardColumn, uuid.UUID(column_id))).category


async def _with_plan(db, task: Task, current_step: int) -> None:
    db.add(WorkflowDocument(task_id=task.id, kind=DocKind.plan, version=1, status=DocStatus.approved, body_md="# p",
                            steps=[{"title": "Test", "detail": "t", "subtask_id": None},
                                   {"title": "Fix", "detail": "f", "subtask_id": None}]))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == task.id).values(current_step=current_step))
    await db.commit()


async def _end(client, chat):
    return await client.post(f"/api/chats/{chat['id']}/end")


async def test_ending_a_working_chat_pauses_its_round(client, db):
    await world(client, db)
    chat = await start(client)
    r = await _end(client, chat)
    assert r.status_code == 200 and r.json()["status"] == "ended" and r.json()["state"] == "ended"
    wf = await db.get(TaskWorkflow, (await _round(db, chat)).id, populate_existing=True)
    assert wf.status == WorkflowStatus.paused
    assert r.json()["rounds"][0]["board"] == "pending"
    # the board question still comes to the people who direct it; nothing more can be typed
    assert r.json()["can_act"] is True and r.json()["intent"] == "closed"


async def test_ending_in_human_review_keeps_tracking(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == rnd.id).values(
        status=WorkflowStatus.waiting_human, needs=Needs.human_code_review, stage=Stage.done,
    ))
    await db.commit()
    from app.agent_runs.models import AgentRun, RunStatus
    await db.execute(update(AgentRun).where(AgentRun.task_id == rnd.id).values(status=RunStatus.completed))
    await db.commit()
    assert (await _end(client, chat)).status_code == 200
    wf = await db.get(TaskWorkflow, rnd.id, populate_existing=True)
    assert (wf.status, wf.needs) == (WorkflowStatus.waiting_human, Needs.human_code_review)


async def _merge_confirmation(db, rnd: Task) -> None:
    """The agent reviewed and merged the round's pull request; MegooColab waits to see the merge."""
    from app.agent_runs.models import AgentRun, RunStatus

    await db.execute(update(AgentRun).where(AgentRun.task_id == rnd.id).values(status=RunStatus.completed))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == rnd.id).values(
        status=WorkflowStatus.waiting_human, needs=Needs.merge_confirmation, stage=Stage.done,
        pr_url="https://git.example/pr/7",
    ))
    await db.commit()


async def test_ending_a_chat_leaves_a_merge_confirmation_alone(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _merge_confirmation(db, rnd)
    assert (await _end(client, chat)).status_code == 200
    wf = await db.get(TaskWorkflow, rnd.id, populate_existing=True)
    assert (wf.status, wf.needs) == (WorkflowStatus.waiting_human, Needs.merge_confirmation)


async def test_ending_a_chat_leaves_an_unconfirmed_merge_alone(client, db):
    """An agent's merge MegooColab couldn't confirm escalated; its pull request is still read, and a merged read
    finishes it: ending the chat doesn't pause it (that would stop it clearing itself)."""
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _merge_confirmation(db, rnd)
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == rnd.id).values(
        needs=Needs.escalation, escalation_reason="merge_not_confirmed"))
    await db.commit()
    assert (await _end(client, chat)).status_code == 200
    wf = await db.get(TaskWorkflow, rnd.id, populate_existing=True)
    assert (wf.status, wf.needs, wf.escalation_reason) == (
        WorkflowStatus.waiting_human, Needs.escalation, "merge_not_confirmed")


async def test_ending_a_chat_still_pauses_another_escalation(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _merge_confirmation(db, rnd)
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == rnd.id).values(
        needs=Needs.escalation, escalation_reason="pr_closed"))
    await db.commit()
    assert (await _end(client, chat)).status_code == 200
    assert (await db.get(TaskWorkflow, rnd.id, populate_existing=True)).status == WorkflowStatus.paused


async def test_chat_state_is_merging(client, db):
    await world(client, db)
    chat = await start(client)
    await _merge_confirmation(db, await _round(db, chat))
    r = await client.get(f"/api/chats/{chat['id']}")
    assert r.status_code == 200 and r.json()["state"] == "merging"
    assert (await client.get("/api/chats/count")).json() == {"waiting": 0}  # nobody waits on it
    needs = (await client.get("/api/dashboard")).json()["needs"]
    assert [n for n in needs if n.get("chat_id") == chat["id"]] == []


async def test_a_round_being_merged_goes_to_the_review_column(client, db):
    await world(client, db)
    chat = await start(client)
    await _merge_confirmation(db, await _round(db, chat))
    await _end(client, chat)
    d = (await client.get(f"/api/chats/{chat['id']}/rounds/1/board")).json()
    assert await _category(db, d["column_id"]) == "review"
    assert "**Outcome:** in code review (https://git.example/pr/7)" in d["description_md"]


async def test_board_defaults_for_a_finished_round(client, db):
    await world(client, db)
    chat = await start(client)
    await _finished(db, await _round(db, chat), "merged_local")
    d = (await client.get(f"/api/chats/{chat['id']}/rounds/1/board")).json()
    assert d["title"] == "Fix the empty email crash"
    assert "**Outcome:** merged" in d["description_md"] and f"/chats/{chat['id']}" in d["description_md"]
    assert await _category(db, d["column_id"]) == "done"


async def test_round_in_human_review_goes_to_the_review_column(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == rnd.id).values(
        status=WorkflowStatus.waiting_human, needs=Needs.human_code_review, pr_url="https://git.example/pr/7",
    ))
    await db.commit()
    await _end(client, chat)
    d = (await client.get(f"/api/chats/{chat['id']}/rounds/1/board")).json()
    assert await _category(db, d["column_id"]) == "review"
    assert "in code review (https://git.example/pr/7)" in d["description_md"]


async def test_adding_to_the_board_shows_it_with_its_steps(client, db):
    await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    await _with_plan(db, rnd, current_step=2)
    await _end(client, chat)  # ended during step 2
    d = (await client.get(f"/api/chats/{chat['id']}/rounds/1/board")).json()
    r = await client.post(f"/api/chats/{chat['id']}/rounds/1/board",
                          json={"add": True, "title": "Fix empty email", "description_md": d["description_md"],
                                "column_id": d["column_id"]})
    assert r.status_code == 200 and r.json()["board"] == "added"
    board = {t["key"]: t for t in (await client.get("/api/projects/PAY/tasks")).json()}
    assert board[chat["rounds"][0]["key"]]["title"] == "Fix empty email"
    subs = sorted((await db.execute(select(Task).where(Task.parent_id == rnd.id))).scalars().all(), key=lambda t: t.number)
    assert [s.title for s in subs] == ["Step 1: Test", "Step 2: Fix"]
    assert [await _category(db, str(s.column_id)) for s in subs] == ["done", "before"]
    plan = (await db.execute(select(WorkflowDocument).where(WorkflowDocument.task_id == rnd.id))).scalar_one()
    assert [s["subtask_id"] for s in plan.steps] == [str(s.id) for s in subs]


async def test_declining_keeps_it_hidden(client, db):
    await world(client, db)
    chat = await start(client)
    await _end(client, chat)
    r = await client.post(f"/api/chats/{chat['id']}/rounds/1/board", json={"add": False})
    assert r.status_code == 200 and r.json()["board"] == "declined"
    assert all(t["key"] != chat["rounds"][0]["key"] for t in (await client.get("/api/projects/PAY/tasks")).json())


async def test_board_decision_is_once(client, db):
    await world(client, db)
    chat = await start(client)
    await _end(client, chat)
    await client.post(f"/api/chats/{chat['id']}/rounds/1/board", json={"add": False})
    r = await client.post(f"/api/chats/{chat['id']}/rounds/1/board", json={"add": True})
    assert r.status_code == 409 and r.json()["detail"] == "already_decided"


async def test_a_running_round_cannot_be_decided(client, db):
    await world(client, db)
    chat = await start(client)
    r = await client.post(f"/api/chats/{chat['id']}/rounds/1/board", json={"add": True})
    assert r.status_code == 409 and r.json()["detail"] == "round_not_finished"
