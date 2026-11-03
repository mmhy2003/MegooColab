import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.ai import client as ai
from app.auth.models import Role
from app.core.db import SessionLocal
from app.jobs.models import Job
from app.memory import dream, entities, fakes
from app.memory.models import (
    ConclusionStatus,
    MemCard,
    MemConclusion,
    MemDreamRun,
    MemPremise,
    MemSuppression,
    ScopeKind,
)
from tests.factories import make_project, make_user
from tests.memory.test_search import _add


@pytest.fixture
def calls(monkeypatch):
    seen: list = []

    def capture(messages):
        seen.append(messages)
        return fakes.fake_dreaming(messages)

    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", capture)
    return seen


async def _dream(trigger="manual"):
    async with SessionLocal() as s:
        await dream.dream(s, {"trigger": trigger})
        await s.commit()
    async with SessionLocal() as s:
        return (await s.execute(select(MemDreamRun).order_by(MemDreamRun.started_at.desc()))).scalars().first()


async def _active(db):
    rows = await db.execute(select(MemConclusion).where(MemConclusion.status == ConclusionStatus.active))
    return {r.text: r for r in rows.scalars()}


async def _premises(db, cid):
    rows = await db.execute(select(MemPremise.premise_id).where(MemPremise.conclusion_id == cid))
    return set(rows.scalars())


async def test_dream_replaces_duplicates_and_links_premises(db, calls):
    a = await _add(db, "Invoices are sent monthly")
    b = await _add(db, "Invoices are sent monthly")
    run = await _dream()
    assert run.status == "done" and run.stats["replaced"] == 2
    active = await _active(db)
    new = active["Invoices are sent monthly"]
    assert new.kind == "deduced" and await _premises(db, new.id) == {a.id, b.id}
    await db.refresh(a)
    assert a.status == ConclusionStatus.superseded and a.superseded_by_id == new.id


async def test_induction_needs_two_premises_and_confidence(db, monkeypatch):
    await _add(db, "Payments retry webhooks")
    await _add(db, "Refunds retry webhooks")
    reply = {"induce": [{"premises": ["C1"], "text": "one premise", "confidence": 0.5},
                        {"premises": ["C1", "C2"], "text": "bad confidence", "confidence": 1.5},
                        {"premises": ["C1", "C2"], "text": "Everything retries webhooks", "confidence": 0.8}],
             "card": "Card"}
    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", lambda m: json.dumps(reply))
    run = await _dream()
    assert (run.stats["induced"], run.stats["dropped"]) == (1, 2)
    row = (await _active(db))["Everything retries webhooks"]
    assert (row.kind, row.confidence) == ("induced", 0.8) and len(await _premises(db, row.id)) == 2


async def test_pinned_never_replaced(db, calls):
    a = await _add(db, "Deploys run nightly", pinned=True)
    b = await _add(db, "Deploys run nightly")
    await _dream()
    await db.refresh(a)
    await db.refresh(b)
    assert a.status == ConclusionStatus.active
    assert b.status == ConclusionStatus.superseded


async def test_dream_never_mixes_scopes(client, db, calls):
    pa, _, _ = await make_project(client, db, "AAA")
    pb, _, _ = await make_project(client, db, "BBB")
    await _add(db, "Billing service uses Stripe", scope=(ScopeKind.project, uuid.UUID(pa["id"])))
    await _add(db, "Billing service uses Stripe", scope=(ScopeKind.project, uuid.UUID(pb["id"])))
    run = await _dream()
    assert run.stats["replaced"] == 0 and run.stats["pairs"] == 2
    cards = (await db.execute(select(MemCard))).scalars().all()
    assert sorted(str(c.scope_project_id) for c in cards) == sorted([pa["id"], pb["id"]])
    for messages in calls:
        assert messages[-1]["content"].count("Billing service uses Stripe") == 1


async def test_cards_per_entity_and_scope_and_nothing_new_no_calls(db, calls):
    await _add(db, "Releases ship every Tuesday")
    await _add(db, "Hotfixes ship any day")
    await _dream()
    [card] = (await db.execute(select(MemCard))).scalars().all()
    assert card.scope_kind == ScopeKind.org and "Releases ship every Tuesday" in card.summary_md
    assert len(card.conclusion_ids) == 2
    n = len(calls)
    run = await _dream()
    assert len(calls) == n and run.stats["pairs"] == 0


async def test_dream_does_not_rederive_deleted(db, monkeypatch):
    a = await _add(db, "Billing uses Stripe")
    a.source_kind, a.source_id = "comment", uuid.uuid4()
    db.add(MemSuppression(source_kind="comment", source_id=a.source_id, entity_id=a.entity_id,
                          text="Stripe handles all billing"))
    await db.commit()
    reply = {"deduce": [{"premises": ["C1"], "text": "Stripe handles all billing"}], "card": ""}
    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", lambda m: json.dumps(reply))
    run = await _dream()
    assert run.stats["deduced"] == 0 and "Stripe handles all billing" not in await _active(db)


