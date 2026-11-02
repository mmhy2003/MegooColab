from fastapi import APIRouter, Response, status

from app.auth.deps import AdminUser, AuthedUser
from app.core.db import DbSession
from app.telegram import service
from app.telegram.schemas import (
    MyTelegramOut,
    TelegramBotIn,
    TelegramBotOut,
    TelegramLinkUrl,
)

router = APIRouter(tags=["telegram"])


@router.get("/api/admin/telegram")
async def get_bot(_admin: AdminUser, db: DbSession) -> TelegramBotOut:
    return TelegramBotOut(bot_username=await service.bot_username(db))


@router.put("/api/admin/telegram")
async def put_bot(body: TelegramBotIn, admin: AdminUser, db: DbSession) -> TelegramBotOut:
    return TelegramBotOut(bot_username=await service.set_bot(db, admin.id, body.token))


@router.delete("/api/admin/telegram", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(admin: AdminUser, db: DbSession) -> Response:
    await service.remove_bot(db, admin.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/me/telegram")
async def my_telegram(user: AuthedUser, db: DbSession) -> MyTelegramOut:
    username = await service.bot_username(db)
    return MyTelegramOut(available=username is not None, bot_username=username,
                         linked=username is not None and await service.is_linked(db, user.id))


@router.post("/api/me/telegram/link")
async def make_link(user: AuthedUser, db: DbSession) -> TelegramLinkUrl:
    return TelegramLinkUrl(url=await service.link_url(db, user.id))


@router.delete("/api/me/telegram", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(user: AuthedUser, db: DbSession) -> Response:
    await service.unlink(db, user.id, reason="disconnected", actor_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
