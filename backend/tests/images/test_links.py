"""Images go with the message that sends them: a comment, a message to the agent, an answer, a change request, a
chat's first message or the message that restarts its agent."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app.agent_runs.models import AgentRun, RunStatus
from app.images import links
from app.tasks.models import Attachment
from app.workflow.models import DocKind, TaskWorkflow, WorkflowStatus
from tests.chats.helpers import start, world
from tests.chats.test_chat_workflow import _round, _waiting_for
from tests.chats.test_messages import _run
from tests.factories import login
from tests.workflow.test_engine import _ask, _finish

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def takes(monkeypatch):
    """The agent's runner can be sent images."""
    monkeypatch.setattr(links, "task_takes_images", AsyncMock(return_value=True))


async def _img(client, name="a.png") -> str:
    r = await client.post("/api/images", files={"file": (name, PNG, "image/png")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _task(client, agent_id: str | None = None) -> str:
    body = {"title": "a", "type": "task"} | ({"assignee_agent_id": agent_id} if agent_id else {})
    r = await client.post("/api/projects/PAY/tasks", json=body)
    assert r.status_code == 201, r.text
    return r.json()["key"]


async def _activity(client, key: str) -> list[dict]:
    return (await client.get(f"/api/tasks/{key}/activity")).json()


async def _attachments(client, key: str) -> list[dict]:
    return (await client.get(f"/api/tasks/{key}/attachments")).json()


async def test_comment_links_its_images(client, db):
    await world(client, db)
    key = await _task(client)
    ids = [await _img(client, "one.png"), await _img(client, "two.png")]
    r = await client.post(f"/api/tasks/{key}/comments", json={"body_md": "see these", "image_ids": ids})
    assert r.status_code == 201, r.text
    (item,) = [i for i in await _activity(client, key) if i["type"] == "comment"]
    assert [x["id"] for x in item["images"]] == ids
    assert [x["filename"] for x in item["images"]] == ["one.png", "two.png"]
    listed = await _attachments(client, key)
    assert {a["id"] for a in listed} == set(ids)
    assert {(a["message_kind"], a["message_id"]) for a in listed} == {("comment", item["id"])}


async def test_message_to_agent_kind(client, db, takes):
    w = await world(client, db)
    key = await _task(client, w.agent["id"])
    r = await client.post(f"/api/tasks/{key}/comments",
                          json={"body_md": "look", "to_agent": True, "image_ids": [await _img(client)]})
    assert r.status_code == 201, r.text
    assert (await _attachments(client, key))[0]["message_kind"] == "agent_message"


async def test_agent_message_refused_without_support(client, db):
    w = await world(client, db)  # its agent's runner never said images/1
    key = await _task(client, w.agent["id"])
    r = await client.post(f"/api/tasks/{key}/comments",
                          json={"body_md": "look", "to_agent": True, "image_ids": [await _img(client)]})
    assert r.status_code == 409 and r.json()["detail"] == "images_not_supported"
    assert [i for i in await _activity(client, key) if i["type"] == "comment"] == []


async def test_plain_comment_allowed_without_support(client, db):
    w = await world(client, db)
    key = await _task(client, w.agent["id"])
    r = await client.post(f"/api/tasks/{key}/comments", json={"body_md": "for people", "image_ids": [await _img(client)]})
    assert r.status_code == 201, r.text


async def test_cannot_link_someone_elses_image(client, client_factory, db):
    w = await world(client, db)
    key = await _task(client)
    other = client_factory()
    await login(other, w.other)
    theirs = await _img(other)
    r = await client.post(f"/api/tasks/{key}/comments", json={"body_md": "x", "image_ids": [theirs]})
    assert r.status_code == 422 and r.json()["detail"] == "image_not_found"


async def test_cannot_link_an_image_twice(client, db):
    await world(client, db)
    key = await _task(client)
    img = await _img(client)
    assert (await client.post(f"/api/tasks/{key}/comments", json={"body_md": "x", "image_ids": [img]})).status_code == 201
    r = await client.post(f"/api/tasks/{key}/comments", json={"body_md": "y", "image_ids": [img]})
    assert r.status_code == 422 and r.json()["detail"] == "image_not_found"


async def test_seven_images_refused(client, db):
    await world(client, db)
    key = await _task(client)
    ids = [await _img(client) for _ in range(7)]
    r = await client.post(f"/api/tasks/{key}/comments", json={"body_md": "x", "image_ids": ids})
    assert r.status_code == 422


async def test_deleting_a_comment_keeps_its_images(client, db):
    await world(client, db)
    key = await _task(client)
    img = await _img(client)
    c = (await client.post(f"/api/tasks/{key}/comments", json={"body_md": "x", "image_ids": [img]})).json()
    assert (await client.delete(f"/api/comments/{c['id']}")).status_code == 204
    (att,) = await _attachments(client, key)
    assert att["id"] == img and att["message_kind"] is None and att["message_id"] is None


async def test_deleting_an_attachment_takes_it_out_of_its_message(client, db):
    await world(client, db)
    key = await _task(client)
    keep, drop = await _img(client), await _img(client)
    await client.post(f"/api/tasks/{key}/comments", json={"body_md": "x", "image_ids": [keep, drop]})
    assert (await client.delete(f"/api/attachments/{drop}")).status_code == 204
    (item,) = [i for i in await _activity(client, key) if i["type"] == "comment"]
    assert [x["id"] for x in item["images"]] == [keep]


async def test_answer_and_change_request_carry_images(client, db, takes):
    w = await world(client, db)
    chat = await start(client)
    rnd = await _round(db, chat)
    run = await _run(db, rnd)
    qid = await _ask(rnd.id, run.id)
    await _finish(w.owner.id, run)
    key = chat["rounds"][0]["key"]
    a = await _img(client)
    r = await client.post(f"/api/tasks/{key}/questions/{qid}/answer", json={"text": "this one", "image_ids": [a]})
    assert r.status_code == 200, r.text
    (q,) = [i for i in await _activity(client, key) if i["type"] == "question"]
    assert [x["id"] for x in q["images"]] == [a]

    await _waiting_for(db, rnd, DocKind.design)
    b = await _img(client)
    r = await client.post(f"/api/tasks/{key}/documents/design/1/decision",
                          json={"approve": False, "comment": "like this", "image_ids": [b]})
    assert r.status_code == 200, r.text
    (ev,) = [i for i in await _activity(client, key) if i["kind"] == "document.rejected"]
    assert [x["id"] for x in ev["images"]] == [b]
    assert ev["data"]["document_id"]


async def test_chat_messages_carry_images(client, db, takes):
    await world(client, db)
    first = await _img(client)
    chat = await start(client, image_ids=[first])
    assert [x["id"] for x in chat["rounds"][0]["images"]] == [first]  # its first message's
    rnd = await _round(db, chat)
    told = await _img(client)  # its run is queued: the message tells the agent
    r = await client.post(f"/api/chats/{chat['id']}/messages", json={"body": "and this", "image_ids": [told]})
    assert r.status_code == 201 and r.json()["intent"] == "tell"
    kinds = {a["id"]: a["message_kind"] for a in await _attachments(client, chat["rounds"][0]["key"])}
    assert kinds == {first: "first_message", told: "agent_message"}

    # nothing running, not paused: the message starts the agent again (a nudge with no comment)
    await db.execute(update(AgentRun).where(AgentRun.task_id == rnd.id).values(status=RunStatus.cancelled))
    await db.execute(update(TaskWorkflow).where(TaskWorkflow.task_id == rnd.id).values(
        status=WorkflowStatus.running, needs=None))
    await db.commit()
    nudged = await _img(client)
    r = await client.post(f"/api/chats/{chat['id']}/messages", json={"body": "go on", "image_ids": [nudged]})
    assert r.status_code == 201 and r.json()["intent"] == "restart"
    att = await db.get(Attachment, nudged, populate_existing=True)
    run = await _run(db, rnd)
    assert (att.message_kind, att.message_id) == ("nudge", run.id)


async def test_chat_start_refused_without_support(client, db):
    await world(client, db)
    r = await client.post("/api/chats", json={"project_key": "PAY", "message": "hi", "image_ids": [await _img(client)]})
    assert r.status_code == 409 and r.json()["detail"] == "images_not_supported"
    assert (await client.get("/api/chats")).json() == []


async def test_unsent_images_stay_out_of_attachments(client, db):
    await world(client, db)
    key = await _task(client)
    await _img(client)
    assert await _attachments(client, key) == []
    img = (await db.execute(select(Attachment))).scalar_one()
    assert img.task_id is None
    assert (await client.get(f"/api/attachments/{img.id}")).status_code == 404  # no task's yet: not served
