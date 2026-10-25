"""The needs_you board filter and TaskOut.workflow.can_act (WF-6, PROJ-7)."""

import uuid
from types import SimpleNamespace

from sqlalchemy import update

from app.agents.models import Agent
from app.auth.models import Role
from app.teams.models import TeamMember
from app.workflow import engine, rules
from tests.factories import make_team, make_user
from tests.runner.test_runner_ws import _login
from tests.workflow.test_engine import _member, _started
from tests.workflow.test_questions import _waiting


def _needs_you(tc) -> list[dict]:
    r = tc.get("/api/projects/PAY/tasks", params={"needs_you": "true"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_needs_you_filter(db, tc_factory):
    tc = tc_factory(lifespan=True)
    await _started(db, tc)
    assert _needs_you(tc) == []  # running, not waiting
    listed = tc.get("/api/projects/PAY/tasks").json()
    assert listed[0]["workflow"]["status"] == "running" and listed[0]["workflow"]["can_act"] is True


async def test_needs_you_waiting_visible_to_owner_manager_not_member(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run, _qid = await _waiting(db, tc)
    [t] = _needs_you(tc)  # the agent's owner, who also manages
    assert t["key"] == b.key and t["workflow"]["needs"] == "question" and t["workflow"]["can_act"] is True
    other_manager = await make_user(db, role=Role.manager)
    team_id = tc.get("/api/projects/PAY").json()["team_ids"][0]
    db.add(TeamMember(team_id=uuid.UUID(team_id), user_id=other_manager.id))
    await db.commit()
    member = await _member(db, tc)
    _login(tc, other_manager)
    assert [x["key"] for x in _needs_you(tc)] == [b.key]  # a manager of the project
    assert tc.get(f"/api/tasks/{b.key}/workflow").json()["can_act"] is True
    _login(tc, member)
    assert _needs_you(tc) == []  # an unrelated member
    [plain] = tc.get("/api/projects/PAY/tasks").json()
    assert plain["workflow"]["status"] == "waiting_human" and plain["workflow"]["can_act"] is False
    assert tc.get(f"/api/tasks/{b.key}/workflow").json()["can_act"] is False


def test_can_act_rule():
    me, other = uuid.uuid4(), uuid.uuid4()
    user = SimpleNamespace(id=me, role=Role.member)
    task = SimpleNamespace(assignee_user_id=None)
    wf = SimpleNamespace(driver="runner")
    assert rules.can_act(user, task, wf, False, me)  # the agent's owner
    assert rules.can_act(user, task, wf, True, other)  # a manager
    assert not rules.can_act(user, task, wf, False, other)
    assert not rules.can_act(user, task, None, False, None)
    co = SimpleNamespace(driver="connect_only")
    assert rules.can_act(user, SimpleNamespace(assignee_user_id=me), co, False, other)  # connect_only assignee
    assert engine.can_act is rules.can_act
    viewer = SimpleNamespace(id=me, role=Role.viewer)  # read-only users never act, even as owner or assignee
    assert not rules.can_act(viewer, task, wf, True, me)
    assert not rules.can_act(viewer, SimpleNamespace(assignee_user_id=me), co, True, me)


async def test_owner_who_is_not_a_manager_sees_it_and_other_team_manager_does_not(db, tc_factory):
    tc = tc_factory(lifespan=True)
    b, _run, _qid = await _waiting(db, tc)
    owner = await _member(db, tc)
    await db.execute(update(Agent).where(Agent.id == uuid.UUID(b.agent["id"])).values(owner_id=owner.id))
    await db.commit()
    _login(tc, owner)
    [t] = _needs_you(tc)
    assert t["key"] == b.key and t["workflow"]["can_act"] is True
    outsider = await make_user(db, role=Role.manager)
    await make_team(db, outsider)
    _login(tc, outsider)  # manages another team, not this project
    r = tc.get("/api/projects/PAY/tasks", params={"needs_you": "true"})
    assert r.status_code != 200
