"""Knowledge Base MCP tools (AGT-31): the token owner's space access; writes only for workspace roles."""

import uuid

from sqlalchemy import select, update

from app.agent_runs.models import AgentRun
from app.core.db import SessionLocal
from app.kb import access
from app.kb.models import KbRevision
from tests.factories import make_team, make_user
from tests.mcp.test_workflow_tools import _personal, _run_token, _tool
from tests.workflow.test_engine import _started


async def _spaces(db, b):
    await access.ensure_spaces(db)
    org = await access.org_space(db)
    project_id = b.tc.get("/api/projects/PAY").json()["id"]
    project_space = await access.space_for_project(db, project_id)
    outsider = await make_user(db)
    other_team = await make_team(db, outsider)
    other = await access.space_for_team(db, other_team.id)
    await db.commit()
    return org, project_space, other


async def test_kb_search_and_read_respect_owner_access(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    org, _pspace, other = await _spaces(db, b)
    # an admin writes a document the agent's owner cannot read
    from app.auth.models import Role

    admin = await make_user(db, role=Role.admin)
    ac = tc_factory()
    r = ac.post("/api/auth/login", json={"email": admin.email, "password": "correct-horse-1"})
    assert r.status_code == 200
    hidden = ac.post(f"/api/kb/spaces/{other.id}/documents", json={"title": "Hidden zebra", "body_md": "zebra"}).json()
    shown = ac.post(f"/api/kb/spaces/{org.id}/documents", json={"title": "Shown zebra", "body_md": "zebra"}).json()

    token = await _run_token(run)
    err, out = _tool(tc, token, "kb_search", query="zebra")
    assert not err, out
    assert [r["document_id"] for r in out["results"]] == [shown["id"]]
    err, text = _tool(tc, token, "kb_read", document_id=hidden["id"])
    assert err and "document_not_found" in text
    err, doc = _tool(tc, token, "kb_read", document_id=shown["id"])
    assert not err and doc["body_md"] == "zebra" and doc["revision"] == 1 and doc["truncated"] is False
    err, spaces = _tool(tc, token, "kb_list")
    assert not err and str(other.id) not in {s["id"] for s in spaces["spaces"]}
    err, text = _tool(tc, token, "kb_list", space_id=str(other.id))
    assert err and "space_not_found" in text
    err, text = _tool(tc, token, "kb_search", query="zebra", space_id=str(other.id))
    assert not err and text["results"] == []


async def test_kb_write_refused_for_read_only_roles(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    org, _, _ = await _spaces(db, b)
    for role in ("brainstorm", "plan", "step_review", "final_review"):
        token = await _run_token(run, workflow_role=role)
        err, text = _tool(tc, token, "kb_write", space_id=str(org.id), title="X", body_md="y")
        assert err and "not_allowed_in_role" in text, role
        err, _ = _tool(tc, token, "kb_search", query="x")
        assert not err, role


async def test_kb_write_creates_with_folder_path_and_agent_author(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)
    _, pspace, _ = await _spaces(db, b)
    token = await _run_token(run, workflow_role="implement")
    err, out = _tool(
        tc, token, "kb_write", space_id=str(pspace.id), folder_path="guides/api", title="Webhooks",
        body_md="How webhooks work.", summary="first",
    )
    assert not err, out
    assert (out["path"], out["title"], out["revision"]) == ("guides/api", "Webhooks", 1)
    async with SessionLocal() as s:
        rev = (await s.execute(select(KbRevision).where(KbRevision.document_id == uuid.UUID(out["id"])))).scalar_one()
    assert rev.author_user_id == b.manager.id and str(rev.author_agent_id) == b.agent["id"]
    # the same folders are reused
    err, again = _tool(tc, token, "kb_write", space_id=str(pspace.id), folder_path="/guides//api/", title="Other",
                       body_md="")
    assert not err and again["path"] == "guides/api"
    err, text = _tool(tc, token, "kb_write", space_id=str(pspace.id), folder_path="a\\b", title="T", body_md="")
    assert err and "invalid_folder" in text
    # update
    err, upd = _tool(tc, token, "kb_write", document_id=out["id"], base_revision=1, title="Webhooks",
                     body_md="Updated.")
    assert not err and upd["revision"] == 2
    err, text = _tool(tc, token, "kb_write", document_id=out["id"], title="Webhooks", body_md="no base")
    assert err and "base_revision_required" in text
    err, text = _tool(tc, token, "kb_write", title="Nowhere", body_md="")
    assert err and "space_required" in text


async def test_kb_write_conflict_tool_error(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run = await _started(db, tc)
    org, _, _ = await _spaces(db, b)
    token = _personal(tc)
    err, out = _tool(tc, token, "kb_write", space_id=str(org.id), title="Doc", body_md="v1")
    assert not err, out
    assert _tool(tc, token, "kb_write", document_id=out["id"], base_revision=1, title="Doc", body_md="v2")[0] is False
    err, text = _tool(tc, token, "kb_write", document_id=out["id"], base_revision=1, title="Doc", body_md="v3")
    assert err and "kb_conflict" in text
    async with SessionLocal() as s:
        revs = (await s.execute(select(KbRevision).where(KbRevision.document_id == uuid.UUID(out["id"])))).scalars()
        assert [r.author_agent_id for r in revs] == [None, None]  # personal token: no agent


async def test_kb_read_truncates_large_body(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    org, _, _ = await _spaces(db, b)
    doc = tc.post(f"/api/kb/spaces/{org.id}/documents", json={"title": "Big", "body_md": "x" * 150_000}).json()
    token = _personal(tc)
    err, out = _tool(tc, token, "kb_read", document_id=doc["id"])
    assert not err and len(out["body_md"]) == 100_000 and out["truncated"] is True
    tc.put(f"/api/kb/documents/{doc['id']}", json={"base_revision": 1, "body_md": "small"})
    err, old = _tool(tc, token, "kb_read", document_id=doc["id"], revision=1)
    assert not err and old["revision"] == 1 and old["truncated"] is True
    err, text = _tool(tc, token, "kb_read", document_id=doc["id"], revision=7)
    assert err and "revision_not_found" in text


async def test_run_token_kb_tools_after_run_ended_401(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _b, run = await _started(db, tc)
    token = await _run_token(run, workflow_role="implement")
    async with SessionLocal() as s:
        await s.execute(update(AgentRun).where(AgentRun.id == run.id).values(status="completed"))
        await s.commit()
    for name, args in (("kb_search", {"query": "x"}), ("kb_list", {}), ("kb_write", {"title": "t", "body_md": ""})):
        err, detail = _tool(tc, token, name, **args)
        assert err and detail == "invalid_token", name


def test_methodology_defaults_mention_kb_tools():
    from pathlib import Path

    import app.workflow.methodology as m

    defaults = Path(m.__file__).parent / "methodology_texts" / "defaults"
    for name in ("brainstorm.md", "plan.md", "build_implement.md"):
        text = (defaults / name).read_text(encoding="utf-8")
        assert "kb_search" in text and "kb_read" in text, name
    assert "kb_write" in (defaults / "build_implement.md").read_text(encoding="utf-8")
