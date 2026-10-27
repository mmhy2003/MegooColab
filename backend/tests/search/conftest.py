import uuid

import pytest

from app.core.config import get_settings
from app.search import client


@pytest.fixture
async def meili_index():
    """A fresh, uniquely named index with the app's settings; deleted afterwards."""
    settings = get_settings()
    before = settings.meili_index
    settings.meili_index = f"test_{uuid.uuid4().hex[:8]}"
    await client.ensure_index()
    try:
        yield settings.meili_index
    finally:
        try:
            await client.call(lambda: client.client().index(settings.meili_index).delete())
        finally:
            settings.meili_index = before
