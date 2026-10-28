"""Admin → Settings: whether the rate limits are on (Valkey reachable)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.auth.deps import AdminUser
from app.ratelimit import store

router = APIRouter(prefix="/api/admin/rate-limits", tags=["rate-limits"])


class RateLimitsOut(BaseModel):
    working: bool


@router.get("")
async def rate_limits_status(_admin: AdminUser) -> RateLimitsOut:
    return RateLimitsOut(working=await store.healthy())
