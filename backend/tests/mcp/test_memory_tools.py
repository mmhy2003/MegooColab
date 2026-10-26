"""Memory MCP tools (AGT-31): the token owner's scopes; every role may use them."""

import uuid

from app.core.config import get_settings
from app.memory.models import ScopeKind
from app.workflow.models import RunRole
from tests.factories import make_team, make_user
from tests.mcp.test_workflow_tools import _personal, _run_token, _tool
from tests.memory.test_search import _add
from tests.workflow.test_engine import _started


async def test_memory_tools_respect_owner_access(db, tc_factory):
    tc = tc_factory(lifespan=True)
    _b, run = await _started(db, tc)
    pid = uuid.UUID(tc.get("/api/projects/PAY").json()["id"])
    outsider = await make_user(db)
    other = await make_team(db, outsider)
    await _add(db, "Webhooks are signed with HMAC", scope=(ScopeKind.project, pid))
    await _add(db, "Webhooks leak secret things", scope=(ScopeKind.team, other.id))
    for role in (RunRole.brainstorm, RunRole.final_review):
        token = await _run_token(run, workflow_role=role)
        err, out = _tool(tc, token, "search_memory", query="webhooks")
        assert not err, out
        assert [r["text"] for r in out["results"]] == ["Webhooks are signed with HMAC"]
        assert set(out["results"][0]) == {"id", "entity", "text", "kind", "confidence", "source_label"}
    token = _personal(tc)
    err, out = _tool(tc, token, "ask_memory", question="How are webhooks signed?", project_key="PAY")
    assert not err and out["cited"][0]["text"] == "Webhooks are signed with HMAC"
    assert "From memory" in out["answer_md"]
    err, text = _tool(tc, token, "search_memory", query="webhooks", project_key="NOPE")
    assert err and "project_not_found" in text


async def test_ask_memory_tool_not_configured_error(db, tc_factory, monkeypatch):
    tc = tc_factory(lifespan=True)
    _b, _ = await _started(db, tc)
    await _add(db, "Webhooks are signed with HMAC")
    token = _personal(tc)
    monkeypatch.setattr(get_settings(), "ai_fake", False)
    err, text = _tool(tc, token, "ask_memory", question="webhooks signed?")
    assert err and "memory_answering_not_configured" in text
