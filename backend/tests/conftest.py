import asyncio
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

# Only TEST_DATABASE_URL (or the default test DB) decides the database; an exported DATABASE_URL
# is overwritten. The session fixture below drops the public schema, so refuse any non-test DB.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://megoo:megoo@localhost:5433/megoo_test"
)
_db_name = urlsplit(TEST_DATABASE_URL).path.rsplit("/", 1)[-1]
if not _db_name.endswith("_test"):
    raise RuntimeError(
        f"Refusing to run tests: database name {_db_name!r} does not end in '_test' "
        "(the suite drops the public schema). Fix TEST_DATABASE_URL."
    )
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef")
os.environ["RUN_MIGRATIONS_ON_STARTUP"] = "false"
os.environ["DB_NULL_POOL"] = "true"
os.environ["AI_FAKE"] = "true"
os.environ.setdefault("MEILI_URL", "http://localhost:7700")
os.environ.setdefault("MEILI_MASTER_KEY", "megoo-dev-master-key")
os.environ.setdefault("VALKEY_URL", "valkey://:megoo-dev-valkey@localhost:6379/0")
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="megoo-uploads-")

import httpx
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.models
from app.core.db import Base, SessionLocal, engine
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
async def _migrated_database():
    assert engine.url.database and engine.url.database.endswith("_test"), engine.url.database
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


@pytest.fixture(autouse=True)
def _rate_limit_namespace():
    """Each test counts in its own Valkey namespace, so counters never carry over between tests."""
    import uuid

    from app.core.config import get_settings
    from app.ratelimit import store

    settings = get_settings()
    before = settings.valkey_prefix
    settings.valkey_prefix = f"test:{uuid.uuid4()}:"
    store.reset_client()
    yield
    settings.valkey_prefix = before
    store.reset_client()


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
def tc_factory(app):
    """Starlette TestClients against the same app. `lifespan=True` runs startup (event hub, runner registry):
    use it for the client that opens sockets or needs the app's background services."""
    entered: list[TestClient] = []

    def _make(lifespan: bool = False) -> TestClient:
        c = TestClient(app, headers={"X-Megoo-Client": "web"})
        if lifespan:
            c.__enter__()
            entered.append(c)
        return c

    yield _make
    for c in entered:
        c.__exit__(None, None, None)


@pytest.fixture
async def mcp_running(app):
    """httpx ASGITransport doesn't run the lifespan, so run the MCP session manager in its own task.

    (An anyio task group must be exited by the task that entered it, hence the task.)
    """
    started, stop = asyncio.Event(), asyncio.Event()

    async def _run():
        async with app.state.mcp.session_manager.run():
            started.set()
            await stop.wait()

    task = asyncio.create_task(_run())
    await started.wait()
    yield
    stop.set()
    await task


@pytest.fixture
def outbox(app):
    from app.core.email import OutboxMailer, get_mailer

    mailer = OutboxMailer()
    app.dependency_overrides[get_mailer] = lambda: mailer
    return mailer
