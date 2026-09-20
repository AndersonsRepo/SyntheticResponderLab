"""The Postgres driver has to be explicit, or the container dies before it serves.

Hosted Postgres hands out a bare `postgresql://` URL and SQLAlchemy reads that as
psycopg2, which this project does not install. The failure is an ImportError from
`alembic upgrade head` at container start, which a platform reports as a health
check timeout — so it looks like a networking problem and is not one.
"""
import os

import pytest
from sqlalchemy.engine.url import make_url

from src.config.db_url import normalize_database_url
from src.config.settings import API_ROOT, AppSettings


def test_a_hosted_postgres_url_gets_the_installed_driver():
    for bare in ("postgresql://u:pw@host:5432/db", "postgres://u:pw@host/db"):
        assert normalize_database_url(bare).startswith("postgresql+psycopg://")


def test_an_explicit_driver_is_never_substituted():
    """Naming psycopg2 should fail honestly, not be silently rewritten."""
    explicit = "postgresql+psycopg2://u:pw@host/db"
    assert normalize_database_url(explicit) == explicit


def test_non_postgres_urls_pass_through():
    assert normalize_database_url("sqlite:///./local-dev.db") == "sqlite:///./local-dev.db"
    assert normalize_database_url("  ") == ""


def test_credentials_survive_the_rewrite():
    """A password can contain the characters a naive string replace would eat."""
    url = "postgresql://user:p%40ss%3Aword@host:5432/db?sslmode=require"
    rewritten = make_url(normalize_database_url(url))
    original = make_url(url)
    assert rewritten.password == original.password
    assert (rewritten.username, rewritten.host, rewritten.port, rewritten.database) == \
        (original.username, original.host, original.port, original.database)
    assert rewritten.query == original.query


def test_settings_normalizes_what_the_platform_injects(test_settings):
    """The app's own engine is built from Settings, so the fix has to reach it.

    Built by copying the shared fixture and swapping only DATABASE_URL, so this
    stays honest if AppSettings grows another required field.
    """
    hosted = test_settings.model_copy(
        update={"database_url": "postgresql://u:pw@host:5432/db"})
    # model_copy skips validators, so assert on the validated construction path.
    revalidated = AppSettings(**{**{f.alias or n: getattr(test_settings, n)
                                    for n, f in AppSettings.model_fields.items()},
                                 "DATABASE_URL": "postgresql://u:pw@host:5432/db"},
                              _env_file=None)
    assert revalidated.database_url == "postgresql+psycopg://u:pw@host:5432/db"
    assert hosted.database_url == "postgresql://u:pw@host:5432/db"  # copy is unvalidated


def test_migrations_load_psycopg3_not_psycopg2(tmp_path):
    """The crash was in `alembic upgrade head`, so prove THAT path picks the driver.

    env.py reads DATABASE_URL straight from the environment rather than through
    Settings, so it needs its own proof. Pointed at a host that does not exist:
    with the fix the run gets far enough to fail CONNECTING (psycopg v3 loaded);
    without it, it dies importing psycopg2 and never reaches the network.
    """
    import subprocess
    import sys

    env = {**os.environ,
           "DATABASE_URL": "postgresql://u:pw@127.0.0.1:1/db?connect_timeout=1"}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=120)

    assert proc.returncode != 0, "a bogus host should not migrate successfully"
    combined = proc.stdout + proc.stderr
    assert "No module named 'psycopg2'" not in combined, (
        "env.py handed SQLAlchemy a bare postgresql:// URL — this is the "
        "container-start crash the normalizer exists to prevent")
    assert "psycopg" in combined.lower() or "connect" in combined.lower()
