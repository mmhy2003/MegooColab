from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.crons.schedule import check, describe, next_times
from tests.factories import login, make_user


def _refused(expr: str, tz: str = "UTC") -> dict:
    with pytest.raises(HTTPException) as e:
        check(expr, tz)
    assert e.value.status_code == 422
    return e.value.detail


@pytest.mark.parametrize("expr", ["0 2 * * *", "0 16 * * FRI", "*/15 9-17 * * MON-FRI", "0 0 1 * *", "0 9 1,15 JAN-JUN *"])
def test_valid_expressions_pass(expr):
    check(expr, "Africa/Cairo")


def test_invalid_expressions_name_the_field():
    assert "Hour must be 0–23" in _refused("0 25 * * *")["message"]
    assert "Minute must be 0–59" in _refused("61 2 * * *")["message"]
    assert "Use five fields" in _refused("0 2 * *")["message"]
    assert _refused("@daily")["code"] == "schedule_invalid"
    assert _refused("0 2 * * *", "Mars/Olympus")["code"] == "timezone_invalid"


def test_too_frequent():
    assert _refused("* * * * *")["code"] == "schedule_too_frequent"
    assert _refused("*/2 * * * *")["code"] == "schedule_too_frequent"
    check("*/5 * * * *", "UTC")


def test_describe():
    assert describe("0 2 * * *") == "At 02:00"
    assert describe("0 16 * * FRI") == "At 16:00, only on Friday"
    assert describe("0 9 * * 1-5") == "At 09:00, Monday through Friday"


def test_next_times_in_zone():
    after = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    first = next_times("0 2 * * *", "Africa/Cairo", after, 3)
    assert first[0] == datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    assert len(first) == 3 and all(t.tzinfo is not None for t in first)


def test_dst_spring_forward_skips_and_fall_back_runs_once():
    spring = next_times("30 2 * * *", "Europe/Berlin", datetime(2026, 3, 28, 12, tzinfo=UTC), 2)
    assert [t.date().isoformat() for t in spring] == ["2026-03-30", "2026-03-31"]  # no 29 March: 02:30 never happens
    autumn = next_times("30 2 * * *", "Europe/Berlin", datetime(2026, 10, 24, 12, tzinfo=UTC), 2)
    assert [t.date().isoformat() for t in autumn] == ["2026-10-25", "2026-10-26"]  # 25 October once


async def test_preview_endpoint(client, db):
    await login(client, await make_user(db))
    bad = (await client.post("/api/crons/preview", json={"schedule": "0 25 * * *", "timezone": "UTC"})).json()
    assert bad["ok"] is False and "Hour must be 0–23" in bad["error"] and bad["next"] == []
    good = (await client.post("/api/crons/preview", json={"schedule": "0 2 * * *", "timezone": "UTC"})).json()
    assert good["ok"] is True and good["description"] == "At 02:00" and len(good["next"]) == 3
