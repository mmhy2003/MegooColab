"""The one template every MegooColab email uses: a plain-text part, and an HTML part in the app's look.

The HTML is a dark brand bar (the logo and MEGOOCOLAB, the organization's name on the right), a white card with a
coloured tag, a heading, the message, an optional box (a task's key and title, or a notice), a cyan button with the
raw link under it, a note, and a footer saying why the email came. Styles are inline, as mail apps need; a mail app
in dark mode that honours prefers-color-scheme gets the card dark too. Everything people or agents wrote is escaped.
"""

from dataclasses import dataclass, field
from html import escape

from app.core.config import get_settings

# the app's colours (frontend/src/app/globals.css): light, and dark for mail apps in dark mode
TONES = {
    "violet": ("#6d28d9", "#c084fc"),
    "pink": ("#d4004f", "#ff3d81"),
    "amber": ("#a16207", "#ffe14d"),
    "cyan": ("#007a8f", "#22e4ff"),
    "green": ("#1a7a27", "#5bff9a"),
}
FONT = "Geist,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
DISPLAY = "Orbitron,Geist,-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"


@dataclass(frozen=True)
class Email:
    tag: str  # "Invitation", "Needs you", …
    tone: str  # a key of TONES
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    box: tuple[str | None, str] | None = None  # (a task's key, or None; the text)
    box_tone: str = "cyan"
    button: tuple[str, str] | None = None  # (label, absolute url)
    note: str | None = None
    footer: str = ""
    footer_link: tuple[str, str] | None = None  # (label, absolute url)


def render(email: Email, *, org: str | None) -> tuple[str, str]:
    """(plain text, HTML) of one email."""
    return _text(email), _html(email, org)


def _text(e: Email) -> str:
    parts = [e.heading]
    parts += e.paragraphs
    if e.box:
        key, text = e.box
        parts.append(f"{key} · {text}" if key else text)
    if e.button:
        parts.append(f"{e.button[0]}: {e.button[1]}")
    if e.note:
        parts.append(e.note)
    footer = e.footer
    if e.footer_link:
        footer = f"{footer}\n{e.footer_link[0]}: {e.footer_link[1]}".strip()
    if footer:
        parts.append(f"--\n{footer}")
    return "\n\n".join(parts) + "\n"


def _html(e: Email, org: str | None) -> str:
    tone, tone_dark = TONES.get(e.tone, TONES["cyan"])
    box_tone, box_tone_dark = TONES.get(e.box_tone, TONES["cyan"])
    logo = f"{get_settings().public_url}/logo.png"
    paragraphs = "".join(
        f'<p style="margin:0 0 12px;font-size:14px;line-height:1.6;color:#2a1d52" class="mc-text">{escape(p)}</p>'
        for p in e.paragraphs
    )
    box = ""
    if e.box:
        key, text = e.box
        chip = (f'<span class="mc-chip" style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;'
                f'color:#6b5f99;border:1px solid #d6ccf5;border-radius:4px;padding:0 4px;margin-right:6px;'
                f'background:#ffffff">{escape(key)}</span>') if key else ""
        box = (f'<div class="mc-box" style="background:#f6f3ff;border:1px solid #ece6ff;border-left:3px solid {box_tone};'
               f'border-radius:0 6px 6px 0;padding:10px 12px;margin:0 0 16px;font-size:13.5px;line-height:1.5;'
               f'color:#2a1d52" data-dark-edge="{box_tone_dark}">{chip}{escape(text)}</div>')
    button = ""
    if e.button:
        label, url = e.button
        button = (
            f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 0"><tr>'
            f'<td class="mc-btn" style="background:#0090a8;border-radius:6px">'
            f'<a href="{escape(url, quote=True)}" class="mc-btn-a" style="display:inline-block;padding:11px 18px;'
            f'font-family:{DISPLAY};font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;font-weight:600;'
            f'color:#ffffff;text-decoration:none">{escape(label)}</a></td></tr></table>'
            f'<p style="margin:14px 0 0;font-size:12px;line-height:1.5;color:#6b5f99;word-break:break-all" class="mc-muted">'
            f'Or open this link: <a href="{escape(url, quote=True)}" style="color:#007a8f" class="mc-link">'
            f'{escape(url)}</a></p>'
        )
    note = (f'<p style="margin:12px 0 0;font-size:12.5px;line-height:1.5;color:#6b5f99" class="mc-muted">'
            f'{escape(e.note)}</p>') if e.note else ""
    footer_link = (f'<br><a href="{escape(e.footer_link[1], quote=True)}" style="color:#007a8f" class="mc-link">'
                   f'{escape(e.footer_link[0])}</a>') if e.footer_link else ""
    org_cell = (f'<td align="right" style="font-family:{FONT};font-size:11.5px;color:#8e94a3">{escape(org)}</td>'
                if org else "<td></td>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">
<title>{escape(e.heading)}</title>
<style>
@media (prefers-color-scheme: dark) {{
  .mc-page {{ background:#0e0f13 !important; }}
  .mc-card {{ background:#17191f !important; border-color:#2a2d36 !important; }}
  .mc-heading {{ color:#eceef3 !important; }}
  .mc-text {{ color:#c9ccd6 !important; }}
  .mc-muted {{ color:#8e94a3 !important; }}
  .mc-link {{ color:#22e4ff !important; }}
  .mc-box {{ background:#121318 !important; border-color:#2a2d36 !important; color:#c9ccd6 !important; }}
  .mc-chip {{ background:#17191f !important; border-color:#2a2d36 !important; color:#8e94a3 !important; }}
  .mc-btn {{ background:#22e4ff !important; }}
  .mc-btn-a {{ color:#0e0f13 !important; }}
  .mc-tag {{ color:{tone_dark} !important; border-color:{tone_dark} !important; }}
}}
</style></head>
<body style="margin:0;padding:0;background:#f6f3ff" class="mc-page">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="mc-page"
 style="background:#f6f3ff"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px">
<tr><td style="background:#0e0f13;border-radius:10px 10px 0 0;padding:14px 22px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
<td width="38" style="padding-right:8px"><img src="{escape(logo, quote=True)}" width="30" height="30" alt=""
 style="display:block;border:0"></td>
<td style="font-family:{DISPLAY};font-weight:700;letter-spacing:.14em;font-size:13px;color:#22e4ff">MEGOOCOLAB</td>
{org_cell}</tr></table></td></tr>
<tr><td class="mc-card" style="background:#ffffff;border:1px solid #d6ccf5;border-top:0;border-radius:0 0 10px 10px;
 padding:24px 22px 22px;font-family:{FONT}">
<span class="mc-tag" style="display:inline-block;font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
 font-weight:600;border-radius:4px;padding:2px 7px;margin-bottom:10px;color:{tone};border:1px solid {tone}">{escape(e.tag)}</span>
<h1 class="mc-heading" style="margin:0 0 10px;font-size:19px;line-height:1.35;font-weight:600;color:#1a0b3d">{escape(e.heading)}</h1>
{paragraphs}{box}{button}{note}
</td></tr>
<tr><td style="padding:14px 22px 2px;font-family:{FONT};font-size:11.5px;line-height:1.55;color:#6b5f99;
 text-align:center" class="mc-muted">{escape(e.footer)}{footer_link}</td></tr>
</table></td></tr></table>
</body></html>
"""
