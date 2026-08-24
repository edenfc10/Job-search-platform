from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aijaa.core.config import get_settings

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def engine():
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    engine()
    assert _session_factory is not None
    return _session_factory


async def init_db() -> None:
    from aijaa.core.tables import Base

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


def reset_for_tests() -> None:
    """Drop cached engine so tests can point at a fresh database URL."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
    get_settings.cache_clear()


async def dispose_for_tests() -> None:
    """Dispose the cached engine before changing a test database URL.

    Merely dropping the module reference leaves aiosqlite worker threads alive
    until after pytest closes its event loop, which produces noisy thread
    exceptions and can hide real teardown failures.
    """
    global _engine, _session_factory
    previous_engine = _engine
    _engine = None
    _session_factory = None
    get_settings.cache_clear()
    if previous_engine is not None:
        await previous_engine.dispose()
