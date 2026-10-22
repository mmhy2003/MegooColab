from fastapi import APIRouter

from app.auth.deps import AuthedUser

router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("")
async def list_teams(user: AuthedUser) -> list[dict]:
    # replaced in Task 8
    return []
