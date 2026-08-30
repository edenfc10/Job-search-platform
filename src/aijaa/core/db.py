from collections.abc import AsyncIterator
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from aijaa.core.config import get_settings

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class DatabaseNotReadyError(RuntimeError):
    """Raised when the configured database is unsafe or behind migrations."""


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
    """Create tables for local SQLite development and isolated tests only."""
    from aijaa.core.tables import Base

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def expected_migration_heads() -> set[str]:
    project_root = Path(__file__).resolve().parents[3]
    alembic_config = Config(str(project_root / "alembic.ini"))
    return set(ScriptDirectory.from_config(alembic_config).get_heads())


async def current_migration_heads() -> set[str]:
    try:
        async with engine().connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
    except SQLAlchemyError as exc:
        raise DatabaseNotReadyError(
            "PostgreSQL schema is not initialized. Run `alembic upgrade head` before startup."
        ) from exc
    return set(result.scalars())


def validate_migration_heads(current: set[str], expected: set[str]) -> None:
    if not expected:
        raise DatabaseNotReadyError("No Alembic head revision exists in the application.")
    if current != expected:
        current_label = ", ".join(sorted(current)) or "none"
        expected_label = ", ".join(sorted(expected))
        raise DatabaseNotReadyError(
            "PostgreSQL migration mismatch: "
            f"database={current_label}, application={expected_label}. "
            "Run `alembic upgrade head` before startup."
        )


async def prepare_database() -> None:
    """Prepare local SQLite or enforce Alembic-managed PostgreSQL startup."""
    settings = get_settings()
    backend = make_url(settings.database_url).get_backend_name()
    if backend == "sqlite":
        if settings.production_mode:
            raise DatabaseNotReadyError("SQLite is not allowed in production mode.")
        await init_db()
        return
    if backend != "postgresql":
        raise DatabaseNotReadyError(f"Unsupported database backend: {backend}.")

    validate_migration_heads(
        await current_migration_heads(),
        expected_migration_heads(),
    )


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
