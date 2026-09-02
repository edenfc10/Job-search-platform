set dotenv-load := true

venv := ".venv/bin"

setup:
    python3 -m venv .venv
    {{venv}}/pip install -e ".[dev]"

test:
    {{venv}}/python -m pytest -q

lint:
    {{venv}}/ruff check backend/src backend/tests database/migrations

typecheck:
    {{venv}}/python -c "import aijaa.api.app; print('imports ok')"

demo:
    rm -f demo.db
    AIJAA_DATABASE_URL=sqlite+aiosqlite:///./demo.db AIJAA_ARTIFACTS_DIR=./demo_artifacts {{venv}}/python backend/scripts/demo_pipeline.py

run:
    {{venv}}/uvicorn aijaa.api.app:app --reload

ci: lint typecheck test
