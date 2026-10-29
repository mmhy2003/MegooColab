from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://megoo:megoo@localhost:5433/megoo"
    # POSTGRES_PASSWORD, when the URL carries no password: added encoded, so any character works
    postgres_password: str | None = None
    # the release build bakes the version into the image; run from source it is "dev" (never "out of date")
    app_version: str = "dev"
    # ask GitHub a few times a day for the latest MegooColab and runner versions (update notices); false: never
    update_check: bool = True
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
    # global search (Plan 9): the Meilisearch service; the key never leaves the backend and worker
    meili_url: str = "http://localhost:7700"
    meili_master_key: str = ""
    meili_index: str = "megoo"
    # rate limits (Plan 10): counters live in Valkey, shared by every backend; unreachable means limits are off
    valkey_url: str = "valkey://localhost:6379/0"
    # passed apart from the URL, so any characters work (a `/`, `?` or `#` would break a URL)
    valkey_password: str = "megoo-dev-valkey"
    valkey_prefix: str = "megoo:"
    # a header a fronting proxy sets with the visitor's address (e.g. CF-Connecting-IP); empty: the resolved address
    client_ip_header: str = ""
    rate_limit_login_per_ip: int = 30
    rate_limit_totp_per_account: int = 5
    rate_limit_forgot_per_email: int = 3
    rate_limit_forgot_per_ip: int = 10
    rate_limit_token_pages_per_ip: int = 10
    rate_limit_change_password_per_user: int = 5
    rate_limit_api_per_user: int = 3000
    rate_limit_api_per_ip: int = 120
    rate_limit_ai_per_user: int = 30
    rate_limit_webhook_per_connection: int = 120
    rate_limit_ws_connect: int = 30

    @model_validator(mode="after")
    def _password_into_url(self) -> "Settings":
        """POSTGRES_PASSWORD goes into a URL that has none, percent-encoded: `@`, `:`, `/`, `%`, `#` all work."""
        if self.postgres_password:
            url = make_url(self.database_url)
            if url.password is None:
                self.database_url = url.set(password=self.postgres_password).render_as_string(hide_password=False)
        return self


def alembic_url(url: str) -> str:
    """Alembic keeps the URL in a config file format where `%` starts an interpolation: double it."""
    return url.replace("%", "%%")


@lru_cache
def get_settings() -> Settings:
    return Settings()
