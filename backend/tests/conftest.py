import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_test"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")

import httpx
import pytest

from app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-Megoo-Client": "web"}
    ) as c:
        yield c
