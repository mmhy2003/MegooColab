"""The server's own VAPID keys: made once, recovered when they can no longer be read (plan 18)."""

import uuid

from sqlalchemy import func, select

from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.push.keys import vapid_keys, vapid_subject
from app.push.models import PushSubscription
from tests.factories import make_user


async def test_key_generated_once(db):
    first = await vapid_keys(db)
    await db.commit()
    second = await vapid_keys(db)
    assert first.public_key == second.public_key
    assert len(first.public_key) == 87 and "=" not in first.public_key  # 65 bytes, base64url without padding
    assert first.private_key_pem.startswith("-----BEGIN PRIVATE KEY-----")


async def test_undecryptable_key_regenerates_and_clears_devices(db):
    old = await vapid_keys(db)
    user = await make_user(db)
    db.add(PushSubscription(user_id=user.id, endpoint=f"https://push.example.com/{uuid.uuid4()}", p256dh="k",
                            auth="a", name="Chrome on Windows"))
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    org.vapid_private_key_enc = "not-a-fernet-token"
    await db.commit()

    new = await vapid_keys(db)
    await db.commit()
    assert new.public_key != old.public_key
    assert await db.scalar(select(func.count()).select_from(PushSubscription)) == 0


def test_subject():
    assert vapid_subject("https://megoo.example.com", None) == "https://megoo.example.com"
    assert vapid_subject("http://localhost:8080", "ops@x.io") == "mailto:ops@x.io"
    assert vapid_subject("http://localhost:8080", None) == "mailto:megoocolab@localhost"
