import uuid

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import AuthedUser
from app.auth.models import User
from app.core.db import DbSession
from app.hub import machines
from app.hub.models import HubPrefs
from app.hub.schemas import MachineOut, PrefsIn, PrefsOut, PushIn

machines_router = APIRouter(prefix="/api/hub", tags=["hub"])


@machines_router.get("/machines")
async def list_machines(user: AuthedUser, db: DbSession) -> list[MachineOut]:
    return [await machines.machine_out(db, user, t) for t in await machines.my_machines(db, user)]


@machines_router.get("/machines/summary")
async def machines_summary(user: AuthedUser, db: DbSession) -> dict[str, bool]:
    out = [await machines.machine_out(db, user, t) for t in await machines.my_machines(db, user)]
    return {"out_of_step": any(m.out_of_step for m in out)}


@machines_router.post("/machines/{token_id}/push")
async def push_machine(token_id: uuid.UUID, body: PushIn, user: AuthedUser, db: DbSession) -> MachineOut:
    token = await machines.machine_or_404(db, user, token_id)
    await machines.push(db, user, token, body.tool_ids, body.take_over)
    return await machines.machine_out(db, user, token)


async def _prefs(db: AsyncSession, user: User) -> HubPrefs:
    prefs = await db.get(HubPrefs, user.id)
    if prefs is None:
        prefs = HubPrefs(user_id=user.id, auto_default=False)
        db.add(prefs)
        await db.flush()
    return prefs


@machines_router.get("/prefs")
async def get_prefs(user: AuthedUser, db: DbSession) -> PrefsOut:
    return PrefsOut(auto_default=(await _prefs(db, user)).auto_default)


@machines_router.put("/prefs")
async def put_prefs(body: PrefsIn, user: AuthedUser, db: DbSession) -> PrefsOut:
    prefs = await _prefs(db, user)
    prefs.auto_default = body.auto_default
    return PrefsOut(auto_default=prefs.auto_default)
