"""What an agent works on now (AgentOut.runs): every running run, newest first, for its owner and admins only."""

from datetime import UTC, datetime, timedelta

from app.auth.models import Role
from tests.dashboard.conftest import World, add_chat, add_cron_run, add_draft, add_question, add_run, add_task, world  # noqa: F401 (world is a fixture)
from tests.factories import login, make_user


def _row(agents: list[dict], name: str) -> dict:
    return next(a for a in agents if a["name"] == name)


async def _get(client, url: str) -> list[dict]:
    r = await client.get(url)
    assert r.status_code == 200, r.text
    return r.json()


async def test_admin_list_has_every_running_run_newest_first(client, db, world: World):
    now = datetime.now(UTC)
    task = await add_task(db, world.pay)
    await add_run(db, world.agent, task=task, started_at=now - timedelta(minutes=5))
    chat = await add_chat(db, world.pay, title="Pricing ideas")
    await add_run(db, world.agent, task=await add_task(db, world.pay, chat=chat), started_at=now - timedelta(minutes=4))
    q = await add_question(db, world.pay, status="routed")
    await add_run(db, world.agent, question=q, started_at=now - timedelta(minutes=3))
    cron_run = await add_cron_run(db, world.pay, name="Nightly check")
    await add_run(db, world.agent, cron_run=cron_run, started_at=now - timedelta(minutes=2))
    draft = await add_draft(db, world.viewer, world.agent, world.pay)
    await add_run(db, world.agent, draft=draft, started_at=now - timedelta(minutes=1))
    await add_run(db, world.agent, task=await add_task(db, world.pay), status="queued")
    await login(client, await make_user(db, role=Role.admin))
    runs = _row(await _get(client, "/api/admin/agents"), "Viewer bot")["runs"]
    assert [r["kind"] for r in runs] == ["draft", "cron", "question", "chat", "task"]
    drafted, cron, question, chatting, working = runs
    assert (drafted["link"], drafted["title"]) == (None, None)
    assert cron["link"] == f"/projects/PAY/crons/{cron_run.cron_id}"
    assert question["question_key"] == f"PAY-Q{q.number}"
    assert (chatting["title"], chatting["link"]) == ("Pricing ideas", f"/chats/{chat.id}")
    assert working["link"] == f"/projects/PAY/board?task={task.key}"


async def test_my_agents_lists_the_owners_runs_without_links_they_cannot_open(client, db, world: World):
    now = datetime.now(UTC)
    pay = await add_task(db, world.pay)
    await add_run(db, world.agent, task=pay, started_at=now - timedelta(minutes=2))
    web = await add_task(db, world.web)
    await add_run(db, world.agent, task=web, started_at=now - timedelta(minutes=1))
    await login(client, world.viewer)
    runs = _row(await _get(client, "/api/agents/mine"), "Viewer bot")["runs"]
    assert [(r["task_key"], r["link"]) for r in runs] == [
        (web.key, None), (pay.key, f"/projects/PAY/board?task={pay.key}")]
    assert web.key.startswith("WEB-")


async def test_project_agents_show_runs_only_to_the_owner_and_admins(client, db, world: World):
    await add_run(db, world.agent, task=await add_task(db, world.pay), started_at=datetime.now(UTC))
    await login(client, world.pay_manager)
    assert _row(await _get(client, "/api/projects/PAY/agents"), "Viewer bot")["runs"] == []
    await login(client, world.viewer)
    assert len(_row(await _get(client, "/api/projects/PAY/agents"), "Viewer bot")["runs"]) == 1
