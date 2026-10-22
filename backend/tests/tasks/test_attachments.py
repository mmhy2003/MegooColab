from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.tasks.models import Attachment
from tests.factories import login, make_project, make_user


async def _task(client, db):
    await make_project(client, db)
    await client.post("/api/projects/PAY/tasks", json={"title": "a", "type": "task"})


async def test_upload_and_download_attachment_roundtrip(client, db):
    await _task(client, db)
    r = await client.post("/api/tasks/PAY-1/attachments", files={"file": ("notes.txt", b"hello world", "text/plain")})
    assert r.status_code == 201
    att = r.json()
    assert att["filename"] == "notes.txt" and att["size"] == 11
    listed = (await client.get("/api/tasks/PAY-1/attachments")).json()
    assert [a["id"] for a in listed] == [att["id"]]
    d = await client.get(f"/api/attachments/{att['id']}")
    assert d.status_code == 200 and d.content == b"hello world"
    assert d.headers["content-disposition"].startswith("attachment")
    assert (await client.delete(f"/api/attachments/{att['id']}")).status_code == 204
    assert (await client.get(f"/api/attachments/{att['id']}")).status_code == 404


async def test_attachment_over_limit_413(client, db, monkeypatch):
    from app.tasks import activity

    monkeypatch.setattr(activity, "MAX_ATTACHMENT_BYTES", 10)
    await _task(client, db)
    r = await client.post("/api/tasks/PAY-1/attachments", files={"file": ("big.bin", b"x" * 11, "application/octet-stream")})
    assert r.status_code == 413
    assert (await db.execute(select(Attachment))).scalars().all() == []


async def test_attachment_download_requires_project_access(client, client_factory, db):
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": ("a.txt", b"x", "text/plain")})).json()
    outsider = await make_user(db)
    oc = client_factory()
    await login(oc, outsider)
    assert (await oc.get(f"/api/attachments/{att['id']}")).status_code == 404


async def test_attachment_filename_path_traversal_is_neutralized(client, db):
    await _task(client, db)
    r = await client.post("/api/tasks/PAY-1/attachments", files={"file": ("../../etc/passwd", b"x", "text/plain")})
    assert r.status_code == 201 and r.json()["filename"] == "passwd"
    row = (await db.execute(select(Attachment))).scalar_one()
    stored = Path(get_settings().upload_dir) / row.storage_key
    assert stored.resolve().is_relative_to(Path(get_settings().upload_dir).resolve())
    assert stored.read_bytes() == b"x"
    assert "passwd" not in row.storage_key
