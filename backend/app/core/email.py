from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.crypto import decrypt
from app.core.db import DbSession
from app.org.models import ORG_SETTINGS_ID, OrgSettings


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, org: OrgSettings):
        self._org = org

    async def send(self, to: str, subject: str, body: str) -> None:
        org = self._org
        msg = EmailMessage()
        msg["From"] = org.smtp_from or org.smtp_user or "megoocolab@localhost"
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        await aiosmtplib.send(
            msg,
            hostname=org.smtp_host,
            port=org.smtp_port or 587,
            username=org.smtp_user or None,
            password=decrypt(org.smtp_password_enc) if org.smtp_password_enc else None,
            start_tls=org.smtp_tls,
            timeout=15,
        )


class OutboxMailer:
    """Collects messages instead of sending them (tests, previews)."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


async def get_mailer(db: DbSession) -> Mailer | None:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is None or not org.smtp_host:
        return None
    return SmtpMailer(org)
