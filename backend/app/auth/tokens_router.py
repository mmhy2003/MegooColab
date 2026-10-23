import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.audit import service as audit
from app.auth import tokens
from app.auth.deps import AuthedUser
from app.auth.models import PersonalAccessToken, TokenScope
from app.auth.service import now
from app.core.db import DbSession

router = APIRouter(prefix="/api/tokens", tags=["tokens"])


class TokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[TokenScope]
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


class CreateTokenIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    scopes: Annotated[list[TokenScope], Field(min_length=1)]
    expires_in_days: Annotated[int, Field(ge=1, le=3650)] | None = None


class CreatedTokenOut(BaseModel):
    token: TokenOut
    secret: str


@router.get("")
async def list_tokens(user: AuthedUser, db: DbSession) -> list[TokenOut]:
    rows = (
        await db.execute(
            select(PersonalAccessToken)
            .where(PersonalAccessToken.user_id == user.id)
            .order_by(PersonalAccessToken.created_at.desc())
        )
    ).scalars()
    return [TokenOut.model_validate(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_token(body: CreateTokenIn, user: AuthedUser, db: DbSession) -> CreatedTokenOut:
    expires_at = now() + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    scopes = list(dict.fromkeys(body.scopes))
    row, secret = await tokens.create_token(db, user, body.name.strip(), scopes, expires_at)
    await db.refresh(row)
    await audit.record(
        db,
        "token.created",
        actor_id=user.id,
        target_type="token",
        target_id=row.id,
        data={"name": row.name, "scopes": row.scopes},
    )
    return CreatedTokenOut(token=TokenOut.model_validate(row), secret=secret)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(token_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    row = await db.get(PersonalAccessToken, token_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "token_not_found")
    await tokens.revoke_token(db, row)
    await audit.record(db, "token.revoked", actor_id=user.id, target_type="token", target_id=row.id)
