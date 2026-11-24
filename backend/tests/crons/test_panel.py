"""Cron run panels: the agent's tiles and charts kept with a run (MC-174)."""

import importlib.util
import json
from pathlib import Path

from sqlalchemy import text

from app.a2ui import service
from app.a2ui.service import PANEL_COMPONENTS
from app.core.db import SessionLocal
from app.crons.models import CronRun
from app.tasks.models import Task
from tests.crons.test_report import BASE, _cron_run, _cron_runs, _finish, _report, _tasks
from tests.mcp.test_workflow_tools import _run_token, _tool

EXAMPLE = json.loads((Path(service.__file__).parent / "panel_example.json").read_text())
_FIXTURES = json.loads((Path(__file__).parents[1] / "a2ui" / "fixtures" / "panels.json").read_text())
PANEL = next(f["panel"] for f in _FIXTURES["valid"] if f["name"] == "example")
_INVALID = {f["name"]: f["panel"] for f in _FIXTURES["invalid"]}


def _detail(out: str) -> str:
    """A refused submit_cron_report's detail, without the prefix the MCP server puts before it."""
    return out.removeprefix("Error executing tool submit_cron_report: ")


def _load_migration():
    [path] = (Path(__file__).parents[2] / "migrations" / "versions").glob("*_cron_run_panel.py")
    spec = importlib.util.spec_from_file_location("cron_run_panel", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_cron_runs_panel_column(db):
    async with SessionLocal() as s:
        row = (await s.execute(text(
            "SELECT is_nullable, data_type FROM information_schema.columns "
            "WHERE table_name = 'cron_runs' AND column_name = 'panel'"
        ))).one()
    assert tuple(row) == ("YES", "jsonb")


def test_the_migration_follows_the_previous_head():
    assert _load_migration().down_revision == "449e0d24f6b0"


async def test_runs_carry_the_panel_and_last_run_does_not(client, db, world):
    cron_id, _ = await _cron_run(client, world, "report")
    [cr] = await _cron_runs(cron_id)
    stored = service.clean_panel(EXAMPLE)
    async with SessionLocal() as s:
        (await s.get(CronRun, cr.id)).panel = stored
        await s.commit()

    runs = (await client.get(f"{BASE}/{cron_id}/runs")).json()
    assert runs[0]["panel"] == stored
    assert (await client.get(f"{BASE}/{cron_id}/runs/{cr.id}")).json()["panel"] == stored
    assert (await client.get(BASE)).json()[0]["last_run"]["panel"] is None
    assert (await client.get(f"{BASE}/{cron_id}")).json()["last_run"]["panel"] is None


async def test_a_run_without_a_panel_has_null(client, db, world):
    cron_id, _ = await _cron_run(client, world, "report")
    [run] = (await client.get(f"{BASE}/{cron_id}/runs")).json()
    assert run["panel"] is None


async def test_a_panel_is_stored_and_the_report_is_unchanged(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    cron_id, run = await _cron_run(client, world, "tasks")
    err, out = await _report(tc, run, findings=[{"title": "P", "detail": "d", "new_task": True}], panel=PANEL)
    assert not err, out
    assert out == {"ok": True, "tasks_created": 1, "notes": []}
    [cr] = await _cron_runs(cron_id)
    assert cr.panel["createSurface"]["components"] == PANEL["components"]
    assert cr.panel["createSurface"]["surfaceId"].startswith("panel-")
    assert set(cr.report) == {"summary", "findings", "checked", "nothing_new", "notes", "submitted"}


async def test_a_refused_panel_stores_nothing(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    cron_id, run = await _cron_run(client, world, "tasks")
    findings = [{"title": "Refused panel finding", "detail": "d", "new_task": True}]
    err, out = await _report(tc, run, findings=findings, panel=_INVALID["five-series"])
    assert err and _detail(out).startswith("invalid_panel"), out
    [cr] = await _cron_runs(cron_id)
    assert cr.report is None and cr.panel is None
    assert await _tasks(Task.title == "Refused panel finding") == []

    err, out = await _report(tc, run, findings=findings)
    assert not err, out
    assert len(await _tasks(Task.title == "Refused panel finding")) == 1


async def test_a_panel_with_an_input_is_refused(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    _, run = await _cron_run(client, world, "report")
    err, out = await _report(tc, run, panel=_INVALID["input"])
    assert err and _detail(out).startswith("panel_with_inputs"), out


async def test_already_submitted_comes_before_the_panel(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    _, run = await _cron_run(client, world, "report")
    err, out = await _report(tc, run)
    assert not err, out
    err, out = await _report(tc, run, panel=_INVALID["five-series"])
    assert err and _detail(out).startswith("already_submitted"), out


async def test_a_report_without_a_panel_keeps_it_null(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    cron_id, run = await _cron_run(client, world, "report")
    err, out = await _report(tc, run)
    assert not err, out
    await _finish(world.manager.id, run)
    [cr] = await _cron_runs(cron_id)
    assert cr.panel is None and cr.status == "done"


async def test_get_panel_guide(client, db, world, tc_factory):
    tc = tc_factory(lifespan=True)
    _, run = await _cron_run(client, world, "report")
    err, out = _tool(tc, await _run_token(run), "get_panel_guide")
    assert not err, out
    assert set(out["catalog"]["components"]) == PANEL_COMPONENTS
    assert out["example"] == EXAMPLE
