"""Cron run panels: the agent's tiles and charts kept with a run (MC-174)."""

import importlib.util
import json
from pathlib import Path

from sqlalchemy import text

from app.a2ui import service
from app.core.db import SessionLocal
from app.crons.models import CronRun
from tests.crons.test_report import BASE, _cron_run, _cron_runs

EXAMPLE = json.loads((Path(service.__file__).parent / "panel_example.json").read_text())


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
