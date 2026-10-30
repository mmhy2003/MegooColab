import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.auth.deps import AuthedUser, current_session
from app.core.db import DbSession
from app.push.keys import vapid_keys
from app.push.models import PushSubscription
from app.push.schemas import PushKeyOut, PushSubscriptionIn, PushSubscriptionOut
from app.push.service import MAX_DEVICES, device_name, is_push_service

# Cookie sessions only: a device is turned on from the browser it belongs to, never with a bearer token.
router = APIRouter(prefix="/api/push", tags=["push"], dependencies=[Depends(current_session)])


@router.get("/key")
async def push_key(user: AuthedUser, db: DbSession) -> PushKeyOut:
    return PushKeyOut(public_key=(await vapid_keys(db)).public_key)  # made on first need


@router.get("/subscriptions")
async def list_subscriptions(user: AuthedUser, db: DbSession) -> list[PushSubscriptionOut]:
    rows = await db.execute(
        select(PushSubscription).where(PushSubscription.user_id == user.id)
        .order_by(PushSubscription.created_at.desc(), PushSubscription.id)
    )
    return [PushSubscriptionOut.model_validate(r) for r in rows.scalars()]


@router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def add_subscription(
    body: PushSubscriptionIn, request: Request, user: AuthedUser, db: DbSession
) -> PushSubscriptionOut:
    if not is_push_service(body.endpoint):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_push_endpoint")
    values = {"user_id": user.id, "p256dh": body.keys.p256dh, "auth": body.keys.auth,
              "name": device_name(request.headers.get("user-agent"))}
    # a browser has one endpoint: registering it again (even signed in as someone else) moves it here
    stmt = insert(PushSubscription).values(endpoint=body.endpoint, **values)
    row_id = await db.scalar(
        stmt.on_conflict_do_update(index_elements=["endpoint"], set_=values).returning(PushSubscription.id)
    )
    # at most MAX_DEVICES per person: the oldest go
    keep = (
        select(PushSubscription.id).where(PushSubscription.user_id == user.id)
        .order_by(PushSubscription.created_at.desc(), PushSubscription.id.desc()).limit(MAX_DEVICES)
    )
    await db.execute(delete(PushSubscription).where(PushSubscription.user_id == user.id,
                                                    PushSubscription.id.not_in(keep)))
    row = await db.get(PushSubscription, row_id, populate_existing=True)
    return PushSubscriptionOut.model_validate(row)


@router.delete("/subscriptions/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_subscription(subscription_id: uuid.UUID, user: AuthedUser, db: DbSession) -> None:
    row = await db.get(PushSubscription, subscription_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "push_subscription_not_found")
    await db.delete(row)
