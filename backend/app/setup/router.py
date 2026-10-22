from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import service as audit
from app.auth.models import Role, User, UserStatus
from app.auth.schemas import LowerEmail, Password, UserEnvelope, UserOut
from app.core.db import DbSession
from app.core.security import hash_password
from app.org.models import OrgSettings

router = APIRouter(prefix="/api/setup", tags=["setup"])

SETUP_LOCK_ID = 7340001


class SetupIn(BaseModel):
    org_name: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: LowerEmail
    password: Password


async def _user_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


@router.get("/status")
async def setup_status(db: DbSession) -> dict[str, bool]:
    return {"needs_setup": await _user_count(db) == 0}


@router.post("", status_code=status.HTTP_201_CREATED)
async def run_setup(body: SetupIn, db: DbSession) -> UserEnvelope:
    # serialize concurrent setup attempts; only the first may create the admin
    await db.execute(text(f"SELECT pg_advisory_xact_lock({SETUP_LOCK_ID})"))
    if await _user_count(db) > 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "already_set_up")
    user = User(
        email=body.email,
        name=body.name,
        role=Role.admin,
        status=UserStatus.active,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.add(OrgSettings(name=body.org_name))
    await db.flush()
    await audit.record(
        db, "setup.completed", actor_id=user.id, target_type="user", target_id=user.id
    )
    return UserEnvelope(user=UserOut.model_validate(user))
