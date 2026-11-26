from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.db import engine_options


def test_pool_settings_reach_the_engine():
    settings = Settings(secret_key="k" * 32, db_pool_size=7, db_max_overflow=3, db_null_pool=False)
    assert engine_options(settings) == {"pool_pre_ping": True, "pool_size": 7, "max_overflow": 3}


def test_null_pool_ignores_the_sizes():
    settings = Settings(secret_key="k" * 32, db_pool_size=7, db_max_overflow=3, db_null_pool=True)
    assert engine_options(settings) == {"pool_pre_ping": True, "poolclass": NullPool}


def test_pool_defaults():
    assert Settings.model_fields["db_pool_size"].default == 20
    assert Settings.model_fields["db_max_overflow"].default == 20
