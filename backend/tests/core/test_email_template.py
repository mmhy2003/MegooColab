"""The one email template every MegooColab email uses: a plain-text part and an HTML part in the app's look."""

from app.core.config import get_settings
from app.core.email import OutboxMailer, SmtpMailer
from app.core.email_template import Email, render
from app.org.models import OrgSettings


def _email(**kw) -> Email:
    base = dict(tag="Invitation", tone="violet", heading="Ahmed invited you to Acme",
                paragraphs=["Join your team on MegooColab."], button=("Accept the invitation", "https://x.io/invite/t"),
                note="The link works once and expires in 7 days.", footer="You got this because an admin invited you.")
    return Email(**{**base, **kw})


def test_render_gives_text_and_html_with_the_same_content():
    text, html = render(_email(), org="Acme")
    for part in ("Ahmed invited you to Acme", "Join your team on MegooColab.", "https://x.io/invite/t",
                 "The link works once and expires in 7 days.", "You got this because an admin invited you."):
        assert part in text and part in html
    assert "Accept the invitation: https://x.io/invite/t" in text
    assert 'href="https://x.io/invite/t"' in html and ">Accept the invitation<" in html
    assert f'src="{get_settings().public_url}/logo.png"' in html and "MEGOOCOLAB" in html and "Acme" in html
    assert ">Invitation<" in html and "#6d28d9" in html  # the violet tag
    assert "prefers-color-scheme: dark" in html


def test_render_escapes_what_people_and_agents_wrote():
    text, html = render(_email(heading="<script>x()</script> & co", box=("PAY-1", "<b>bold</b>")), org="<i>Org</i>")
    assert "<script>" not in html and "&lt;script&gt;" in html and "&amp; co" in html
    assert "<b>bold</b>" not in html and "<i>Org</i>" not in html
    assert "<script>x()</script> & co" in text and "PAY-1 · <b>bold</b>" in text  # text stays as written


def test_render_footer_link_and_no_button():
    text, html = render(_email(button=None, footer_link=("Change which emails you get", "https://x.io/s")), org=None)
    assert "Change which emails you get: https://x.io/s" in text and 'href="https://x.io/s"' in html
    assert "Accept the invitation" not in html


async def test_smtp_sends_text_with_an_html_alternative(monkeypatch):
    sent = []

    async def fake_send(msg, **_kw):
        sent.append(msg)

    monkeypatch.setattr("app.core.email.aiosmtplib.send", fake_send)
    mailer = SmtpMailer(OrgSettings(smtp_host="mail.example", smtp_from="m@example"))
    await mailer.send("u@example", "Hi", "plain body", html="<p>html body</p>")
    msg = sent[0]
    assert msg.get_content_type() == "multipart/alternative"
    parts = {p.get_content_type(): p.get_content() for p in msg.iter_parts()}
    assert "plain body" in parts["text/plain"] and "<p>html body</p>" in parts["text/html"]
    await mailer.send("u@example", "Hi", "plain only")
    assert sent[1].get_content_type() == "text/plain"


async def test_outbox_keeps_the_html_beside_each_message():
    box = OutboxMailer()
    await box.send("a@x.io", "S", "B", html="<p>H</p>")
    assert box.sent == [("a@x.io", "S", "B")] and box.html == ["<p>H</p>"]
