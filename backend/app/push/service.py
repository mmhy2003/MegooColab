import re
import uuid
from urllib.parse import urlsplit

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.push.models import PushSubscription

# order matters: Edge says Chrome and Safari too, Chrome says Safari, iPad and iPhone say "like Mac OS X"
_BROWSERS = (("Edge", r"Edg(e|A|iOS)?/"), ("Firefox", r"Firefox/|FxiOS/"), ("Chrome", r"Chrome/|CriOS/"),
             ("Safari", r"Safari/"))
_SYSTEMS = (("iPhone", r"iPhone"), ("iPad", r"iPad"), ("Android", r"Android"), ("Windows", r"Windows"),
            ("macOS", r"Mac OS X|Macintosh"), ("Linux", r"Linux|X11"))


# the browsers' push services: the worker POSTs to a registered endpoint, so nothing else may be registered
_PUSH_HOSTS = ("fcm.googleapis.com", "web.push.apple.com")  # Chrome, Edge (Android), Brave, Samsung...; Safari
_PUSH_SUFFIXES = (".push.services.mozilla.com", ".push.apple.com", ".notify.windows.com")  # Firefox; Safari; Edge
MAX_DEVICES = 10


def is_push_service(endpoint: str) -> bool:
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        return False
    host = (url.hostname or "").lower()
    return (
        url.scheme == "https" and url.username is None and port in (None, 443)
        and (host in _PUSH_HOSTS or host.endswith(_PUSH_SUFFIXES))
    )


def device_name(user_agent: str | None) -> str:
    """'{Browser} on {OS}' for the device list, e.g. 'Chrome on Windows'."""
    ua = user_agent or ""
    browser = next((name for name, pattern in _BROWSERS if re.search(pattern, ua)), "Browser")
    system = next((name for name, pattern in _SYSTEMS if re.search(pattern, ua)), "this device")
    return f"{browser} on {system}"


async def delete_user_subscriptions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Account recovery or deactivation: none of this person's devices gets their notifications any more."""
    await db.execute(delete(PushSubscription).where(PushSubscription.user_id == user_id))
