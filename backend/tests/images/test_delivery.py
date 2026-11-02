"""Images reach the agent: listed in run_start (and run_steer) for a runner with images/1, named in the prompt, and
downloadable by that runner while its run is running."""

import time
import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun
from app.agent_runs.service import dispatch_pending
from app.agents.models import Agent
from app.core.db import SessionLocal
from app.projects.models import Project
from app.tasks.models import Attachment, Task
from tests.agent_runs.test_dispatch import _avail, _setup, _wait_run
from tests.runner.test_runner_ws import URL, _hello, _manager_with_project, _mint

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
IMAGES = ("workflow/1", "branch/1", "model/1", "steer/1", "images/1")
OLD = ("workflow/1", "branch/1", "model/1", "steer/1")


def _img(tc, name="a.png") -> str:
    r = tc.post("/api/images", files={"file": (name, PNG, "image/png")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _tell(tc, task, ids, body="look at these") -> str:
    r = tc.post(f"/api/tasks/{task['key']}/comments", json={"body_md": body, "to_agent": True, "image_ids": ids})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _until(check, what="condition never met"):
    deadline = time.monotonic() + 3
    while not check():
        assert time.monotonic() < deadline, what
        time.sleep(0.02)


async def _caps(token_id):
    async with SessionLocal() as s:
        from app.auth.models import PersonalAccessToken

        return (await s.get(PersonalAccessToken, token_id)).runner_capabilities


def _online(tc, ws, agent, token, capabilities=IMAGES):
    ws.receive_json()  # welcome
    ws.send_json(_hello([_avail(agent)], capabilities=capabilities))
    _until(lambda: sorted(tc.portal.call(_caps, token["id"])) == sorted(capabilities), "hello never saved")


async def _queue_workflow_run(task_key: str, resume: str | None = None) -> str:
    """A workflow run (implement, build step 1) on the task, then dispatched."""
    project_key, number = task_key.split("-")
    async with SessionLocal() as s:
        task = (await s.execute(select(Task).join(Project, Project.id == Task.project_id)
                                .where(Project.key == project_key, Task.number == int(number)))).scalar_one()
        agent = await s.get(Agent, task.assignee_agent_id)
        run = AgentRun(task_id=task.id, agent_id=agent.id, requested_by=agent.owner_id, policy="workspace",
                       status="queued", prompt="Do the step.", workflow_role="implement", stage="build", step=1,
                       resume_session_ref="sess-1" if resume else None, resume_prompt=resume)
        s.add(run)
        await s.commit()
        run_id, owner = run.id, agent.owner_id
    async with SessionLocal() as s:
        await dispatch_pending(s, owner)
        await s.commit()
    return str(run_id)


def _start_frame(ws) -> dict:
    while True:
        msg = ws.receive_json()
        if msg["type"] == "run_start":
            return msg


async def _row(image_id: str) -> Attachment:
    async with SessionLocal() as s:
        return await s.get(Attachment, uuid.UUID(image_id))


async def test_fresh_run_carries_newest_ten(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token)
        first = [_img(tc, f"old-{i}.png") for i in range(6)]
        _tell(tc, task, first, "the old ones")
        second = [_img(tc, f"new-{i}.png") for i in range(6)]
        _tell(tc, task, second, "the new ones")
        tc.portal.call(_queue_workflow_run, task["key"])
        start = _start_frame(ws)
    sent = [i["id"] for i in start["images"]]
    assert sent == first[2:] + second  # the newest ten, oldest first, in prompt order
    assert start["images"][0] == {"id": first[2], "filename": "old-2.png", "content_type": "image/png", "size": len(PNG)}
    assert "## Images" in start["prompt"] and "1. old-2.png" in start["prompt"]
    assert "(2 more images on " in start["prompt"] and "were left out)" in start["prompt"]
    assert "[6 images attached: new-0.png" in start["prompt"]  # named on its message too


async def _worked_on(comment_id: str) -> None:
    from app.tasks.models import Comment

    async with SessionLocal() as s:
        await s.execute(update(Comment).where(Comment.id == uuid.UUID(comment_id)).values(delivery="given_at_start"))
        await s.commit()


async def test_resumed_answer_carries_only_its_images(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token)
        seen = _img(tc)
        first = _tell(tc, task, [seen])
        run = tc.portal.call(_queue_workflow_run, task["key"])
        _start_frame(ws)
        ws.send_json({"type": "run_finished", "run_id": run, "outcome": "completed", "summary": "ok"})
        _wait_run(tc, task, run, "completed")
        tc.portal.call(_worked_on, first)  # the agent had it (a run that did nothing would hand it out again)
        new = _img(tc)
        _tell(tc, task, [new], "and this")
        tc.portal.call(_queue_workflow_run, task["key"], "Carry on.")
        start = _start_frame(ws)
    assert [i["id"] for i in start["images"]] == [new]
    assert "## Images" in start["resume_prompt"]


async def test_plain_comment_images_are_a_note(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token)
        r = tc.post(f"/api/tasks/{task['key']}/comments",
                    json={"body_md": "for Sara", "image_ids": [_img(tc), _img(tc)]})
        assert r.status_code == 201, r.text
        from app.workflow.context import build_prompt

        async def prompt():
            async with SessionLocal() as s:
                t = (await s.execute(select(Task).where(Task.title == "Fix login"))).scalar_one()
                return (await build_prompt(s, t, "implement", step=None))[0]
        text = tc.portal.call(prompt)
    assert "(this comment had 2 images, for the people on the task)" in text


async def test_old_runner_gets_names_not_images(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token)
        img = _img(tc, "seen.png")
        _tell(tc, task, [img])
        run = tc.portal.call(_queue_workflow_run, task["key"])
        _start_frame(ws)
        ws.send_json({"type": "run_finished", "run_id": run, "outcome": "completed", "summary": "ok"})
        _wait_run(tc, task, run, "completed")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token, OLD)  # downgraded; the image was delivered already
        tc.portal.call(_queue_workflow_run, task["key"])
        start = _start_frame(ws)
    assert start.get("images") in (None, [])
    assert "seen.png" in start["prompt"]


async def test_run_with_undelivered_images_waits_for_capability(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token)
        _tell(tc, task, [_img(tc)])  # allowed: this runner said images/1
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token, OLD)
        run = tc.portal.call(_queue_workflow_run, task["key"])
        time.sleep(0.2)
        assert tc.portal.call(_status, run) == "queued"  # not sent: the agent would never see the image
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token)
        start = _start_frame(ws)
    assert start["run_id"] == run and len(start["images"]) == 1


