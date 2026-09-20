from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config.db_url import normalize_database_url
from src.persistence.base import Base
from src.persistence import models  # noqa: F401


config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which silences every application
    # logger that already exists in this process. Running a migration in-process
    # (tests, a management command) would otherwise leave the service loggers dead
    # for the rest of the run, so an incident later logs nothing.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

database_url = os.getenv("DATABASE_URL")
if database_url:
    # Migrations run before the app builds its own engine, so this path needs the
    # same driver fix independently — it reads the environment directly rather
    # than going through Settings.
    #
    # The doubled %% is not cosmetic. set_main_option writes into a ConfigParser
    # that performs %-interpolation, so a single % anywhere in the URL aborts the
    # migration with "invalid interpolation syntax" before any engine is built.
    # Percent-encoding is ordinary in a generated password, and normalizing the
    # URL can introduce it where there was none (a literal ':' in a password
    # re-renders as %3A), so escape at this boundary and nowhere else — the value
    # ConfigParser hands back is the unescaped original (refuter F1).
    normalized = normalize_database_url(database_url)
    config.set_main_option("sqlalchemy.url", normalized.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
