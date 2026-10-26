from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://megoo:megoo@localhost:5433/megoo"
    secret_key: str
    cookie_secure: bool = False
    upload_dir: str = "/data/uploads"
    public_url: str = "http://localhost:8080"
    db_null_pool: bool = False
    run_migrations_on_startup: bool = True
    # tests and e2e: deterministic local embeddings, no provider calls
    ai_fake: bool = False
    # the nightly memory consolidation (dreaming) starts in this UTC hour
    memory_dream_hour_utc: int = 3
    # a changed source is read this long after its last change, so a burst of edits is extracted once
    memory_extract_delay_seconds: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
