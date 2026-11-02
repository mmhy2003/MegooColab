from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.tasks.models import Attachment
from tests.factories import login, make_project, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def _stored(att: Attachment) -> Path:
    return Path(get_settings().upload_dir) / att.storage_key


@pytest.fixture
async def member(client, db):
    await login(client, await make_user(db))


async def _rows(db) -> list[Attachment]:
    return list((await db.execute(select(Attachment))).scalars())


async def test_upload_png_is_kept_unsent(client, db, member):
    r = await client.post("/api/images", files={"file": ("shot.png", PNG, "application/octet-stream")})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "shot.png" and body["size"] == len(PNG) and body["content_type"] == "image/png"
    (row,) = await _rows(db)
    assert row.task_id is None and row.image is True and row.content_type == "image/png"
    assert _stored(row).read_bytes() == PNG


async def test_upload_without_a_name(client, db, member):
    # a browser always sends a name; one with nothing usable in it (".", "..") falls back to image.<type>
    r = await client.post("/api/images", files={"file": ("..", PNG, "image/png")})
    assert r.status_code == 201, r.text
    assert r.json()["filename"] == "image.png"


def _pending_files() -> int:
    return sum(1 for f in Path(get_settings().upload_dir, "pending").rglob("*") if f.is_file())


async def test_svg_named_png_is_refused(client, db, member):
    before = _pending_files()
    r = await client.post("/api/images", files={"file": ("x.png", SVG, "image/png")})
    assert r.status_code == 422 and r.json()["detail"] == "not_an_image"
    assert await _rows(db) == []
    assert _pending_files() == before  # nothing left on disk


async def test_too_large_is_refused(client, db, member):
    from app.images import files

    big = PNG + b"\x00" * (files.MAX_IMAGE_BYTES - len(PNG) + 1)
    r = await client.post("/api/images", files={"file": ("big.png", big, "image/png")})
    assert r.status_code == 413 and r.json()["detail"] == "image_too_large"
    assert await _rows(db) == []


async def test_pending_limit(client, db, member, monkeypatch):
    from app.images import router

    monkeypatch.setattr(router, "MAX_PENDING", 2)
    for _ in range(2):
        assert (await client.post("/api/images", files={"file": ("a.png", PNG, "image/png")})).status_code == 201
    r = await client.post("/api/images", files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 409 and r.json()["detail"] == "too_many_pending"


async def test_cleanup_removes_day_old_unsent(client, db):
    from app.images.jobs import cleanup_unsent
    from app.tasks.models import Task

    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})
    task = (await db.execute(select(Task))).scalar_one()
    for _ in range(3):
        assert (await client.post("/api/images", files={"file": ("a.png", PNG, "image/png")})).status_code == 201
    old, fresh, linked = sorted(await _rows(db), key=lambda r: r.storage_key)
    day_ago = datetime.now(UTC) - timedelta(hours=25)
    old.created_at = day_ago
    linked.created_at, linked.task_id = day_ago, task.id
    await db.commit()
    old_path, fresh_path = _stored(old), _stored(fresh)
    await cleanup_unsent(db)
    await db.commit()
    assert {r.id for r in await _rows(db)} == {fresh.id, linked.id}
    assert not old_path.exists() and fresh_path.exists()
