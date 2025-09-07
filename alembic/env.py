from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.db.base  # noqa: F401
from alembic import context

# Carrega settings do app (inclui .env)
from app.core.settings import settings
from app.db.base_class import Base

# Config Alembic
config = context.config

# Usa a URL do settings (do .env) em vez do alembic.ini
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Logging Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata para autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,  # detecta mudanças de tipo
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
