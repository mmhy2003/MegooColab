"""Needs you: what waits for a person, who it waits for, and the sidebar count."""

from datetime import UTC, datetime, timedelta

from app.auth.models import Role
from app.notifications.models import Notification
from app.workflow.models import WorkflowQuestion
from tests.dashboard.conftest import add_question, add_task, add_workflow, dash
from tests.factories import login


async def test_mine_holds_what_is_addressed_to_the_viewer(client, db, world):
    old = datetime.now(UTC) - timedelta(days=2)
    design = await add_task(db, world.pay, agent=world.agent, title="Refunds")
    await add_workflow(db, design, stage="design", status="waiting_human", needs="design_approval", agent=world.agent,
                       waiting_since=old)
    asks = await add_task(db, world.pay, user=world.viewer, title="Colours")
    await add_workflow(db, asks, stage="brainstorm", status="waiting_human", needs="question", driver="connect_only")
    db.add(WorkflowQuestion(task_id=asks.id, stage="brainstorm", body="Which colour?"))
    await db.commit()
    stuck = await add_task(db, world.pay, user=world.pay_manager)  # someone else's
    await add_workflow(db, stuck, stage="build", status="waiting_human", needs="escalation")
    await add_question(db, world.pay, status="draft", draft_agent=world.agent, title="Retry policy?")
    await add_question(db, world.pay, status="needs_human", title="Who owns billing?")
    db.add(Notification(user_id=world.viewer.id, kind="mentioned", title="Pat mentioned you", body="can you check?",
                        link="/projects/PAY/board?task=PAY-1"))
    db.add(Notification(user_id=world.viewer.id, kind="mentioned", title="read", body="", link="/x",
                        read_at=datetime.now(UTC)))
    leak = await add_task(db, world.web, user=world.viewer)  # WEB: never shown
    await add_workflow(db, leak, stage="plan", status="waiting_human", needs="plan_approval")
    await add_question(db, world.web, status="needs_human")
    await db.commit()
    await login(client, world.viewer)
    body = await dash(client, "mine")
    kinds = [n["kind"] for n in body["needs"]]
    assert kinds[0] == "design_approval"  # longest waiting first
    assert sorted(kinds) == sorted(["design_approval", "question", "draft_answer", "needs_human", "mention"])
    by = {n["kind"]: n for n in body["needs"]}
    assert by["question"]["detail"] == "Which colour?"
    assert by["design_approval"]["title"] == "Refunds"
    assert by["design_approval"]["link"] == f"/projects/PAY/board?task={by['design_approval']['ref']}"
    assert by["draft_answer"]["ref"].startswith("PAY-Q") and by["draft_answer"]["link"].startswith("/questions/")
    assert by["mention"]["notification_id"] and by["mention"]["link"] == "/projects/PAY/board?task=PAY-1"
    assert (body["numbers"]["need_you"], body["numbers"]["need_you_over_day"]) == (5, 1)
    assert (await client.get("/api/dashboard/count")).json() == {"needs_you": 5}


async def test_teams_holds_every_wait_with_who_it_waits_for_and_no_mentions(client, db, world):
    stuck = await add_task(db, world.pay, user=world.pay_manager)
    await add_workflow(db, stuck, stage="build", status="waiting_human", needs="escalation", agent=world.agent)
    await add_question(db, world.pay, status="needs_human")
    db.add(Notification(user_id=world.viewer.id, kind="mentioned", title="m", body="", link="/x"))
    await db.commit()
    await login(client, world.viewer)
    rows = (await dash(client, "teams"))["needs"]
    assert {r["kind"] for r in rows} == {"escalation", "needs_human"}
    by = {r["kind"]: r for r in rows}
    assert sorted(by["escalation"]["waiting_for"]) == sorted([world.viewer.name, world.pay_manager.name])
    assert by["needs_human"]["waiting_for"] == ["anyone on PAY"]


async def test_wait_without_an_agent_is_addressed_to_the_assignee(client, db, world):
    t = await add_task(db, world.pay, user=world.viewer)
    await add_workflow(db, t, stage="review", status="waiting_human", needs="human_code_review", driver="manual")
    await login(client, world.viewer)
    [row] = (await dash(client, "teams"))["needs"]
    assert row["waiting_for"] == [world.viewer.name]
    assert [r["kind"] for r in (await dash(client, "mine"))["needs"]] == ["human_code_review"]


async def test_needs_keeps_ten_and_counts_all(client, db, world):
    for i in range(12):
        t = await add_task(db, world.pay, user=world.viewer)
        await add_workflow(db, t, stage="plan", status="waiting_human", needs="plan_approval",
                           waiting_since=datetime.now(UTC) - timedelta(minutes=i))
    await login(client, world.viewer)
    body = await dash(client, "mine")
    assert len(body["needs"]) == 10 and body["numbers"]["need_you"] == 12


async def test_viewers_are_not_asked_to_answer_questions(client, db, world):
    world.viewer.role = Role.viewer
    await db.commit()
    await add_question(db, world.pay, status="needs_human")
    await login(client, world.viewer)
    assert (await client.get("/api/dashboard/count")).json() == {"needs_you": 0}


async def test_count_is_counted_in_the_database(client, db, world, monkeypatch):
    """The sidebar badge counts without building every row: the same total the dashboard shows under Mine."""
    from app.dashboard import needs

    design = await add_task(db, world.pay, agent=world.agent)
    await add_workflow(db, design, stage="design", status="waiting_human", needs="design_approval", agent=world.agent)
    await add_question(db, world.pay, status="draft", draft_agent=world.agent)
    await add_question(db, world.pay, status="needs_human")
    db.add(Notification(user_id=world.viewer.id, kind="mentioned", title="m", body="", link="/x"))
    leak = await add_task(db, world.web, user=world.viewer)  # WEB: not counted
    await add_workflow(db, leak, stage="plan", status="waiting_human", needs="plan_approval")
    await db.commit()
    await login(client, world.viewer)
    assert (await dash(client, "mine"))["numbers"]["need_you"] == 4

    async def built_rows(*_a, **_k):
        raise AssertionError("the count built the rows")

    monkeypatch.setattr(needs, "needs", built_rows)
    assert (await client.get("/api/dashboard/count")).json() == {"needs_you": 4}
