from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config.db_url import normalize_database_url
from src.persistence.base import Base
from src.persistence import models  # noqa: F401
from src.persistence.migration_target import ALEMBIC_INI_DEFAULT, resolve_migration_database_url


config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which silences every application
    # logger that already exists in this process. Running a migration in-process
    # (tests, a management command) would otherwise leave the service loggers dead
    # for the rest of the run, so an incident later logs nothing.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Resolved the same way the application resolves it, so migrations cannot be applied to a database the
# app never opens. Reading os.getenv alone meant a URL set only in apps/api/.env -- the documented local
# setup -- fell through to alembic.ini's default and migrated a second database, reporting success.
#
# Normalizing on top of that is not redundant: resolve_migration_database_url hands back an exported
# DATABASE_URL verbatim, and Railway exports a bare postgres:// URL, so the psycopg3 driver rewrite has
# to happen here too or the migration cannot open a connection at all.
#
# The doubled %% is not cosmetic. set_main_option writes into a ConfigParser that performs
# %-interpolation, so a single % anywhere in the URL aborts the migration with "invalid interpolation
# syntax" before any engine is built. Percent-encoding is ordinary in a generated password, and
# normalizing can introduce it where there was none (a literal ':' re-renders as %3A), so escape at this
# boundary and nowhere else -- the value ConfigParser hands back is the unescaped original (refuter F1).
# A caller that set sqlalchemy.url on the Config object chose that database on purpose --
# the migration tests point alembic at a temp file, and overriding them turns a passing
# suite into five failures that describe nothing real. Only alembic.ini's own default
# means "nobody chose", which is the case the resolver exists to refuse.
configured = (config.get_main_option("sqlalchemy.url") or "").strip()
chosen = configured if configured and configured != ALEMBIC_INI_DEFAULT else resolve_migration_database_url()
normalized = normalize_database_url(chosen)
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
