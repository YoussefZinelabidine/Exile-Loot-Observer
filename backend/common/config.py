"""Application settings, read from the repo-root .env (variables prefixed ELO_)."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

# backend/common/config.py -> repo root is three levels up.
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ELO_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    db_host: str
    db_port: int = 5432
    db_name: str
    db_user: str
    db_pass: SecretStr

    account_hash_salt: SecretStr | None = None
    discord_webhook_url: SecretStr | None = None

    contact_email: str | None = None
    project_url: str | None = None

    data_dir: Path | None = None  # ELO_DATA_DIR: downloaded static data, outside the repo

    log_level: str = "INFO"

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_pass.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def require_account_hash_salt(settings: Settings | None = None) -> str:
    """Return the account-hash salt, or raise if it is not configured."""
    settings = settings or get_settings()
    if settings.account_hash_salt is None or not settings.account_hash_salt.get_secret_value():
        raise RuntimeError(
            "ELO_ACCOUNT_HASH_SALT is not set. Anything that hashes account names "
            "refuses to run without it; set it in the server's .env."
        )
    return settings.account_hash_salt.get_secret_value()
