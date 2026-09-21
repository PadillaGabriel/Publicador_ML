from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=max(30, settings.database_pool_recycle_seconds),
    pool_use_lifo=True,
    pool_size=max(1, settings.database_pool_size),
    max_overflow=max(0, settings.database_max_overflow),
    pool_timeout=max(1.0, settings.database_pool_timeout_seconds),
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def reset_connection_pool() -> None:
    """Discard this process' pooled connections after a transport-level DB failure."""

    engine.dispose()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
