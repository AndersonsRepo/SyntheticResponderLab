"""Pick the Postgres driver the project actually installs.

Hosted Postgres hands out a bare `postgresql://` URL (Railway, Render, Supabase,
Heroku). SQLAlchemy reads a bare scheme as a request for psycopg2, which this
project does not depend on — it installs psycopg v3 (`psycopg[binary]`). The
result is not a connection error but an import error at startup:
`ModuleNotFoundError: No module named 'psycopg2'`, raised from `alembic upgrade
head` before the app ever binds a port, so the platform reports it as a health
check timeout rather than as the missing driver it is.

Only a MISSING driver is filled in. An explicit `postgresql+psycopg2://` is left
exactly as written — someone who names a driver should get that driver, or the
honest failure for not having it, rather than a silent substitution.
"""
from __future__ import annotations

from sqlalchemy.engine.url import make_url

# What this project installs. Change with the dependency, not independently.
_DRIVER = "psycopg"
# `postgres://` is the legacy spelling Heroku popularised; SQLAlchemy 2.x rejects
# it outright, so it has to be rewritten rather than merely completed.
_BARE_POSTGRES_SCHEMES = ("postgresql", "postgres")


def normalize_database_url(url: str) -> str:
    """Return `url` with the Postgres driver made explicit; other URLs untouched."""
    trimmed = url.strip()
    if not trimmed:
        return trimmed
    scheme = trimmed.split("://", 1)[0].lower()
    if scheme not in _BARE_POSTGRES_SCHEMES:
        return trimmed
    # make_url round-trips credentials and query params without us parsing them,
    # which matters because a password can legally contain "://" and "+".
    return make_url(trimmed).set(drivername=f"postgresql+{_DRIVER}").render_as_string(
        hide_password=False)
