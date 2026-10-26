import math
import types

import litellm
import pytest
from sqlalchemy import select, text

from app.ai import client as ai
from app.ai.models import AiJobModel, AiProvider, AiUsage
from app.auth.models import Role
from app.core.config import get_settings
from tests.factories import login, make_user


@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_fake", False)


async def _admin(client, db):
    admin = await make_user(db, role=Role.admin)
    await login(client, admin)
    return admin


async def _configure(client, *, key="sk-secret-123", model="text-embedding-3-small"):
    r = await client.post("/api/admin/ai/providers", json={"name": "OpenAI", "kind": "openai", "api_key": key})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    r = await client.put("/api/admin/ai/jobs/embeddings", json={"provider_id": pid, "model": model})
    assert r.status_code == 200, r.text
    return pid


def _fake_response(n, prompt_tokens=5):
    return types.SimpleNamespace(
        data=[{"object": "embedding", "index": i, "embedding": [float(i), 1.0]} for i in reversed(range(n))],
        usage=types.SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=0),
    )


async def test_provider_key_encrypted_and_never_returned(client, db):
    await _admin(client, db)
    await _configure(client)
    stored = (await db.execute(text("SELECT api_key_enc FROM ai_providers"))).scalar_one()
    assert stored and "sk-secret-123" not in stored
    providers = (await client.get("/api/admin/ai/providers")).json()
    assert providers == [{"id": providers[0]["id"], "name": "OpenAI", "kind": "openai", "api_base": None, "has_key": True}]
    assert "sk-secret-123" not in (await client.get("/api/admin/ai/providers")).text


async def test_patch_keeps_key_unless_replaced(client, db):
    await _admin(client, db)
    pid = await _configure(client)
    before = (await db.execute(text("SELECT api_key_enc FROM ai_providers"))).scalar_one()
    r = await client.patch(f"/api/admin/ai/providers/{pid}", json={"api_base": "https://proxy.example.com/v1"})
    assert r.status_code == 200 and r.json()["has_key"] is True
    assert (await db.execute(text("SELECT api_key_enc FROM ai_providers"))).scalar_one() == before
    r = await client.patch(f"/api/admin/ai/providers/{pid}", json={"api_key": ""})
    assert r.json()["has_key"] is False


async def test_embed_fake_is_deterministic_64d_unit(db):
    model, vecs = await ai.embed(db, ["hello world", "hello world", "something else"])
    assert model == "fake/embed-64"
    assert len(vecs) == 3 and all(len(v) == 64 for v in vecs)
    assert vecs[0] == vecs[1] and vecs[0] != vecs[2]
    for v in vecs:
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)
    _, (empty,) = await ai.embed(db, [""])
    assert math.isclose(math.sqrt(sum(x * x for x in empty)), 1.0, rel_tol=1e-6)


async def test_current_model(db, client, real_mode):
    assert await ai.current_model(db, "embeddings") is None
    await _admin(client, db)
    await _configure(client)
    assert await ai.current_model(db, "embeddings") == "openai/text-embedding-3-small"


async def test_current_model_fake():
    from app.core.db import SessionLocal

    async with SessionLocal() as s:
        assert await ai.current_model(s, "embeddings") == "fake/embed-64"


async def test_model_already_prefixed_is_not_prefixed_twice(db, client, real_mode):
    await _admin(client, db)
    await _configure(client, model="openai/text-embedding-3-large")
    assert await ai.current_model(db, "embeddings") == "openai/text-embedding-3-large"


async def test_embed_not_configured_raises_when_not_fake(db, real_mode):
    with pytest.raises(ai.AiNotConfigured):
        await ai.embed(db, ["x"])


async def test_embed_records_usage_and_failure(db, client, real_mode, monkeypatch):
    await _admin(client, db)
    await _configure(client)
    calls = []

    async def ok(**kw):
        calls.append(kw)
        return _fake_response(len(kw["input"]), prompt_tokens=9)

    monkeypatch.setattr(litellm, "aembedding", ok)
    model, vecs = await ai.embed(db, ["a", "b"])
    assert model == "openai/text-embedding-3-small"
    assert vecs == [[0.0, 1.0], [1.0, 1.0]]  # ordered by index
    assert calls[0]["model"] == "openai/text-embedding-3-small"
    assert calls[0]["api_key"] == "sk-secret-123"

    async def boom(**kw):
        raise litellm.exceptions.AuthenticationError("bad key", llm_provider="openai", model="x")

    monkeypatch.setattr(litellm, "aembedding", boom)
    with pytest.raises(litellm.exceptions.AuthenticationError):
        await ai.embed(db, ["c"])
    rows = (await db.execute(select(AiUsage).order_by(AiUsage.created_at))).scalars().all()
    assert [(r.job, r.model, r.ok, r.error_code, r.input_tokens) for r in rows] == [
        ("embeddings", "openai/text-embedding-3-small", True, None, 9),
        ("embeddings", "openai/text-embedding-3-small", False, "AuthenticationError", 0),
    ]


