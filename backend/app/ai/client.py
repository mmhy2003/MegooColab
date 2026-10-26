"""The only gateway to LiteLLM: every model call goes through here, so it is configured per job and metered.

Fake mode (settings.ai_fake, tests and e2e) returns deterministic local vectors without network calls.
"""

import hashlib
import math
import os
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiJobModel, AiProvider, AiUsage
from app.core.config import get_settings
from app.core.crypto import decrypt
from app.core.db import SessionLocal

# use the bundled price list instead of fetching it on import
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

JOBS: tuple[str, ...] = ("embeddings",)
FAKE_EMBED_MODEL = "fake/embed-64"
FAKE_DIM = 64
BATCH = 64
TIMEOUT_SECONDS = 60


class AiNotConfigured(Exception):
    pass


def full_model_name(kind: str, model: str) -> str:
    return model if model.startswith(f"{kind}/") else f"{kind}/{model}"


async def _resolve(db: AsyncSession, job: str) -> tuple[str, AiProvider] | None:
    row = (
        await db.execute(
            select(AiJobModel, AiProvider)
            .join(AiProvider, AiProvider.id == AiJobModel.provider_id)
            .where(AiJobModel.job == job)
        )
    ).first()
    if row is None or not row[0].model:
        return None
    return full_model_name(row[1].kind, row[0].model), row[1]


async def current_model(db: AsyncSession, job: str) -> str | None:
    if get_settings().ai_fake:
        return FAKE_EMBED_MODEL
    resolved = await _resolve(db, job)
    return resolved[0] if resolved else None


def fake_vector(text: str) -> list[float]:
    """Hashed character trigrams (SHA-256 per trigram): similar spellings land near each other."""
    vec = [0.0] * FAKE_DIM
    padded = f"  {text.lower()} "
    grams = [padded[i : i + 3] for i in range(len(padded) - 2)] or [padded]
    for gram in grams:
        digest = hashlib.sha256(gram.encode()).digest()
        vec[digest[0] % FAKE_DIM] += 1.0 if digest[1] % 2 else -1.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        vec[hashlib.sha256(text.encode()).digest()[0] % FAKE_DIM] = 1.0
        return vec
    return [x / norm for x in vec]


async def _record(job: str, model: str, *, ok: bool, input_tokens: int = 0, output_tokens: int = 0,
                  cost: float | None = None, error_code: str | None = None) -> None:
    # its own transaction: a failed call is recorded even when the caller rolls back
    async with SessionLocal() as s:
        s.add(AiUsage(job=job, model=model, ok=ok, input_tokens=input_tokens, output_tokens=output_tokens,
                      cost_usd=cost, error_code=error_code))
        await s.commit()


def _cost(litellm, response) -> float | None:
    try:
        return float(litellm.completion_cost(completion_response=response, call_type="aembedding"))
    except Exception:  # noqa: BLE001 - unknown models have no price
        return None


def _vector(item) -> list[float]:
    return list(item["embedding"] if isinstance(item, dict) else item.embedding)


def _index(item) -> int:
    return item["index"] if isinstance(item, dict) else item.index


async def embed(db: AsyncSession, texts: list[str], *, job: str = "embeddings") -> tuple[str, list[list[float]]]:
    """Returns (model name, one vector per text). Raises AiNotConfigured when the job has no model."""
    if get_settings().ai_fake:
        await _record(job, FAKE_EMBED_MODEL, ok=True, input_tokens=sum(len(t) for t in texts) // 4, cost=0.0)
        return FAKE_EMBED_MODEL, [fake_vector(t) for t in texts]
    resolved = await _resolve(db, job)
    if resolved is None:
        raise AiNotConfigured(job)
    model, provider = resolved
    api_key = decrypt(provider.api_key_enc) if provider.api_key_enc else None

    import litellm

    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        batch = texts[start : start + BATCH]
        try:
            response = await litellm.aembedding(
                model=model, input=batch, api_key=api_key, api_base=provider.api_base, timeout=TIMEOUT_SECONDS
            )
        except Exception as exc:
            await _record(job, model, ok=False, error_code=type(exc).__name__[:100])
            raise
        usage = getattr(response, "usage", None)
        await _record(
            job,
            model,
            ok=True,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            cost=_cost(litellm, response),
        )
        vectors.extend(_vector(item) for item in sorted(response.data, key=_index))
    return model, vectors


async def provider_key(db: AsyncSession, provider_id: uuid.UUID) -> str | None:
    provider = await db.get(AiProvider, provider_id)
    return decrypt(provider.api_key_enc) if provider and provider.api_key_enc else None
