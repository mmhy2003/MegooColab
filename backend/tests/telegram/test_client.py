"""The Telegram client: what it sends, and how Telegram's errors come back (never with the bot token in them)."""

import json

import httpx
import pytest

from app.telegram.client import HttpTelegramClient, TelegramError

TOKEN = "123:ABC"


def _client(handler) -> HttpTelegramClient:
    return HttpTelegramClient(transport=httpx.MockTransport(handler))


async def test_send_message_posts_html_with_a_button():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    client = _client(handler)
    await client.send_message(TOKEN, 5001, "<b>Hi</b>", "https://megoo.example.com/x")
    await client.send_message(TOKEN, 5001, "plain", None)
    assert seen[0].url.path == f"/bot{TOKEN}/sendMessage"
    assert json.loads(seen[0].content) == {
        "chat_id": 5001, "text": "<b>Hi</b>", "parse_mode": "HTML", "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": [[{"text": "Open in MegooColab", "url": "https://megoo.example.com/x"}]]},
    }
    assert "reply_markup" not in json.loads(seen[1].content)


async def test_telegram_errors_carry_status_and_retry_after():
    client = _client(lambda _r: httpx.Response(429, json={
        "ok": False, "error_code": 429, "description": "Too Many Requests: retry after 7", "parameters": {"retry_after": 7},
    }))
    with pytest.raises(TelegramError) as caught:
        await client.send_message(TOKEN, 1, "x", None)
    assert (caught.value.status, caught.value.retry_after) == (429, 7)
    assert "Too Many Requests" in caught.value.description


async def test_get_me_and_get_updates_return_results():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 42, "username": "megoo_bot"}})
        assert json.loads(request.content) == {"offset": 12, "timeout": 25, "allowed_updates": ["message"]}
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 12}]})

    client = _client(handler)
    assert (await client.get_me(TOKEN))["username"] == "megoo_bot"
    assert await client.get_updates(TOKEN, 12, 25) == [{"update_id": 12}]


async def test_errors_never_carry_the_token():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    with pytest.raises(TelegramError) as caught:
        await _client(handler).get_me(TOKEN)
    assert caught.value.status == 0
    assert TOKEN not in str(caught.value) and TOKEN not in caught.value.description
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
