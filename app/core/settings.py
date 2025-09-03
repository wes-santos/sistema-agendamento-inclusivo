from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(str, Enum):
    DEV = "dev"
    HML = "hml"
    PROD = "prod"


class Settings(BaseSettings):
    APP_ENV: Env = Env.DEV
    DEBUG: bool = False
    SECRET_KEY: str

    DATABASE_URL: str

    SMTP_HOST: str | None = None
    SMTP_PORT: int | None = None
    SMTP_USER: str | None = None
    SMTP_PASS: str | None = None

    FRONT_BASE_URL: str = "http://localhost:8000"
    ALLOWED_HOSTS: str = "localhost,127.0.0.1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


# cria instância global
settings = Settings()
