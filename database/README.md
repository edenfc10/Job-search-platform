# Database

PostgreSQL is the recommended local and production database. This directory
contains Alembic configuration and versioned schema migrations; SQLAlchemy
runtime code remains in `backend/src/aijaa/core` because it is part of the
backend application.

Run migrations from the repository root:

```bash
uv run alembic -c database/alembic.ini upgrade head
uv run alembic -c database/alembic.ini check
```
