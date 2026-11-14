"""The task's Attachments reach its agent through list_attachments / get_attachment: a short-lived signed link the
agent downloads with, and the picture of an image. Images sent with messages stay with their runs."""

import base64
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from app.core.db import SessionLocal
from app.tasks import file_links
from app.tasks.models import Attachment
from tests.mcp.test_task_images import _call
from tests.mcp.test_workflow_tools import _run_token, _task, _tool
from tests.workflow.test_engine import _started

PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 40
NOTES = b"brand colours: #0aa5c0\n"


def _attach(tc, key: str, name: str, data: bytes, content_type: str) -> dict:
    r = tc.post(f"/api/tasks/{key}/attachments", files={"file": (name, data, content_type)})
    assert r.status_code == 201, r.text
    return r.json()


async def _message_image(task_id: uuid.UUID) -> uuid.UUID:
    """An image sent with a message to the agent: it belongs to that run, not to the task's Attachments."""
    async with SessionLocal() as s:
        a = Attachment(task_id=task_id, filename="shot.png", content_type="image/png", size=len(PNG),
                       storage_key=f"{task_id}/msg", image=True, message_kind="agent_message",
                       message_id=uuid.uuid4())
        s.add(a)
        await s.commit()
        return a.id


async def _with_files(db, tc):
    """A started task with a logo and a notes file in its Attachments, one message image, and the run's token."""
    b, run = await _started(db, tc)
    logo = _attach(tc, b.key, "voice-changer-logo.png", PNG, "image/png")
    notes = _attach(tc, b.key, "notes.txt", NOTES, "text/plain")
    await _message_image(b.task_id)
    return b, logo, notes, await _run_token(run)


def _path_and_query(link: str) -> str:
    parts = urlsplit(link)
    return f"{parts.path}?{parts.query}"


async def test_list_attachments_lists_the_tasks_files_not_message_images(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, logo, notes, token = await _with_files(db, tc)
    err, out = _tool(tc, token, "list_attachments", key=b.key)
    assert not err, out
    assert [f["filename"] for f in out] == ["voice-changer-logo.png", "notes.txt"]
    first = out[0]
    assert first["id"] == logo["id"] and first["content_type"] == "image/png" and first["size"] == len(PNG)
    assert first["image"] is True and out[1]["image"] is False
    assert first["uploaded_by"] and first["created_at"]


async def test_get_task_lists_the_tasks_files(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, logo, notes, token = await _with_files(db, tc)
    err, task = _tool(tc, token, "get_task", key=b.key)
    assert not err
    assert [f["id"] for f in task["attachments"]] == [logo["id"], notes["id"]]


async def test_attachment_tools_refuse_another_task(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, logo, notes, token = await _with_files(db, tc)
    other = _task(tc, b.agent, title="Other")
    theirs = _attach(tc, other["key"], "secret.txt", b"no", "text/plain")
    err, text = _tool(tc, token, "list_attachments", key=other["key"])
    assert err and "wrong_task" in text
    err, text = _tool(tc, token, "get_attachment", key=other["key"], attachment_id=theirs["id"])
    assert err and "wrong_task" in text
    # its own key with another task's file is not found either
    err, text = _tool(tc, token, "get_attachment", key=b.key, attachment_id=theirs["id"])
    assert err and "not_found" in text


async def test_get_attachment_gives_a_link_that_downloads_the_file_without_signing_in(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, logo, notes, token = await _with_files(db, tc)
    err, out = _tool(tc, token, "get_attachment", key=b.key, attachment_id=notes["id"])
    assert not err, out
    assert out["filename"] == "notes.txt" and out["size"] == len(NOTES) and out["content_type"] == "text/plain"
    assert out["url"].startswith("http://localhost:8080/api/attachment-links/")
    assert "curl -fsSL -o" in out["how"] and out["expires_at"]
    stranger = tc_factory()  # no session, no token
    r = stranger.get(_path_and_query(out["url"]))
    assert r.status_code == 200, r.text
    assert r.content == NOTES
    assert 'filename="notes.txt"' in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_get_attachment_shows_an_image_as_a_picture(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, logo, notes, token = await _with_files(db, tc)
    result = _call(tc, token, "get_attachment", key=b.key, attachment_id=logo["id"])
    assert not result.get("isError"), result
    assert result["content"][0]["type"] == "text"
    images = [c for c in result["content"] if c["type"] == "image"]
    assert images == [{"type": "image", "data": base64.b64encode(PNG).decode(), "mimeType": "image/png"}]
    assert result["structuredContent"]["filename"] == "voice-changer-logo.png"
    plain = _call(tc, token, "get_attachment", key=b.key, attachment_id=notes["id"])
    assert [c["type"] for c in plain["content"]] == ["text"]


async def test_get_attachment_refuses_a_message_image(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, logo, notes, token = await _with_files(db, tc)
    msg = await _message_image(b.task_id)
    err, text = _tool(tc, token, "get_attachment", key=b.key, attachment_id=str(msg))
    assert err and "not_found" in text


async def test_a_link_that_was_changed_expired_or_whose_file_is_gone_is_not_found(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, logo, notes, token = await _with_files(db, tc)
    stranger = tc_factory()
    err, out = _tool(tc, token, "get_attachment", key=b.key, attachment_id=notes["id"])
    link = _path_and_query(out["url"])
    q = parse_qs(urlsplit(out["url"]).query)
    # pointed at another file with the same signature
    assert stranger.get(link.replace(notes["id"], logo["id"])).status_code == 404
    # a later expiry with the same signature
    later = str(int(q["expires"][0]) + 3600)
    assert stranger.get(link.replace(f"expires={q['expires'][0]}", f"expires={later}")).status_code == 404
    # a made-up signature
    assert stranger.get(link.replace(q["sig"][0], "0" * len(q["sig"][0]))).status_code == 404
    # expired
    old = file_links.signed_link(uuid.UUID(notes["id"]), now=datetime.now(UTC) - timedelta(minutes=16))[0]
    assert stranger.get(_path_and_query(old)).status_code == 404
    # deleted: the link it gave stops working
    assert tc.delete(f"/api/attachments/{notes['id']}").status_code == 204
    assert stranger.get(link).status_code == 404


def test_links_last_fifteen_minutes():
    now = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    att = uuid.uuid4()
    url, expires_at = file_links.signed_link(att, now=now)
    assert expires_at == now + timedelta(minutes=15)
    q = parse_qs(urlsplit(url).query)
    expires, sig = int(q["expires"][0]), q["sig"][0]
    assert file_links.valid(att, expires, sig, now=now + timedelta(minutes=14))
    assert not file_links.valid(att, expires, sig, now=now + timedelta(minutes=15, seconds=1))
    assert not file_links.valid(uuid.uuid4(), expires, sig, now=now)


async def test_an_image_too_large_to_show_comes_as_a_link_only(db, tc_factory, monkeypatch):
    """A picture goes to the model base64-encoded, a third larger than the file: one that would pass the model's
    5 MB limit only before encoding is not shown, and its link still works."""
    from app.mcp_server import attachment_tools

    tc = tc_factory(lifespan=True)
    b, logo, notes, token = await _with_files(db, tc)
    assert attachment_tools.MAX_PICTURE_BYTES * 4 / 3 <= 5 * 1024 * 1024
    monkeypatch.setattr(attachment_tools, "MAX_PICTURE_BYTES", len(PNG) - 1)
    result = _call(tc, token, "get_attachment", key=b.key, attachment_id=logo["id"])
    assert [c["type"] for c in result["content"]] == ["text"]
    assert result["structuredContent"]["url"]
