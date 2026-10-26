import types

import litellm
import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.ai import client as ai
from app.ai.models import AiUsage
from app.auth.models import Role
from app.core.config import get_settings
from app.jobs.models import Job, JobStatus
from tests.factories import login, make_user


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_fake", False)


async def _admin(client, db):
    await login(client, await make_user(db, role=Role.admin))


async def _configure(client, job="extraction", model="gpt-x"):
    pid = (await client.post("/api/admin/ai/providers", json={"name": "P", "kind": "openai", "api_key": "sk"})).json()["id"]
    r = await client.put(f"/api/admin/ai/jobs/{job}", json={"provider_id": pid, "model": model})
    assert r.status_code == 200, r.text
    return pid


def _resp(content='{"a":1}'):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
        usage=types.SimpleNamespace(prompt_tokens=7, completion_tokens=3),
    )


async def test_jobs_list_includes_llm_jobs(client, db):
    await _admin(client, db)
    jobs = [j["job"] for j in (await client.get("/api/admin/ai/jobs")).json()]
    assert jobs == ["embeddings", "extraction", "dreaming", "answering"]


async def test_complete_calls_litellm_and_records_usage(client, db, real_mode, monkeypatch):
    await _admin(client, db)
    await _configure(client)
    seen = {}

    async def fake(**kw):
        seen.update(kw)
        return _resp()

    monkeypatch.setattr(litellm, "acompletion", fake)
    out = await ai.complete(db, "extraction", [{"role": "user", "content": "hi"}], timeout=9, max_tokens=50)
    assert out == '{"a":1}'
    assert seen["model"] == "openai/gpt-x" and seen["response_format"] == {"type": "json_object"}
    assert seen["timeout"] == 9 and seen["max_tokens"] == 50 and seen["api_key"] == "sk"
    row = (await db.execute(select(AiUsage))).scalar_one()
    assert (row.job, row.input_tokens, row.output_tokens, row.ok) == ("extraction", 7, 3, True)


async def test_complete_failure_recorded_and_raised(client, db, real_mode, monkeypatch):
    await _admin(client, db)
    await _configure(client)

    async def boom(**kw):
        raise RuntimeError("down")

    monkeypatch.setattr(litellm, "acompletion", boom)
    with pytest.raises(RuntimeError):
        await ai.complete(db, "extraction", [{"role": "user", "content": "hi"}])
    row = (await db.execute(select(AiUsage))).scalar_one()
    assert (row.ok, row.error_code) == (False, "RuntimeError")


async def test_complete_not_configured_raises(db, real_mode):
    with pytest.raises(ai.AiNotConfigured):
        await ai.complete(db, "dreaming", [{"role": "user", "content": "hi"}])


async def test_complete_fake_mode_uses_registered_fake_and_raises_without_one(db, monkeypatch):
    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "answering", lambda messages: f'{{"echo": "{messages[-1]["content"]}"}}')
    assert await ai.complete(db, "answering", [{"role": "user", "content": "q"}]) == '{"echo": "q"}'
    monkeypatch.delitem(ai.FAKE_COMPLETIONS, "dreaming", raising=False)
    with pytest.raises(ai.AiNotConfigured):
        await ai.complete(db, "dreaming", [{"role": "user", "content": "q"}])
    rows = (await db.execute(select(AiUsage))).scalars().all()
    assert [(r.job, r.cost_usd) for r in rows] == [("answering", 0.0)]


class _Out(BaseModel):
    a: int


def test_parse_json_strips_fence_and_rejects_garbage():
    assert ai.parse_json('```json\n{"a": 2}\n```', _Out).a == 2
    assert ai.parse_json(' {"a": 3} ', _Out).a == 3
    for bad in ("not json", '{"a": "x"}', "[]"):
        with pytest.raises(ai.AiBadOutput):
            ai.parse_json(bad, _Out)


async def test_test_endpoint_llm_job(client, db, monkeypatch):
    await _admin(client, db)
    monkeypatch.setitem(ai.FAKE_COMPLETIONS, "answering", lambda messages: '{"ok": true}')
    r = await client.post("/api/admin/ai/jobs/answering/test")
    assert r.json() == {"ok": True, "model": "fake/llm", "error": None}


async def test_settings_change_enqueues_every_reindex_job(client, db, monkeypatch):
    monkeypatch.setattr(ai, "REINDEX_JOBS", ["kb.reconcile", "t.extra"])
    await _admin(client, db)
    pid = await _configure(client, job="embeddings", model="m")
    from sqlalchemy import update

    await db.execute(update(Job).values(status=JobStatus.done))
    await db.commit()
    await client.put("/api/admin/ai/jobs/embeddings", json={"provider_id": pid, "model": "m"})
    kinds = sorted(j.kind for j in (await db.execute(select(Job).where(Job.status == JobStatus.queued))).scalars())
    assert kinds == ["kb.reconcile", "t.extra"]
