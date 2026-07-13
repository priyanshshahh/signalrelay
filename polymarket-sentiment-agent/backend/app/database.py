"""SQLAlchemy engine + session scope.

Local dev defaults to a SQLite file under ./data/. Production points
DATABASE_URL at Postgres (e.g. Neon free tier) — Render's free-tier disk
is ephemeral, so SQLite there survives only until the next restart.

Schema is denormalized intentionally for MVP: every row captures the
agent's full reasoning context at the moment of decision, so post-mortems
are a single SELECT.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, declarative_base

from .config import settings


def normalize_db_url(url: str) -> str:
    """Map provider-style Postgres URLs onto the psycopg2 dialect.

    Neon/Heroku/Render hand out `postgres://` (and sometimes plain
    `postgresql://`) URLs; SQLAlchemy 2.x dropped the `postgres://` alias.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def _prepare_sqlite_dir(url: str) -> None:
    """Make sure the parent directory of a SQLite file exists."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        raw = url[len(prefix):]
        if raw and raw != ":memory:":
            Path(raw).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


_db_url = normalize_db_url(settings.database_url)
_prepare_sqlite_dir(_db_url)

connect_args = {"check_same_thread": False} if _db_url.startswith("sqlite") else {}
engine = create_engine(
    _db_url,
    connect_args=connect_args,
    pool_pre_ping=not _db_url.startswith("sqlite"),
    future=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False,
)
Base = declarative_base()


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)
    Base.metadata.create_all(bind=engine)
