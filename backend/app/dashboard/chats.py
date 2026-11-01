"""Chats on the dashboard: the Open chats tile and the Chats card. Chats are seen by the people who can see them
(chats.service.visible_chats), within the scope's projects; under Mine, the chats the viewer started or whose agent
is theirs."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent
from app.chats.models import Chat, ChatStatus
from app.chats.service import WAITING, chat_out, visible_chats
from app.dashboard.schemas import ChatBrief
from app.dashboard.scope import Scope

CHATS_SHOWN = 6


async def _in_scope(db: AsyncSession, scope: Scope) -> list[Chat]:
    chats = [c for c in await visible_chats(db, scope.user) if c.status == ChatStatus.open]
    if scope.project_ids is not None:
        chats = [c for c in chats if c.project_id in scope.project_ids]
    if scope.name == "mine":
        mine = []
        for c in chats:
            owner = (await db.get(Agent, c.agent_id)).owner_id if c.agent_id else None
            if c.started_by == scope.user.id or owner == scope.user.id:
                mine.append(c)
        chats = mine
    return chats


async def chats(db: AsyncSession, scope: Scope) -> tuple[list[ChatBrief], int, int]:
    """The open chats shown (most recent first), how many are open, and how many wait on the viewer."""
    outs = [await chat_out(db, c, scope.user) for c in await _in_scope(db, scope)]
    waiting = sum(1 for o in outs if o.can_act and o.state in WAITING)
    shown = sorted(outs, key=lambda o: o.last_activity_at, reverse=True)[:CHATS_SHOWN]
    briefs = [
        ChatBrief(
            id=o.id, title=o.title, project_key=o.project_key, state=o.state,
            current_step=o.rounds[-1].current_step if o.rounds else None,
            steps_total=o.rounds[-1].steps_total if o.rounds else None,
            pr_url=o.rounds[-1].pr_url if o.rounds else None,
            finish_outcome=o.rounds[-1].finish_outcome if o.rounds else None,
            agent_name=o.agent.name if o.agent else None,
        )
        for o in shown
    ]
    return briefs, len(outs), waiting
