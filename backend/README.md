# Backend

The Python backend lives in `src/aijaa` and keeps the import package name
`aijaa`. FastAPI routers are under `src/aijaa/api/routers`, domain services are
grouped by workflow area, and ARQ worker code is under
`src/aijaa/orchestration`.

Backend tests live in `tests`, deterministic job/application fixtures live in
`fixtures`, and local utility entry points live in `scripts`.

Run backend checks from the repository root:

```bash
uv run pytest -q
uv run ruff check backend/src backend/tests
```