async def test_embed_batches_64(db, client, real_mode, monkeypatch):
    await _admin(client, db)
    await _configure(client)
    sizes = []

    async def ok(**kw):
        sizes.append(len(kw["input"]))
        return _fake_response(len(kw["input"]))

    monkeypatch.setattr(litellm, "aembedding", ok)
    _, vecs = await ai.embed(db, [f"t{i}" for i in range(130)])
    assert sizes == [64, 64, 2] and len(vecs) == 130


async def test_admin_only(client, db):
    member = await make_user(db)
    await login(client, member)
    for method, url in [
        ("get", "/api/admin/ai/providers"),
        ("get", "/api/admin/ai/jobs"),
        ("get", "/api/admin/ai/usage"),
        ("post", "/api/admin/ai/jobs/embeddings/test"),
    ]:
        assert (await getattr(client, method)(url)).status_code == 403, url


async def test_delete_provider_in_use_409(client, db):
    await _admin(client, db)
    pid = await _configure(client)
    r = await client.delete(f"/api/admin/ai/providers/{pid}")
    assert r.status_code == 409 and r.json()["detail"] == "provider_in_use"
    await client.put("/api/admin/ai/jobs/embeddings", json={"provider_id": None, "model": ""})
    assert (await client.delete(f"/api/admin/ai/providers/{pid}")).status_code == 204
    assert (await db.execute(select(AiProvider))).first() is None


async def test_jobs_list_and_unknown_job(client, db):
    await _admin(client, db)
    assert (await client.get("/api/admin/ai/jobs")).json() == [{"job": "embeddings", "provider_id": None, "model": ""}]
    r = await client.put("/api/admin/ai/jobs/dreaming", json={"provider_id": None, "model": ""})
    assert r.status_code == 404 and r.json()["detail"] == "unknown_job"
    pid = await _configure(client)
    assert (await client.get("/api/admin/ai/jobs")).json() == [
        {"job": "embeddings", "provider_id": pid, "model": "text-embedding-3-small"}
    ]
    assert (await db.execute(select(AiJobModel))).scalar_one().model == "text-embedding-3-small"


async def test_test_endpoint_reports_error_without_key(client, db, real_mode, monkeypatch):
    await _admin(client, db)
    await _configure(client)

    async def boom(**kw):
        raise RuntimeError(f"Incorrect API key provided: {kw['api_key']}")

    monkeypatch.setattr(litellm, "aembedding", boom)
    r = await client.post("/api/admin/ai/jobs/embeddings/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["model"] == "openai/text-embedding-3-small"
    assert "sk-secret-123" not in body["error"] and "RuntimeError" in body["error"]


async def test_test_endpoint_ok_in_fake_mode(client, db):
    await _admin(client, db)
    r = await client.post("/api/admin/ai/jobs/embeddings/test")
    assert r.json() == {"ok": True, "model": "fake/embed-64", "error": None}


async def test_usage_endpoint_aggregates(client, db):
    await _admin(client, db)
    db.add_all(
        [
            AiUsage(job="embeddings", model="m1", input_tokens=10, output_tokens=0, cost_usd=0.5, ok=True),
            AiUsage(job="embeddings", model="m1", input_tokens=5, output_tokens=0, cost_usd=None, ok=False, error_code="X"),
            AiUsage(job="embeddings", model="m2", input_tokens=1, output_tokens=0, cost_usd=0.25, ok=True),
        ]
    )
    await db.commit()
    rows = (await client.get("/api/admin/ai/usage", params={"days": 30})).json()
    by_model = {r["model"]: r for r in rows}
    assert by_model["m1"]["calls"] == 2 and by_model["m1"]["failures"] == 1
    assert by_model["m1"]["input_tokens"] == 15 and by_model["m1"]["cost_usd"] == 0.5
    assert by_model["m2"]["calls"] == 1 and by_model["m2"]["job"] == "embeddings"
    assert (await client.get("/api/admin/ai/usage", params={"days": 0})).status_code == 422
