"""A connect-only agent (the person's own, over their personal MCP token) gets the task's images from get_task."""

import base64
import uuid

from sqlalchemy import select

from app.core.db import SessionLocal
from app.tasks.models import Attachment
from app.workflow.models import WorkflowQuestion
from tests.mcp.test_workflow_tools import MCP_HEADERS, _my_task, _personal, _tool
from tests.workflow.test_engine import _started

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _call(tc, token, name, **args) -> dict:
    r = tc.post(
        "/api/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}},
        headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["result"]


async def _answered_with_image(db, tc) -> tuple[str, str, str]:
    """A connect-only task whose agent asked a question, answered with a PNG: (key, token, image id)."""
    b, _ = await _started(db, tc)
    key = _my_task(tc, b.manager)["key"]
    token = _personal(tc)
    assert not _tool(tc, token, "ask_human", key=key, question="Which button?")[0]
    async with SessionLocal() as s:
        task_id = uuid.UUID(tc.get(f"/api/tasks/{key}").json()["id"])
        q = (await s.execute(select(WorkflowQuestion).where(WorkflowQuestion.task_id == task_id))).scalar_one()
    img = tc.post("/api/images", files={"file": ("shot.png", PNG, "image/png")}).json()["id"]
    r = tc.post(f"/api/tasks/{key}/questions/{q.id}/answer", json={"text": "this one", "image_ids": [img]})
    assert r.status_code == 200, r.text
    return key, token, img


async def test_get_task_returns_images_as_image_content(db, tc_factory):
    tc = tc_factory(lifespan=True)
    key, token, _ = await _answered_with_image(db, tc)
    result = _call(tc, token, "get_task", key=key)
    assert not result.get("isError")
    images = [c for c in result["content"] if c["type"] == "image"]
    assert images == [{"type": "image", "data": base64.b64encode(PNG).decode(), "mimeType": "image/png"}]
    assert result["content"][0]["type"] == "text"
    assert result["structuredContent"]["key"] == key and result["structuredContent"]["activity"]
    assert "## Images" in result["structuredContent"]["images_note"]


async def test_get_task_without_images_is_unchanged(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    key = _my_task(tc, b.manager)["key"]
    token = _personal(tc)
    result = _call(tc, token, "get_task", key=key)
    assert [c["type"] for c in result["content"]] == ["text"]
    assert "images_note" not in result["structuredContent"]


async def test_get_task_marks_delivered(db, tc_factory):
    tc = tc_factory(lifespan=True)
    key, token, img = await _answered_with_image(db, tc)
    async with SessionLocal() as s:
        assert (await s.get(Attachment, uuid.UUID(img))).delivered_at is None
    _call(tc, token, "get_task", key=key)
    async with SessionLocal() as s:
        assert (await s.get(Attachment, uuid.UUID(img))).delivered_at is not None
