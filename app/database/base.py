"""Database engines and session factories (sync for scripts/migrations, async for app)."""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import get_settings


def make_sync_engine(url: str | None = None):
    s = get_settings()
    return create_engine(
        url or s.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        future=True,
    )


def make_async_engine(url: str | None = None):
    s = get_settings()
    return create_async_engine(
        url or s.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        future=True,
    )


SyncSession = sessionmaker(bind=make_sync_engine(), expire_on_commit=False, future=True)
AsyncSessionLocal = async_sessionmaker(bind=make_async_engine(), expire_on_commit=False, class_=AsyncSession)


def get_async_session():
    """FastAPI dependency."""
    from sqlalchemy.orm import Session  # noqa

    async def _gen():
        async with AsyncSessionLocal() as session:
            yield session

    return _gen()


def server_admin_url() -> str:
    """URL pointing at the default maintenance DB (to CREATE DATABASE)."""
    s = get_settings()
    return s.DATABASE_URL.rsplit("/", 1)[0] + "/postgres"


async def check_async(url: str | None = None) -> bool:
    engine = make_async_engine(url or get_settings().DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    finally:
        await engine.dispose()


def check_sync(url: str | None = None) -> bool:
    engine = make_sync_engine(url or get_settings().DATABASE_URL)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    finally:
        engine.dispose()
