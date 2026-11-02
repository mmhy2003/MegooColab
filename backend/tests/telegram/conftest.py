"""A Telegram that only exists in the tests: it records what was asked of it and answers as each test scripts."""

import pytest

from app.org.models import ORG_SETTINGS_ID, OrgSettings
from app.telegram import client as telegram_client
from app.telegram.client import TelegramError


class FakeTelegram:
    def __init__(self):
        self.me: dict | Exception = {"id": 42, "username": "megoo_bot"}
        self.sent: list[dict] = []  # {token, chat_id, text, button_url}
        self.send_errors: list[Exception] = []  # raised by the next sends, in order
        self.updates: list[list[dict] | Exception] = []  # one entry per get_updates call
        self.update_calls: list[dict] = []

    async def get_me(self, token: str) -> dict:
        if isinstance(self.me, Exception):
            raise self.me
        return self.me

    async def send_message(self, token: str, chat_id: int, text: str, button_url: str | None) -> None:
        if self.send_errors:
            raise self.send_errors.pop(0)
        self.sent.append({"token": token, "chat_id": chat_id, "text": text, "button_url": button_url})

    async def get_updates(self, token: str, offset: int | None, timeout: int) -> list[dict]:
        self.update_calls.append({"token": token, "offset": offset, "timeout": timeout})
        if not self.updates:
            return []
        got = self.updates.pop(0)
        if isinstance(got, Exception):
            raise got
        return got


@pytest.fixture
def telegram():
    fake = FakeTelegram()
    telegram_client.override = fake
    yield fake
    telegram_client.override = None


@pytest.fixture
async def org(db) -> OrgSettings:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is None:
        org = OrgSettings(id=ORG_SETTINGS_ID, name="Acme")
        db.add(org)
        await db.commit()
    return org


__all__ = ["FakeTelegram", "TelegramError"]
