"""Methodology library (WF-10): the nine versioned instruction texts sent to agents."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.workflow.models import MethodologyVersion, Stage

KEYS: dict[Stage, list[str]] = {
    Stage.brainstorm: ["brainstorm"],
    Stage.design: ["design_revision"],
    Stage.plan: ["plan"],
    Stage.build: ["build_implement", "build_step_review", "build_step_fix"],
    Stage.review: ["review_final", "review_fix"],
    Stage.done: ["finish"],
}
ALL_KEYS: list[str] = [k for keys in KEYS.values() for k in keys]
STAGE_OF: dict[str, Stage] = {k: stage for stage, keys in KEYS.items() for k in keys}

DEFAULTS_DIR = Path(__file__).resolve().parent / "methodology" / "defaults"


async def seed_defaults(db: AsyncSession) -> None:
    """Insert version 1 of every key that has no rows yet. Idempotent."""
    existing = set((await db.execute(select(MethodologyVersion.key).distinct())).scalars())
    for key in ALL_KEYS:
        if key in existing:
            continue
        body = (DEFAULTS_DIR / f"{key}.md").read_text(encoding="utf-8")
        db.add(MethodologyVersion(key=key, version=1, body_md=body, created_by=None))
    await db.flush()


async def current(db: AsyncSession, key: str) -> MethodologyVersion:
    row = (
        await db.execute(
            select(MethodologyVersion)
            .where(MethodologyVersion.key == key)
            .order_by(MethodologyVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError(f"no methodology text for {key!r}")
    return row
