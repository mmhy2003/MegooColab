import asyncio
import logging

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai import client as ai
from app.ai.models import AiUsage
from app.core.config import get_settings


async def test_embed_does_not_wait_for_a_second_connection(monkeypatch):
    small = create_async_engine(get_settings().database_url, pool_size=1, max_overflow=0, pool_timeout=1)
    Small = async_sessionmaker(small, expire_on_commit=False)
    monkeypatch.setattr(ai, "SessionLocal", Small)
    try:
        async with Small() as caller:
            await caller.execute(text("SELECT 1"))  # the caller holds the only connection
            model, _ = await asyncio.wait_for(ai.embed(caller, ["hello"]), 0.5)
            assert model == ai.FAKE_EMBED_MODEL
        await ai.usage_written()
        async with Small() as s:
            assert (await s.execute(select(func.count()).select_from(AiUsage))).scalar_one() == 1
    finally:
        await small.dispose()


async def test_a_failed_usage_write_is_logged_not_raised(monkeypatch, caplog):
    def broken():
        raise RuntimeError("no database")

    monkeypatch.setattr(ai, "SessionLocal", broken)
    with caplog.at_level(logging.ERROR):
        model, _ = await ai.embed(None, ["hello"])
        await ai.usage_written()
    assert model == ai.FAKE_EMBED_MODEL
    assert "recording AI usage failed" in caplog.text
