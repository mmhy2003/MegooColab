import pytest

from app.org.models import ORG_SETTINGS_ID, OrgSettings


@pytest.fixture(autouse=True)
async def _org(db):
    """A set-up server: the VAPID keys live on its settings row."""
    if await db.get(OrgSettings, ORG_SETTINGS_ID) is None:
        db.add(OrgSettings(id=ORG_SETTINGS_ID, name="Acme"))
        await db.commit()
