from sqlalchemy import inspect

import aijaa.core.db as db


async def test_local_sqlite_startup_creates_schema():
    await db.prepare_database()

    async with db.engine().connect() as connection:
        tables = await connection.run_sync(lambda conn: inspect(conn).get_table_names())

    assert "seekers" in tables
    assert "applications" in tables


async def test_production_sqlite_startup_is_rejected(monkeypatch):
    monkeypatch.setenv("AIJAA_PRODUCTION_MODE", "true")
    db.reset_for_tests()

    try:
        await db.prepare_database()
    except db.DatabaseNotReadyError as exc:
        assert str(exc) == "SQLite is not allowed in production mode."
    else:
        raise AssertionError("production SQLite startup should fail")


async def test_postgres_startup_accepts_current_alembic_head(monkeypatch):
    monkeypatch.setenv(
        "AIJAA_DATABASE_URL",
        "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
    )
    db.reset_for_tests()
    expected = db.expected_migration_heads()

    async def current_heads():
        return expected

    monkeypatch.setattr(db, "current_migration_heads", current_heads)
    await db.prepare_database()


async def test_postgres_startup_rejects_stale_alembic_head(monkeypatch):
    monkeypatch.setenv(
        "AIJAA_DATABASE_URL",
        "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
    )
    db.reset_for_tests()

    async def stale_heads():
        return {"stale-revision"}

    monkeypatch.setattr(db, "current_migration_heads", stale_heads)

    try:
        await db.prepare_database()
    except db.DatabaseNotReadyError as exc:
        assert "PostgreSQL migration mismatch" in str(exc)
        assert "Run `alembic upgrade head`" in str(exc)
    else:
        raise AssertionError("stale PostgreSQL startup should fail")
