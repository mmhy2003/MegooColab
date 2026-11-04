"""The server blanks a run's secret values out of everything the agent writes through MCP."""

from sqlalchemy import select

from app.secrets.blanking import blank, blank_json
from app.tasks.models import Comment
from tests.mcp.test_workflow_tools import _personal, _run_token, _tool
from tests.workflow.test_engine import _started


def test_blank_longest_first_and_short_values_kept():
    secrets = {"A": "abcd", "B": "abcdef", "C": "xyz"}
    assert blank("abcdef abcd xyz", secrets) == "[B] [A] xyz"
    assert blank("nothing here", secrets) == "nothing here"
    assert blank("abcd", {}) == "abcd"


def test_blank_json_nested():
    secrets = {"DB_PASSWORD": "hunter22"}
    data = {"hunter22": ["postgres://u:hunter22@db/app", {"note": "pw hunter22", "n": 3}], "ok": True}
    assert blank_json(data, secrets) == {
        "hunter22": ["postgres://u:[DB_PASSWORD]@db/app", {"note": "pw [DB_PASSWORD]", "n": 3}], "ok": True,
    }


async def test_mcp_tool_call_arguments_are_blanked(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, run = await _started(db, tc)  # tc is the agent's owner
    r = tc.post("/api/secrets", json={"name": "TOKEN", "description": "An API token", "value": "supersecret1"})
    assert r.status_code == 201, r.text
    token = await _run_token(run)
    err, out = _tool(tc, token, "comment_on_task", key=b.key, body_md="use supersecret1 here")
    assert not err, out
    bodies = (await db.execute(select(Comment.body_md).where(Comment.task_id == b.task_id))).scalars().all()
    assert "use [TOKEN] here" in bodies and not any("supersecret1" in x for x in bodies)


async def test_personal_token_calls_untouched(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _ = await _started(db, tc)
    tc.post("/api/secrets", json={"name": "TOKEN", "description": "An API token", "value": "supersecret1"})
    err, out = _tool(tc, _personal(tc), "comment_on_task", key=b.key, body_md="mine: supersecret1")
    assert not err, out
    bodies = (await db.execute(select(Comment.body_md).where(Comment.task_id == b.task_id))).scalars().all()
    assert "mine: supersecret1" in bodies
