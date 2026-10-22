from tests.conftest import run_autogenerate_diff


async def test_migrations_upgrade_head_is_clean(db):
    # conftest ran `alembic upgrade head` once per session; autogenerate must find no diff
    diff = await run_autogenerate_diff()
    assert diff == []