async def _status(run_id: str) -> str:
    async with SessionLocal() as s:
        return (await s.get(AgentRun, uuid.UUID(run_id))).status


async def test_delivery_marks(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token)
        img = _img(tc)
        _tell(tc, task, [img])
        assert tc.portal.call(_row, img).delivered_at is None
        run = tc.portal.call(_queue_workflow_run, task["key"])
        _start_frame(ws)
    row = tc.portal.call(_row, img)
    assert row.delivered_at is not None and str(row.sent_run_id) == run


async def test_runner_download_only_for_its_runs(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    other = _mint(tc, name="other machine")
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token)
        img = _img(tc)
        _tell(tc, task, [img])
        run = tc.portal.call(_queue_workflow_run, task["key"])
        _start_frame(ws)
        got = tc.get(f"/api/runner/images/{img}", headers=token["headers"])
        assert got.status_code == 200 and got.content == PNG
        assert got.headers["content-type"] == "image/png"
        assert tc.get(f"/api/runner/images/{img}", headers=other["headers"]).status_code == 404
        assert tc.get(f"/api/runner/images/{img}").status_code == 401  # the person's session is not a runner
        ws.send_json({"type": "run_finished", "run_id": run, "outcome": "completed", "summary": "ok"})
        _wait_run(tc, task, run, "completed")
        assert tc.get(f"/api/runner/images/{img}", headers=token["headers"]).status_code == 404


async def _undelivered() -> int:
    async with SessionLocal() as s:
        return len((await s.execute(select(Attachment).where(Attachment.delivered_at.is_(None)))).scalars().all())


async def test_steer_carries_images(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token)
        tc.portal.call(_queue_workflow_run, task["key"])
        start = _start_frame(ws)
        img = _img(tc, "now.png")
        cid = _tell(tc, task, [img], "while you work")
        steer = ws.receive_json()
        assert steer["type"] == "run_steer" and steer["message_id"] == cid
        assert [i["id"] for i in steer["images"]] == [img]
        assert "now.png" in steer["text"]
        assert tc.portal.call(_row, img).delivered_at is None
        ws.send_json({"type": "run_steer_result", "run_id": start["run_id"], "message_id": cid, "outcome": "injected"})
        ws.send_json({"type": "heartbeat"})
        _until(lambda: tc.portal.call(_row, img).delivered_at is not None, "never marked delivered")


async def test_steer_with_images_waits_without_capability(db, tc_factory, monkeypatch):
    """Sending is refused for such an agent; should a message with images still reach a steer (its runner was
    swapped meanwhile), it is not steered without them: it waits for a run that can take them."""
    from unittest.mock import AsyncMock

    from app.images import links

    tc = tc_factory(lifespan=True)
    await _manager_with_project(db, tc)
    token, agent, task = _setup(tc)
    with tc.websocket_connect(URL, headers=token["headers"]) as ws:
        _online(tc, ws, agent, token, OLD)
        run = tc.portal.call(_queue_workflow_run, task["key"])
        assert _start_frame(ws)["run_id"] == run
        monkeypatch.setattr(links, "task_takes_images", AsyncMock(return_value=True))
        cid = _tell(tc, task, [_img(tc)], "while you work")
        items = tc.get(f"/api/tasks/{task['key']}/activity").json()
        assert next(i for i in items if i["id"] == cid)["to_agent"]["state"] == "waiting"
        ws.send_json({"type": "run_finished", "run_id": run, "outcome": "completed", "summary": "ok"})
        _wait_run(tc, task, run, "completed")  # the next frame would have been the steer otherwise
