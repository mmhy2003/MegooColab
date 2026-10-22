import asyncio
import os
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_test"
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ["RUN_MIGRATIONS_ON_STARTUP"] = "false"
os.environ["DB_NULL_POOL"] = "true"
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="megoo-uploads-")

import httpx
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text

import app.models  # noqa: F401
from app.core.db import Base, SessionLocal, engine
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
async def _migrated_database():
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    # env.py calls asyncio.run(), so run it off the test loop
    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")
    yield


@pytest.fixture(autouse=True)
async def _truncate_tables(_migrated_database):
    yield
    tables = [t.name for t in Base.metadata.sorted_tables]
    if tables:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE")
            )


async def run_autogenerate_diff() -> list:
    async with engine.connect() as conn:
        return await conn.run_sync(
            lambda sync_conn: compare_metadata(
                MigrationContext.configure(sync_conn, opts={"compare_type": True}),
                Base.metadata,
            )
        )


@pytest.fixture
async def db():
    async with SessionLocal() as session:
        yield session


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def client_factory(app):
    """Builds extra independent clients (separate cookie jars) against the same app."""
    clients: list[httpx.AsyncClient] = []

    def _make() -> httpx.AsyncClient:
        c = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"X-Megoo-Client": "web"},
        )
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()


@pytest.fixture
async def client(client_factory):
    return client_factory()


@pytest.fixture
def outbox(app):
    from app.core.email import OutboxMailer, get_mailer

    mailer = OutboxMailer()
    app.dependency_overrides[get_mailer] = lambda: mailer
    return mailer
