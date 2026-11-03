import time

from sqlalchemy import select

from app.agents.models import Agent
from app.auth.models import PersonalAccessToken
from app.core.db import SessionLocal
from app.images.support import agent_takes_images, task_takes_images
from app.tasks.models import Task
from app.workflow.models import TaskWorkflow
from tests.runner.test_runner_ws import (
    URL,
    _agent,
    _hello,
    _manager_with_project,
    _mint,
    _next_welcome,
)

IMAGES = ("workflow/1", "branch/1", "model/1", "images/1")


async def _caps(token_id: str) -> list[str]:
    async with SessionLocal() as s:
        return (await s.get(PersonalAccessToken, token_id)).runner_capabilities


def _until(check, what: str) -> None:
    deadline = time.monotonic() + 3
    while not check():
        assert time.monotonic() < deadline, what
        time.sleep(0.02)


async def _agent_row(agent_id: str) -> Agent:
    async with SessionLocal() as s:
        return await s.get(Agent, agent_id)


async def _takes(agent_id: str) -> bool:
    async with SessionLocal() as s:
        return await agent_takes_images(s, await s.get(Agent, agent_id))


async def test_hello_remembers_capabilities(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token = _mint(tc)
    a = _agent(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _next_welcome(ws)
        ws.send_json(_hello([{"agent_id": a["id"], "available": True, "problems": []}], IMAGES))
        _until(lambda: "images/1" in tc.portal.call(_caps, token["id"]), "images/1 never saved")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _next_welcome(ws)
        ws.send_json(_hello([{"agent_id": a["id"], "available": True, "problems": []}]))  # downgraded: no images/1
        _until(lambda: "images/1" not in tc.portal.call(_caps, token["id"]), "images/1 never dropped")


async def test_offline_agent_uses_last_known(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token = _mint(tc)
    a = _agent(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _next_welcome(ws)
        ws.send_json(_hello([{"agent_id": a["id"], "available": True, "problems": []}], IMAGES))
        _until(lambda: "images/1" in tc.portal.call(_caps, token["id"]), "images/1 never saved")
        assert tc.portal.call(_takes, a["id"])
    assert tc.portal.call(_takes, a["id"])  # offline now: the last hello still counts


async def test_never_connected_agent_takes_none(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    _mint(tc)
    a = _agent(tc)
    assert tc.portal.call(_takes, a["id"]) is False
    async with SessionLocal() as s:
        assert await agent_takes_images(s, None) is False


async def test_connect_only_task_takes_images(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    r = tc.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    assert r.status_code == 201, r.text
    task = (await db.execute(select(Task))).scalar_one()
    assert await task_takes_images(db, task) is False  # nobody to send them to
    db.add(TaskWorkflow(task_id=task.id, stage="brainstorm", status="running", driver="connect_only"))
    await db.commit()
    assert await task_takes_images(db, task) is True
    assert tc.get("/api/tasks/PAY-1/workflow").json()["takes_images"] is True


async def test_chat_says_so(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token = _mint(tc)
    a = _agent(tc)
    tc.put(f"/api/agents/{a['id']}/bindings", json={"bindings": [{"project_ref": "PAY", "local_path": "/p"}]})
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _next_welcome(ws)
        ws.send_json(_hello([{"agent_id": a["id"], "available": True, "problems": []}], IMAGES))
        _until(lambda: "images/1" in tc.portal.call(_caps, token["id"]), "images/1 never saved")
    r = tc.post("/api/chats", json={"project_key": "PAY", "agent_id": a["id"], "message": "hi"})
    assert r.status_code == 201, r.text
    assert tc.get(f"/api/chats/{r.json()['id']}").json()["takes_images"] is True
    assert tc.get("/api/tasks/PAY-1/workflow").json()["takes_images"] is True
