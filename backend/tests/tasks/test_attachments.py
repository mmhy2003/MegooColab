from pathlib import Path

import pytest
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


async def test_direct_upload_served_inline_only_when_checked(client, db):
    await _task(client, db)
    png = (await client.post("/api/tasks/PAY-1/attachments",
                             files={"file": ("a.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "application/octet-stream")})).json()
    svg = (await client.post("/api/tasks/PAY-1/attachments",
                             files={"file": ("b.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")})).json()
    assert png["image"] is True and png["content_type"] == "image/png"
    assert svg["image"] is False
    shown = await client.get(f"/api/attachments/{png['id']}?inline=1")
    assert shown.headers["content-disposition"].startswith("inline")
    assert shown.headers["x-content-type-options"] == "nosniff"
    kept = await client.get(f"/api/attachments/{svg['id']}?inline=1")
    assert kept.headers["content-disposition"].startswith("attachment")
    assert kept.headers["x-content-type-options"] == "nosniff"


PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


async def test_real_pdf_is_stored_as_pdf_and_served_inline(client, db):
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": ("r.pdf", PDF, "application/octet-stream")})).json()
    assert att["content_type"] == "application/pdf" and att["image"] is False
    shown = await client.get(f"/api/attachments/{att['id']}?inline=1")
    assert shown.headers["content-disposition"].startswith("inline")
    assert shown.headers["content-type"] == "application/pdf"
    assert shown.headers["x-content-type-options"] == "nosniff"
    plain = await client.get(f"/api/attachments/{att['id']}")
    assert plain.headers["content-disposition"].startswith("attachment")


async def test_fake_pdf_is_stored_as_octet_stream_and_stays_a_download(client, db):
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": ("x.pdf", b"<html>hi</html>", "application/pdf")})).json()
    assert att["content_type"] == "application/octet-stream"
    r = await client.get(f"/api/attachments/{att['id']}?inline=1")
    assert r.headers["content-disposition"].startswith("attachment")


async def test_pdf_label_without_pdf_bytes_stays_a_download(client, db):
    # a file uploaded before this change, labelled by the browser only
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": ("old.pdf", b"not a pdf", "text/plain")})).json()
    row = (await db.execute(select(Attachment))).scalar_one()
    row.content_type = "application/pdf"
    await db.commit()
    r = await client.get(f"/api/attachments/{att['id']}?inline=1")
    assert r.headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize("name,body,ctype", [
    ("a.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml"),
    ("a.html", b"<script>alert(1)</script>", "text/html"),
    ("a.txt", b"hello", "text/plain"),
])
async def test_svg_html_and_text_are_never_inline(client, db, name, body, ctype):
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": (name, body, ctype)})).json()
    r = await client.get(f"/api/attachments/{att['id']}?inline=1")
    assert r.headers["content-disposition"].startswith("attachment")
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_range_request_answers_206(client, db):
    await _task(client, db)
    att = (await client.post("/api/tasks/PAY-1/attachments", files={"file": ("v.mp4", b"0123456789", "video/mp4")})).json()
    r = await client.get(f"/api/attachments/{att['id']}", headers={"Range": "bytes=2-5"})
    assert r.status_code == 206 and r.content == b"2345"
