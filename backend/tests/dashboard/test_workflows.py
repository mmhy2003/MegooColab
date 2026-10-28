"""Workflows by stage: running, waiting for a person, paused or manual; and Done in the last 30 days."""

from datetime import UTC, datetime, timedelta

from tests.dashboard.conftest import add_task, add_workflow, dash
from tests.factories import login


async def test_stage_bars_split_running_waiting_and_paused(client, db, world):
    now = datetime.now(UTC)
    for stage, status, driver in [("brainstorm", "running", "runner"), ("design", "waiting_human", "runner"),
                                  ("plan", "paused", "runner"), ("build", "idle", "manual"),
                                  ("build", "running", "connect_only"), ("review", "waiting_human", "runner"),
                                  ("done", "running", "runner")]:
        await add_workflow(db, await add_task(db, world.pay), stage=stage, status=status, driver=driver)
    for days in (1, 20, 40):
        await add_workflow(db, await add_task(db, world.pay), stage="done", status="finished",
                           finished_at=now - timedelta(days=days))
    await add_workflow(db, await add_task(db, world.pay), stage="brainstorm", status="idle", started=False)
    await add_workflow(db, await add_task(db, world.web), stage="build", status="running")
    await login(client, world.viewer)
    body = await dash(client)
    rows = {r["stage"]: (r["running"], r["waiting"], r["paused"]) for r in body["stages"]["rows"]}
    assert list(rows) == ["brainstorm", "design", "plan", "build", "review", "done"]
    assert rows == {"brainstorm": (1, 0, 0), "design": (0, 1, 0), "plan": (0, 0, 1), "build": (1, 0, 1),
                    "review": (0, 1, 0), "done": (1, 0, 0)}
    assert body["stages"]["done_30d"] == 2
    assert (body["numbers"]["workflows_in_progress"], body["numbers"]["workflow_projects"]) == (7, 1)
