"""Ask the memory (MEM-5): an answer from the conclusions the asker may read, citing the ones it used."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import client as ai
from app.auth.models import User
from app.memory import prompts
from app.memory.access import readable_scopes
from app.memory.models import MemCard, MemConclusion, MemEntity
from app.memory.search import search_conclusions

log = logging.getLogger(__name__)

NOTHING = "The memory has nothing on that yet."
QUESTION_MAX = 1000
ANSWER_MAX = 8000
RETRIEVE = 20
ANSWER_TIMEOUT_SECONDS = 60


class AnswerOut(BaseModel):
    answer: str
    cited: list[str] = []


@dataclass
class AnswerResult:
    answer_md: str
    cited: list[MemConclusion] = field(default_factory=list)


async def _cards(db: AsyncSession, user: User, entity_ids: set[uuid.UUID]) -> list[tuple[str, MemCard]]:
    scopes = await readable_scopes(db, user)
    rows = await db.execute(
        select(MemEntity.name, MemCard)
        .join(MemEntity, MemEntity.id == MemCard.entity_id)
        .where(MemCard.entity_id.in_(entity_ids), scopes.clause(MemCard))
        .order_by(MemEntity.name)
    )
    return [(name, card) for name, card in rows if card.summary_md.strip()]


async def answer(db: AsyncSession, user: User, question: str, *, project_id: uuid.UUID | None = None) -> AnswerResult:
    question = question.replace("\x00", "").strip()
    if not 1 <= len(question) <= QUESTION_MAX:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_question")
    rows = await search_conclusions(db, user, question, project_id=project_id, limit=RETRIEVE)
    if not rows:
        return AnswerResult(NOTHING)
    cards = await _cards(db, user, {r.entity_id for r in rows})
    messages = prompts.answering_messages(question, cards, rows)
    try:
        reply = await asyncio.wait_for(
            ai.complete(db, "answering", messages, timeout=ANSWER_TIMEOUT_SECONDS), ANSWER_TIMEOUT_SECONDS
        )
        out = ai.parse_json(reply, AnswerOut)
    except ai.AiNotConfigured:
        raise HTTPException(status.HTTP_409_CONFLICT, "memory_answering_not_configured") from None
    except Exception:
        log.warning("memory answering failed", exc_info=True)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "memory_unavailable") from None
    by_id = {f"C{i}": c for i, c in enumerate(rows, start=1)}
    cited: list[MemConclusion] = []
    for ref in out.cited:
        c = by_id.get(str(ref).strip())
        if c is not None and c not in cited:
            cited.append(c)
    return AnswerResult(out.answer.strip()[:ANSWER_MAX] or NOTHING, cited)
