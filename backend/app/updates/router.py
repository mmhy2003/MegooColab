from fastapi import APIRouter

from app.auth.deps import AuthedUser
from app.auth.models import Role
from app.core.config import get_settings
from app.core.db import DbSession
from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.updates.schemas import AppUpdate, RunnerRelease, UpdatesOut
from app.updates.versions import is_newer

router = APIRouter(tags=["updates"])


@router.get("/api/updates")
async def get_updates(user: AuthedUser, db: DbSession) -> UpdatesOut:
    """The latest releases, as the update check last found them. The server's own update is for admins only:
    they are the ones who can install it."""
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is None:
        return UpdatesOut()
    current = get_settings().app_version
    app = None
    if user.role == Role.admin and org.latest_app_url and is_newer(org.latest_app_version, current):
        app = AppUpdate(current=current, latest=org.latest_app_version, url=org.latest_app_url)
    runner = None
    if org.latest_runner_version and org.latest_runner_url:
        runner = RunnerRelease(latest=org.latest_runner_version, url=org.latest_runner_url)
    return UpdatesOut(app=app, runner=runner)
