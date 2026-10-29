"""The update check: the newest MegooColab (vX.Y.Z) and runner (runner-vX.Y.Z) releases on GitHub, kept in the
org settings for the update notices. Every 6 hours and when the worker starts; UPDATE_CHECK=false turns it off."""

import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.jobs import queue
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.updates.versions import parse

log = logging.getLogger(__name__)

RELEASES_URL = "https://api.github.com/repos/mmhy2003/MegooColab/releases?per_page=100"
CHECK_SECONDS = 6 * 3600
APP_TAG, RUNNER_TAG = "v", "runner-v"

Latest = tuple[str, str] | None  # (version, release page URL)


async def fetch_releases() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(RELEASES_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "MegooColab"})
        r.raise_for_status()
        return r.json()


def pick_latest(releases: list[dict]) -> tuple[Latest, Latest]:
    """The newest published release of each product; drafts, pre-releases and other tags are skipped."""
    found: dict[str, tuple[tuple[int, int, int], str, str]] = {}
    for rel in releases:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        tag = str(rel.get("tag_name", ""))
        for product, prefix in (("app", APP_TAG), ("runner", RUNNER_TAG)):
            version = tag.removeprefix(prefix)
            key = parse(version) if tag.startswith(prefix) else None
            if key is not None and (product not in found or key > found[product][0]):
                found[product] = (key, version, str(rel.get("html_url", "")))
    app, runner = found.get("app"), found.get("runner")
    return (app[1:] if app else None), (runner[1:] if runner else None)


@queue.register("updates.check")
async def check_updates(db: AsyncSession, payload: dict) -> None:
    if not get_settings().update_check:
        return
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is None:  # not set up yet: the next check stores them
        return
    try:
        app, runner = pick_latest(await fetch_releases())
    except Exception as exc:  # noqa: BLE001 - offline, rate-limited or a changed API: keep what we had
        log.warning("update check failed: %s", exc)
        return
    if app:
        org.latest_app_version, org.latest_app_url = app
    if runner:
        org.latest_runner_version, org.latest_runner_url = runner
    org.updates_checked_at = datetime.now(UTC)


queue.register_periodic("updates.check", CHECK_SECONDS)
