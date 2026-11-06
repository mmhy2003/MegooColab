from app.agent_runs.models import RunPolicy
from app.chats.models import Chat, ChatMode
from app.mcp_server.kb_tools import KB_TOOL_ROLES
from app.mcp_server.workflow_tools import TOOL_ROLES
from app.notifications.models import DEFAULT_PREFS, Kind
from app.workflow import engine, methodology
from app.workflow.context import ROLE_KEY
from app.workflow.models import Needs, RunRole


def test_freestyle_role_writes_and_resumes():
    assert engine.ROLE_POLICY[RunRole.freestyle] == RunPolicy.workspace
    assert RunRole.freestyle not in engine.FRESH_ROLES and RunRole.freestyle not in engine.R1_ROLES
    assert engine.session_key(RunRole.freestyle, None) == "freestyle"
    assert ROLE_KEY[RunRole.freestyle] == "freestyle"


def test_freestyle_tools():
    for tool in ("ask_human", "record_decision", "record_tests"):
        assert RunRole.freestyle in TOOL_ROLES[tool]
    for tool in ("submit_design", "submit_plan", "complete_step", "submit_review", "report_finish",
                 "report_pr_fix", "submit_pr_review", "show_mockup"):
        assert RunRole.freestyle not in TOOL_ROLES[tool]
    assert RunRole.freestyle in KB_TOOL_ROLES["kb_write"]


def test_new_values_and_defaults():
    assert Needs.reply == "reply" and Kind.agent_replied == "agent_replied"
    assert DEFAULT_PREFS[Kind.agent_replied] == (True, False, False, False)
    assert methodology.OTHER_KEYS["chats"] == ["freestyle"] and "freestyle" in methodology.ALL_KEYS


async def test_freestyle_text_is_seeded(db):
    await methodology.seed_defaults(db)
    text = (await methodology.current(db, "freestyle")).body_md
    assert "megoo/" in text and "ask_human" in text and ".megoocolab/" in text


async def test_a_chat_is_a_workflow_chat_unless_told(db, client):
    from tests.chats.helpers import start, world
    await world(client, db)
    chat = await start(client)
    row = await db.get(Chat, __import__("uuid").UUID(chat["id"]))
    assert row.mode == ChatMode.workflow
