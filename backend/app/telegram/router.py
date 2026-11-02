from fastapi import APIRouter, Response, status

from app.auth.deps import AdminUser
from app.core.db import DbSession
from app.telegram import service
from app.telegram.schemas import TelegramBotIn, TelegramBotOut

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
