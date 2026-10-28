"""Deleting a project, or a task, leaves nothing behind: rows, upload folders, what Memory learned."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.auth.models import Role
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.jobs.models import Job
from app.tasks.models import Task
from app.tasks.uploads import remove_after_commit
from tests.factories import login, make_project, make_user
from tests.projects.test_project_status import close


@pytest.fixture
def upload_root() -> Path:
    return Path(get_settings().upload_dir)


async def _attach(client, key: str) -> None:
    r = await client.post(f"/api/tasks/{key}/attachments", files={"file": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 201, r.text


async def test_admin_deletes_a_closed_project_with_everything(client, db, upload_root):
    await make_project(client, db, "PAY")
    task = (await client.post("/api/projects/PAY/tasks", json={"title": "A"})).json()
    await _attach(client, task["key"])
    folder = upload_root / task["id"]
    assert folder.is_dir()
    await close(db, "PAY", "archived")
    await login(client, await make_user(db, role=Role.admin))
    assert (await client.delete("/api/projects/PAY")).status_code == 204
    assert not folder.exists()
    assert await db.scalar(select(func.count()).select_from(Task)) == 0
    assert await db.scalar(select(func.count()).select_from(Job).where(Job.kind == "mem.forget")) == 1


async def test_managers_cannot_delete_projects(client, db):
    await make_project(client, db, "PAY")  # signed in as its manager
    assert (await client.delete("/api/projects/PAY")).status_code == 403


async def test_deleting_a_task_removes_its_and_its_subtasks_folders(client, db, upload_root):
    await make_project(client, db, "PAY")
    parent = (await client.post("/api/projects/PAY/tasks", json={"title": "Parent"})).json()
    child = (await client.post("/api/projects/PAY/tasks",
                               json={"title": "Step", "type": "subtask", "parent_id": parent["id"]})).json()
    await _attach(client, parent["key"])
    await _attach(client, child["key"])
    assert (await client.delete(f"/api/tasks/{parent['key']}")).status_code == 204
    assert not (upload_root / parent["id"]).exists()
    assert not (upload_root / child["id"]).exists()


async def test_upload_folders_survive_a_rolled_back_delete(upload_root):
    task_id = uuid.uuid4()
    folder = upload_root / str(task_id)
    folder.mkdir(parents=True)
    (folder / "f").write_text("x")
    async with SessionLocal() as s:
        await s.execute(text("SELECT 1"))  # inside a transaction, as every delete is
        remove_after_commit(s, [task_id])
        await s.rollback()
        await s.commit()  # a later commit in the same session must not remove it either
    assert folder.is_dir()
    async with SessionLocal() as s:
        remove_after_commit(s, [task_id])
        await s.commit()
    assert not folder.exists()


async def test_deleting_a_project_stops_agents_answering_its_questions(client, db, monkeypatch):
    from types import SimpleNamespace

    from app.a2a.models import Question
    from app.agent_runs.models import AgentRun
    from app.agents.models import Agent
    from app.runner.registry import registry

    _p, manager, _t = await make_project(client, db, "PAY")
    project_id = uuid.UUID(_p["id"])
    agent = Agent(owner_id=manager.id, name="Answerer", program="claude_code")
    db.add(agent)
    await db.flush()
    q = Question(target_project_id=project_id, number=1, title="Q", body="?", status="routed")
    db.add(q)
    await db.flush()
    run = AgentRun(question_id=q.id, agent_id=agent.id, requested_by=manager.id, policy="read_only", prompt="p",
                   status="running")
    db.add(run)
    await db.commit()
    sent = []

    async def send(msg):
        sent.append(msg)

    conn = SimpleNamespace(run_ids={run.id}, send=send)
    monkeypatch.setattr(registry, "conn_for_user", lambda user_id: conn if user_id == manager.id else None)
    await close(db, "PAY", "archived")  # archive first, delete later: answering carried on meanwhile
    await login(client, await make_user(db, role=Role.admin))
    assert (await client.delete("/api/projects/PAY")).status_code == 204
    assert [m.run_id for m in sent] == [run.id]  # the runner is told to stop, so no agent keeps working unobserved
