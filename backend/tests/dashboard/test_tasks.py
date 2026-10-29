"""Task figures: open, done, overdue, my tasks, tasks finished per day and the project rows."""

from datetime import UTC, date, datetime, timedelta

from app.dashboard.scope import day_start, today, week_end
from app.dashboard.tasks import due_label
from tests.dashboard.conftest import add_task, dash
from tests.factories import login


async def test_task_numbers_count_tasks_stories_and_bugs_only(client, db, world):
    now, yesterday = datetime.now(UTC), today() - timedelta(days=1)
    await add_task(db, world.pay, category="before")
    await add_task(db, world.pay, category="working", type="story")
    await add_task(db, world.pay, category="review", type="bug", due=yesterday, user=world.viewer)
    await add_task(db, world.pay, category="before", type="subtask", due=yesterday)
    await add_task(db, world.pay, category="before", type="epic")
    await add_task(db, world.pay, category="done", completed_at=now - timedelta(days=2), due=yesterday)
    await add_task(db, world.pay, category="done", completed_at=now - timedelta(days=9))
    await add_task(db, world.pay, category="done", type="subtask", completed_at=now - timedelta(days=1))
    await add_task(db, world.web, category="working", due=yesterday)  # not the viewer's project
    await add_task(db, world.web, category="done", completed_at=now)
    await login(client, world.viewer)
    n = (await dash(client))["numbers"]
    assert (n["open_tasks"], n["open_in_progress"]) == (3, 2)
    assert (n["done_7d"], n["done_prev_7d"]) == (1, 1)
    assert (n["overdue"], n["overdue_mine"]) == (1, 1)


async def test_mine_counts_tasks_of_the_viewer_and_their_agents(client, db, world):
    await add_task(db, world.pay, user=world.viewer)
    await add_task(db, world.pay, agent=world.agent)
    await add_task(db, world.pay, user=world.pay_manager)
    await login(client, world.viewer)
    assert (await dash(client, "teams"))["numbers"]["open_tasks"] == 3
    assert (await dash(client, "mine"))["numbers"]["open_tasks"] == 2


async def test_my_tasks_are_the_viewers_own_due_this_week_whatever_the_scope(client, db, world):
    t = today()
    await add_task(db, world.pay, user=world.viewer, due=t + timedelta(days=1), title="soon")
    await add_task(db, world.pay, user=world.viewer, due=t, title="today")
    await add_task(db, world.pay, user=world.viewer, due=t - timedelta(days=3), title="late")
    await add_task(db, world.pay, user=world.viewer, due=week_end(t) + timedelta(days=1), title="next week")
    await add_task(db, world.pay, user=world.viewer, due=t - timedelta(days=1), category="done", title="done")
    await add_task(db, world.pay, user=world.viewer, due=t, type="subtask", title="step")
    await add_task(db, world.pay, user=world.pay_manager, due=t, title="theirs")
    await login(client, world.viewer)
    expected = ["late", "today"] + (["soon"] if t + timedelta(days=1) <= week_end(t) else [])
    for scope in ("mine", "teams"):
        rows = (await dash(client, scope))["my_tasks"]
        assert [r["title"] for r in rows] == expected
    assert rows[0]["due"] == "overdue" and rows[1]["due"] == "today"
    assert rows[0]["link"].startswith("/projects/PAY/board?task=PAY-")


async def test_my_tasks_stops_at_eight(client, db, world):
    for i in range(9):
        await add_task(db, world.pay, user=world.viewer, due=today() - timedelta(days=i + 1))
    await login(client, world.viewer)
    assert len((await dash(client))["my_tasks"]) == 8


def test_due_label_on_a_sunday():
    sunday = date(2026, 11, 1)
    assert week_end(sunday) == sunday
    assert due_label(sunday, sunday) == "today"
    assert due_label(date(2026, 10, 31), sunday) == "overdue"
    assert due_label(date(2026, 10, 29), date(2026, 10, 28)) == "week"


async def test_finished_daily_splits_agents_and_people_over_14_days(client, db, world):
    start = day_start(today())
    await add_task(db, world.pay, category="done", agent=world.agent, completed_at=start + timedelta(minutes=1))
    await add_task(db, world.pay, category="done", user=world.viewer, completed_at=start + timedelta(minutes=2))
    await add_task(db, world.pay, category="done", completed_at=start - timedelta(days=13) + timedelta(hours=1))
    await add_task(db, world.pay, category="done", completed_at=start - timedelta(days=14) + timedelta(hours=1))
    await add_task(db, world.pay, category="done", type="subtask", agent=world.agent, completed_at=start)
    await add_task(db, world.web, category="done", completed_at=start + timedelta(minutes=1))
    await login(client, world.viewer)
    days = (await dash(client))["finished_daily"]
    assert len(days) == 14
    assert days[-1] == {"day": today().isoformat(), "agents": 1, "people": 1}
    assert days[0] == {"day": (today() - timedelta(days=13)).isoformat(), "agents": 0, "people": 1}


async def test_projects_rows(client, db, world):
    await add_task(db, world.pay, category="before", due=today() - timedelta(days=1))
    await add_task(db, world.pay, category="working")
    await add_task(db, world.pay, category="done", completed_at=datetime.now(UTC))
    await add_task(db, world.pay, type="subtask")
    await login(client, world.viewer)
    [row] = (await dash(client))["projects"]
    assert row == {"key": "PAY", "name": "Project PAY", "open": 2, "in_progress": 1, "done": 1, "late": 1}


async def test_today_is_the_browsers_day(client, db, world):
    """Due today means today where the viewer is: Kiritimati (UTC+14) is always a day or two ahead of Pago Pago
    (UTC-11)."""
    from zoneinfo import ZoneInfo

    ahead = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    await add_task(db, world.pay, user=world.viewer, due=ahead, title="due")
    await login(client, world.viewer)
    r = await client.get("/api/dashboard", params={"tz": "Pacific/Kiritimati"})
    assert [t["due"] for t in r.json()["my_tasks"]] == ["today"]
    r = await client.get("/api/dashboard", params={"tz": "Pacific/Pago_Pago"})
    assert "today" not in [t["due"] for t in r.json()["my_tasks"]]
    r = await client.get("/api/dashboard", params={"tz": "Not/A_Zone"})  # unknown: the server's day
    assert r.status_code == 200, r.text
