"""Talking to Telegram's Bot API. Tests set `override`; nothing else calls Telegram.

The bot token is part of every URL, so no error raised from here carries the request or its URL: an error is only
Telegram's status, description and retry_after (status 0 when Telegram could not be reached).
"""

from typing import Any, Protocol

import httpx

API = "https://api.telegram.org"
BUTTON_TEXT = "Open in MegooColab"


class TelegramError(Exception):
    def __init__(self, status: int, description: str, retry_after: int | None = None):
        super().__init__(f"telegram {status}: {description}")
        self.status = status
        self.description = description
        self.retry_after = retry_after


class TelegramClient(Protocol):
    async def get_me(self, token: str) -> dict: ...

    async def send_message(self, token: str, chat_id: int, text: str, button_url: str | None) -> None: ...

    async def delete_webhook(self, token: str) -> None: ...

    async def get_updates(self, token: str, offset: int | None, timeout: int) -> list[dict]: ...


class HttpTelegramClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self._transport = transport

    async def _call(self, token: str, method: str, payload: dict[str, Any], *, wait: float = 0) -> Any:
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=wait + 10) as http:
                response = await http.post(f"{API}/bot{token}/{method}", json=payload)
            data = response.json()
        except (httpx.HTTPError, ValueError):
            # from None: the httpx error names the URL, and the URL holds the token
            raise TelegramError(0, f"could not reach Telegram ({method})") from None
        if not data.get("ok"):
            retry = (data.get("parameters") or {}).get("retry_after")
            raise TelegramError(int(data.get("error_code") or response.status_code),
                                str(data.get("description") or ""), int(retry) if retry is not None else None)
        return data.get("result")

    async def get_me(self, token: str) -> dict:
        return await self._call(token, "getMe", {})

    async def send_message(self, token: str, chat_id: int, text: str, button_url: str | None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": True}
        if button_url:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": BUTTON_TEXT, "url": button_url}]]}
        await self._call(token, "sendMessage", payload)

    async def delete_webhook(self, token: str) -> None:
        await self._call(token, "deleteWebhook", {})

    async def get_updates(self, token: str, offset: int | None, timeout: int) -> list[dict]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload = {"offset": offset, **payload}
        return await self._call(token, "getUpdates", payload, wait=timeout)


override: TelegramClient | None = None


def get_client() -> TelegramClient:
    return override if override is not None else HttpTelegramClient()
