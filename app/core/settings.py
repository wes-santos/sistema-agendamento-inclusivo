from enum import Enum

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(str, Enum):
    DEV = "dev"
    HML = "hml"
    PROD = "prod"


class Settings(BaseSettings):
    APP_ENV: Env = Env.DEV
    DEBUG: bool = False
    SECRET_KEY: str

    JWT_SECRET: str = "change-me"
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    DATABASE_URL: str

    SMTP_HOST: str | None = None
    SMTP_PORT: int | None = None
    SMTP_USER: str | None = None
    SMTP_PASS: str | None = None

    FRONT_BASE_URL: str = "http://localhost:8000"
    ALLOWED_HOSTS: str = "localhost,127.0.0.1"

    # If True, login will also set HttpOnly cookies (works with frontends that avoid localStorage)  # noqa: E501
    USE_COOKIE_AUTH: bool = True

    # Only set a domain in production (e.g., ".yourdomain.com"). Leave None in dev.
    COOKIE_DOMAIN: str | None = None

    # In prod, keep cookies secure-only
    SECURE_COOKIES: bool = False

    model_config = SettingsConfigDict(
        env_file=".env.dev",
        env_file_encoding="utf-8",
        ser_json_timedelta="iso8601",
        ser_json_tz="utc",
    )


# cria instância global
settings = Settings()


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
