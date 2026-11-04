from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.auth.deps import AuthedUser
from app.crons import schedule
from app.crons.schemas import Preview, PreviewIn

router = APIRouter(tags=["crons"])

PREVIEW_COUNT = 3


@router.post("/api/crons/preview")
async def preview(body: PreviewIn, user: AuthedUser) -> Preview:
    """What a schedule means, for the editor as it is typed: never a 422, the error is in the answer."""
    try:
        schedule.check(body.schedule, body.timezone)
    except HTTPException as e:
        return Preview(ok=False, error=e.detail["message"], description=None, next=[])
    return Preview(ok=True, error=None, description=schedule.describe(body.schedule),
                   next=schedule.next_times(body.schedule, body.timezone, datetime.now(UTC), PREVIEW_COUNT))
