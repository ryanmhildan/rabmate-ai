from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(url: str, *, pool_size: int = 5, connect_timeout: int = 5) -> Engine:
    return create_engine(
        url,
        pool_size=pool_size,
        pool_pre_ping=True,
        connect_args={"connect_timeout": connect_timeout},
    )


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return build_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.db_pool_size,
        connect_timeout=settings.db_connect_timeout_seconds,
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, rolled back on error."""
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database(session: Session) -> None:
    """Raises if the database is unreachable."""
    session.execute(text("SELECT 1"))
