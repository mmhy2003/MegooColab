"""What a Telegram notification says, and whether it can carry an "Open in MegooColab" button."""

import html
import ipaddress
from urllib.parse import urlsplit


def message_text(title: str, body: str, url_text: str | None) -> str:
    """The title in bold and the body under it, escaped for Telegram's HTML; the address at the end when there is
    no button to carry it."""
    text = f"<b>{html.escape(title, quote=False)}</b>\n{html.escape(body, quote=False)}"
    return f"{text}\n{url_text}" if url_text else text


def full_url(public_url: str, link: str) -> str:
    return public_url.rstrip("/") + link


def button_url(public_url: str, link: str) -> str | None:
    """The button's address, or None when Telegram could not open it: only https on a public host does."""
    parts = urlsplit(public_url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or host == "localhost" or host.endswith(".localhost"):
        return None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return full_url(public_url, link) if "." in host else None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
        return None
    return full_url(public_url, link)
