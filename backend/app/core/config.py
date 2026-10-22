from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://megoo:megoo@localhost:5433/megoo"
    secret_key: str
    cookie_secure: bool = False
    upload_dir: str = "/data/uploads"
    public_url: str = "http://localhost:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()
