from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None


def configure_engine(database_url: str | None = None, **engine_kwargs) -> AsyncEngine:
    global engine, SessionLocal
    url = database_url or get_settings().database_url
    kwargs = {"pool_pre_ping": True, **engine_kwargs}
    engine = create_async_engine(url, **kwargs)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    return engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if SessionLocal is None:
        configure_engine()
    assert SessionLocal is not None
    return SessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def dispose_engine() -> None:
    global engine, SessionLocal
    if engine is not None:
        await engine.dispose()
    engine = None
    SessionLocal = None
