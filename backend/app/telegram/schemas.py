from pydantic import BaseModel, Field

from app.core.text import NoNulStr


class TelegramBotOut(BaseModel):
    bot_username: str | None  # None: no bot set


class TelegramBotIn(BaseModel):
    token: NoNulStr = Field(min_length=1, max_length=200)


class MyTelegramOut(BaseModel):
    available: bool  # the site has a bot
    bot_username: str | None
    linked: bool


class TelegramLinkUrl(BaseModel):
    url: str
