import io
import zipfile

from app.auth.models import Role
from tests.factories import login, make_user

SKILL_MD = b"---\nname: ui-review\ndescription: Use when reviewing a UI\n---\n# UI review\n"


async def _as(client, db, role=Role.member):
    u = await make_user(db, role=role)
    await login(client, u)
    return u


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, data in files.items():
            z.writestr(path, data)
    return buf.getvalue()


async def _upload_zip(client, files, url="/api/hub/skills", method="post"):
    return await getattr(client, method)(url, files={"file": ("skill.zip", _zip(files), "application/zip")})


async def test_upload_zip_creates_skill(client, db):
    await _as(client, db)
    r = await _upload_zip(client, {"ui-review/SKILL.md": SKILL_MD, "ui-review/scripts/contrast.py": b"print(1)"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert (t["kind"], t["name"], t["description"]) == ("skill", "ui-review", "Use when reviewing a UI")
    assert t["files"] == [
        {"path": "SKILL.md", "size": len(SKILL_MD), "runs_on": None},
        {"path": "scripts/contrast.py", "size": 8, "runs_on": ["linux", "macos", "windows"]},
    ]
    assert t["runs_code"] is True and t["spec"] is None


async def test_upload_folder_files(client, db):
    await _as(client, db)
    r = await client.post(
        "/api/hub/skills",
        files=[
            ("files", ("ui-review/SKILL.md", SKILL_MD, "text/markdown")),
            ("files", ("ui-review/scripts/contrast.py", b"print(1)", "text/x-python")),
        ],
    )
    assert r.status_code == 201, r.text
    assert [f["path"] for f in r.json()["files"]] == ["SKILL.md", "scripts/contrast.py"]


async def test_missing_or_bad_name_422(client, db):
    await _as(client, db)
    r = await _upload_zip(client, {"SKILL.md": b"# no frontmatter"})
    assert r.status_code == 422 and r.json()["detail"] == "hub_bad_name"
    r = await _upload_zip(client, {"SKILL.md": b"---\nname: Bad Name\n---\n"})
    assert r.status_code == 422 and r.json()["detail"] == "hub_bad_name"


async def test_bad_paths_refused(client, db):
    await _as(client, db)
    r = await _upload_zip(client, {"SKILL.md": SKILL_MD, "../evil.md": b"x"})
    assert r.status_code == 422 and r.json()["detail"] == "hub_bad_path"


async def test_zip_bomb_refused(client, db):
    await _as(client, db)
    r = await _upload_zip(client, {"SKILL.md": SKILL_MD, "zeros.bin": b"\0" * (3 << 20)})
    assert r.status_code == 413 and r.json()["detail"] == "hub_skill_too_large"


async def test_not_a_zip_422(client, db):
    await _as(client, db)
    r = await client.post("/api/hub/skills", files={"file": ("skill.zip", b"not a zip", "application/zip")})
    assert r.status_code == 422 and r.json()["detail"] == "hub_bad_zip"


async def test_duplicate_skill_name_409(client, db):
    await _as(client, db)
    await _upload_zip(client, {"SKILL.md": SKILL_MD})
    r = await _upload_zip(client, {"SKILL.md": SKILL_MD})
    assert r.status_code == 409 and r.json()["detail"] == "hub_name_taken"


async def test_replace_files_bumps_version(client, db):
    await _as(client, db)
    t = (await _upload_zip(client, {"SKILL.md": SKILL_MD, "a.md": b"a"})).json()
    md2 = SKILL_MD.replace(b"Use when reviewing a UI", b"Newer words")
    r = await _upload_zip(client, {"SKILL.md": md2}, url=f"/api/hub/tools/{t['id']}/files", method="put")
    assert r.status_code == 200, r.text
    got = r.json()
    assert [f["path"] for f in got["files"]] == ["SKILL.md"]
    assert (got["version"], got["rev"], got["description"], got["name"]) == (2, 2, "Newer words", "ui-review")


async def test_read_file_text_and_binary(client, db):
    await _as(client, db)
    png = b"\x89PNG\r\n\x1a\n\x00\x00\xff"
    t = (await _upload_zip(client, {"SKILL.md": SKILL_MD, "logo.png": png})).json()
    r = await client.get(f"/api/hub/tools/{t['id']}/file", params={"path": "SKILL.md"})
    assert r.json() == {"path": "SKILL.md", "size": len(SKILL_MD), "text": SKILL_MD.decode()}
    r = await client.get(f"/api/hub/tools/{t['id']}/file", params={"path": "logo.png"})
    assert r.json()["text"] is None
    assert (await client.get(f"/api/hub/tools/{t['id']}/file", params={"path": "nope"})).status_code == 404


async def test_other_user_cannot_read_private_skill(client, client_factory, db):
    await _as(client, db)
    t = (await _upload_zip(client, {"SKILL.md": SKILL_MD})).json()
    other = client_factory()
    await _as(other, db)
    assert (await other.get(f"/api/hub/tools/{t['id']}/file", params={"path": "SKILL.md"})).status_code == 404
