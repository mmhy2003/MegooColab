from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from app.core.crypto import decrypt
from app.core.db import DbSession
from app.org.models import ORG_SETTINGS_ID, OrgSettings


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> None: ...


def one_line(value: str) -> str:
    """A header value never breaks its line: a newline in it (a user's name, say) would end or inject a header."""
    return " ".join(value.split())


class SmtpMailer:
    def __init__(self, org: OrgSettings):
        self._org = org

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        org = self._org
        msg = EmailMessage()
        msg["From"] = org.smtp_from or org.smtp_user or "megoocolab@localhost"
        msg["To"] = one_line(to)
        msg["Subject"] = one_line(subject)
        msg.set_content(body)
        if html:  # the app's look, with the plain text for mail apps that don't show HTML
            msg.add_alternative(html, subtype="html")
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
        self.html: list[str | None] = []  # each message's HTML part, beside `sent`

    async def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        self.sent.append((to, subject, body))
        self.html.append(html)


async def org_name(db) -> str | None:
    """The organization's name, for the email's brand bar (None before setup)."""
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    return org.name if org else None


async def get_mailer(db: DbSession) -> Mailer | None:
    org = await db.get(OrgSettings, ORG_SETTINGS_ID)
    if org is None or not org.smtp_host:
        return None
    return SmtpMailer(org)
