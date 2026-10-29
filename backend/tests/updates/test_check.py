"""The worker learns the latest MegooColab and runner versions from GitHub's releases."""

import httpx
import pytest

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.updates import check
from app.updates.versions import is_newer, parse

URL = "https://github.com/mmhy2003/MegooColab/releases/tag/"


def _release(tag: str, *, draft: bool = False, prerelease: bool = False) -> dict:
    return {"tag_name": tag, "html_url": URL + tag, "draft": draft, "prerelease": prerelease}


RELEASES = [
    _release("v0.1.0"),
    _release("v0.2.0", draft=True),
    _release("v0.1.5"),
    _release("runner-v0.2.0-rc1"),
    _release("runner-v0.3.0", prerelease=True),
    _release("runner-v0.1.1"),
    _release("v1.0"),
    _release("docs-v9.0.0"),
]


def test_versions_compare_part_by_part():
    assert is_newer("0.10.0", "0.9.0")
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("0.2.0", "dev")  # run from source: never "out of date"
    assert not is_newer(None, "0.1.0")
    assert not is_newer("0.2.0", "0.1.0-dev+abc")
    assert parse("v0.2.0") == (0, 2, 0)


def test_the_newest_release_of_each_product():
    assert check.pick_latest(RELEASES) == (("0.1.5", URL + "v0.1.5"), ("0.1.1", URL + "runner-v0.1.1"))


async def _org(db) -> OrgSettings:
    return await db.get(OrgSettings, ORG_SETTINGS_ID, populate_existing=True)


async def _run_check() -> None:
    async with SessionLocal() as s:
        await check.check_updates(s, {})
        await s.commit()


@pytest.fixture
async def org(db):
    db.add(OrgSettings(id=ORG_SETTINGS_ID, name="Acme"))
    await db.commit()


async def test_the_check_stores_the_latest_versions(db, org, monkeypatch):
    async def releases():
        return RELEASES

    monkeypatch.setattr(check, "fetch_releases", releases)
    await _run_check()
    o = await _org(db)
    assert (o.latest_app_version, o.latest_app_url) == ("0.1.5", URL + "v0.1.5")
    assert (o.latest_runner_version, o.latest_runner_url) == ("0.1.1", URL + "runner-v0.1.1")
    assert o.updates_checked_at is not None


@pytest.mark.parametrize("error", [
    httpx.ConnectError("offline"),
    httpx.HTTPStatusError("rate limited", request=httpx.Request("GET", check.RELEASES_URL),
                          response=httpx.Response(403)),
    ValueError("not json"),
])
async def test_a_failed_check_keeps_what_was_stored(db, org, monkeypatch, error):
    o = await _org(db)
    o.latest_app_version, o.latest_runner_version = "0.1.0", "0.1.0"
    await db.commit()

    async def broken():
        raise error

    monkeypatch.setattr(check, "fetch_releases", broken)
    await _run_check()
    o = await _org(db)
    assert (o.latest_app_version, o.latest_runner_version, o.updates_checked_at) == ("0.1.0", "0.1.0", None)


async def test_the_check_can_be_turned_off(db, org, monkeypatch):
    async def never():
        raise AssertionError("GitHub was asked")

    monkeypatch.setattr(check, "fetch_releases", never)
    monkeypatch.setattr(get_settings(), "update_check", False)
    await _run_check()
    assert (await _org(db)).updates_checked_at is None


async def test_the_worker_checks_when_it_starts(db):
    from sqlalchemy import select

    from app.jobs.models import Job
    from app.worker import HANDLER_MODULES, enqueue_startup_jobs

    assert "app.updates.check" in HANDLER_MODULES
    await enqueue_startup_jobs()
    assert [j.kind for j in (await db.execute(select(Job))).scalars()] == ["updates.check"]