async def test_tick_enqueues_only_at_dream_hour_once_per_20h(db, monkeypatch):
    at = datetime(2026, 10, 27, 3, 5, tzinfo=UTC)
    monkeypatch.setattr(dream, "utcnow", lambda: at)
    async with SessionLocal() as s:
        await dream.dream_tick(s, {})
        await s.commit()
    assert [j.kind for j in (await db.execute(select(Job))).scalars()] == ["mem.dream"]
    await db.execute(Job.__table__.delete())
    db.add(MemDreamRun(trigger="scheduled", started_at=at - timedelta(hours=2)))
    await db.commit()
    async with SessionLocal() as s:
        await dream.dream_tick(s, {})
        await s.commit()
    assert (await db.execute(select(Job))).first() is None
    monkeypatch.setattr(dream, "utcnow", lambda: at.replace(hour=4))
    await db.execute(MemDreamRun.__table__.delete())
    await db.commit()
    async with SessionLocal() as s:
        await dream.dream_tick(s, {})
        await s.commit()
    assert (await db.execute(select(Job))).first() is None


async def test_manual_dream_admin_only_and_409_when_running(db):
    admin = await make_user(db, role=Role.admin)
    manager = await make_user(db, role=Role.manager)
    with pytest.raises(HTTPException) as e:
        await dream.start_dream(db, manager)
    assert e.value.status_code == 403
    run = await dream.start_dream(db, admin)
    await db.commit()
    assert run.trigger == "manual" and run.status == "running"
    assert [j.payload for j in (await db.execute(select(Job).where(Job.kind.not_like("search.%")))).scalars()] == [
        {"run_id": str(run.id)}]
    with pytest.raises(HTTPException) as e:
        await dream.start_dream(db, admin)
    assert (e.value.status_code, e.value.detail) == (409, "dream_running")


async def test_failed_pair_does_not_abort_run(client, db, monkeypatch):
    pa, _, _ = await make_project(client, db, "AAA")
    await _add(db, "Good fact one about billing")
    await _add(db, "Another fact", scope=(ScopeKind.project, uuid.UUID(pa["id"])))

    def flaky(messages):
        if "organization" in messages[-1]["content"]:
            return "garbage"
        return fakes.fake_dreaming(messages)

    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", flaky)
    run = await _dream()
    assert run.status == "done" and run.stats["failed_pairs"] == 1 and run.stats["cards"] == 1


async def test_entities_module_used(db):
    assert (await entities.org_entity(db)).name == "Organization"


async def _projects(client, db, keys):
    """A conclusion in each project's scope: one pair to dream per project."""
    for key in keys:
        p, _, _ = await make_project(client, db, key)
        await _add(db, f"Fact about {key}", scope=(ScopeKind.project, uuid.UUID(p["id"])))


async def test_a_cut_off_reply_skips_only_that_pair(client, db, monkeypatch):
    # five big pairs whose reply is cut off and one that fits: however they are ordered, three cut-off ones come in
    # a row; that is about those pairs, not the provider, so the run goes on to the one that fits
    await _projects(client, db, ["BA", "BB", "BC", "BD", "BE"])
    await _add(db, "A small org fact")

    def cut_off(messages):
        if "Fact about B" in messages[-1]["content"]:
            raise ai.AiBadOutput("truncated: the reply hit max_tokens")
        return fakes.fake_dreaming(messages)

    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", cut_off)
    run = await _dream()
    assert run.status == "done"
    assert (run.stats["failed_pairs"], run.stats["cards"]) == (5, 1)


async def test_errors_that_hit_every_pair_still_stop_the_run(client, db, monkeypatch):
    await _projects(client, db, ["SA", "SB", "SC", "SD"])

    def down(messages):
        raise RuntimeError("provider down")

    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", down)
    run = await _dream()
    assert run.status == "failed" and run.stats["pairs"] == dream.MAX_CONSECUTIVE_FAILURES


async def test_pairs_that_failed_go_to_the_back_of_the_next_run(client, db, monkeypatch):
    await _projects(client, db, ["QA", "QB", "QC"])
    monkeypatch.setattr(dream, "PAIRS_PER_RUN", 1)

    def cut_off(messages):
        raise ai.AiBadOutput("truncated: the reply hit max_tokens")

    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", cut_off)
    first = await _dream()
    assert first.stats["failed_pairs"] == 1
    tried: list[str] = []

    def fits(messages):
        tried.append(messages[-1]["content"])
        return fakes.fake_dreaming(messages)

    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "dreaming", fits)
    await _dream()
    # the one run of one pair tried another pair, not the one that failed last time
    failed_key = first.stats["failed_keys"][0]
    async with SessionLocal() as s:
        cards = (await s.execute(select(MemCard))).scalars().all()
    assert len(cards) == 1 and str(cards[0].scope_project_id) not in failed_key


def test_the_instructions_keep_the_reply_small():
    from app.memory import prompts

    assert "at most 10" in prompts.DREAMING_SYSTEM
    assert dream.MAX_TOKENS >= 16000
