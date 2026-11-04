import uuid

from fastapi import APIRouter, Response, status

from app.auth.deps import AuthedUser
from app.core.db import DbSession
from app.kb_drafts import service
from app.kb_drafts.schemas import AgentChoice, DraftAgentOut, DraftEdit, DraftIn, DraftOut, DraftSummary

router = APIRouter(prefix="/api/kb/drafts", tags=["kb-drafts"])


@router.get("/agents")
async def list_agents(space_id: uuid.UUID, user: AuthedUser, db: DbSession) -> list[DraftAgentOut]:
    return await service.list_agents(db, user, space_id)


@router.get("")
async def my_drafts(user: AuthedUser, db: DbSession) -> list[DraftSummary]:
    return await service.my_drafts(db, user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def start_draft(body: DraftIn, user: AuthedUser, db: DbSession, response: Response) -> DraftOut:
    draft, created = await service.start_draft(db, user, body)
    await db.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return await service.draft_out(db, draft)


@router.get("/{draft_id}")
async def get_draft(draft_id: uuid.UUID, user: AuthedUser, db: DbSession) -> DraftOut:
    return await service.draft_out(db, await service.get_draft_for(db, user, draft_id))


@router.put("/{draft_id}")
async def edit_draft(draft_id: uuid.UUID, body: DraftEdit, user: AuthedUser, db: DbSession) -> DraftOut:
    draft = await service.get_draft_for(db, user, draft_id, lock=True)
    await service.edit(db, draft, title=body.title, body=body.body_md)
    await db.commit()
    return await service.draft_out(db, draft)


@router.post("/{draft_id}/settle")
async def settle(draft_id: uuid.UUID, user: AuthedUser, db: DbSession) -> DraftOut:
    draft = await service.get_draft_for(db, user, draft_id, lock=True)
    service.settle(draft)
    await service.touch(db, draft)
    await db.commit()
    return await service.draft_out(db, draft)


@router.post("/{draft_id}/marks/{mark_id}/keep")
async def keep_mark(draft_id: uuid.UUID, mark_id: int, user: AuthedUser, db: DbSession) -> DraftOut:
    draft = await service.get_draft_for(db, user, draft_id, lock=True)
    await service.set_mark(db, draft, mark_id, "kept")
    await db.commit()
    return await service.draft_out(db, draft)


@router.post("/{draft_id}/marks/{mark_id}/undo")
async def undo_mark(draft_id: uuid.UUID, mark_id: int, user: AuthedUser, db: DbSession) -> DraftOut:
    draft = await service.get_draft_for(db, user, draft_id, lock=True)
    await service.set_mark(db, draft, mark_id, "undone")
    await db.commit()
    return await service.draft_out(db, draft)


@router.post("/{draft_id}/keep-all")
async def keep_all(draft_id: uuid.UUID, user: AuthedUser, db: DbSession) -> DraftOut:
    draft = await service.get_draft_for(db, user, draft_id, lock=True)
    await service.set_all(db, draft, "kept")
    await db.commit()
    return await service.draft_out(db, draft)


@router.post("/{draft_id}/undo-all")
async def undo_all(draft_id: uuid.UUID, user: AuthedUser, db: DbSession) -> DraftOut:
    draft = await service.get_draft_for(db, user, draft_id, lock=True)
    await service.set_all(db, draft, "undone")
    await db.commit()
    return await service.draft_out(db, draft)


@router.patch("/{draft_id}/agent")
async def change_agent(draft_id: uuid.UUID, body: AgentChoice, user: AuthedUser, db: DbSession) -> DraftOut:
    draft = await service.get_draft_for(db, user, draft_id, lock=True)
    await service.change_agent(db, user, draft, body.agent_id)
    await db.commit()
    return await service.draft_out(db, draft)


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard(draft_id: uuid.UUID, user: AuthedUser, db: DbSession) -> Response:
    draft = await service.get_draft_for(db, user, draft_id, lock=True)
    await service.discard(db, draft)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
