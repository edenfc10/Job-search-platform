# Database

PostgreSQL is the recommended local and production database. Alembic
configuration and versioned schema migrations live in `backend/migrations`;
SQLAlchemy runtime code remains in `backend/src/aijaa/core` because it is part
of the backend application.

Run migrations from the repository root:

```bash
uv run alembic -c backend/alembic.ini upgrade head
uv run alembic -c backend/alembic.ini check
```
