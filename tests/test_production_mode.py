import httpx

import aijaa.core.db as db
import aijaa.llm.factory as llm_factory


async def _prod_client(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("AIJAA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/prod.db")
    monkeypatch.setenv("AIJAA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AIJAA_PRODUCTION_MODE", "true")
    monkeypatch.setenv("AIJAA_FAKE_LLM", "false")
    monkeypatch.setenv("AIJAA_LLM_PROVIDER", "openai")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    db.reset_for_tests()
    llm_factory.reset_for_tests()

    from aijaa.api.app import create_app

    await db.init_db()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_production_health_reports_missing_key_without_crashing(monkeypatch, tmp_path):
    async with await _prod_client(monkeypatch, tmp_path) as client:
        r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["production_mode"] is True
    assert body["production_ready"] is False
    assert "AIJAA_OPENAI_API_KEY" in body["missing_requirements"]
    assert body["llm_mode"] == "unconfigured"


async def test_production_blocks_fixture_discovery(monkeypatch, tmp_path):
    async with await _prod_client(
        monkeypatch,
        tmp_path,
        AIJAA_OPENAI_API_KEY="sk-test",
        AIJAA_APPLY_DRIVER="playwright",
    ) as client:
        r = await client.post("/v1/discovery/run", json={"fixtures_dir": "fixtures/postings"})
    assert r.status_code == 422
    assert "disabled in production" in r.json()["detail"]


async def test_manual_job_url_creates_real_posting_without_fixture(monkeypatch, tmp_path):
    async with await _prod_client(
        monkeypatch,
        tmp_path,
        AIJAA_OPENAI_API_KEY="sk-test",
        AIJAA_APPLY_DRIVER="playwright",
    ) as client:
        r = await client.post(
            "/v1/jobs/manual",
            json={
                "url": "https://example.com/jobs/backend",
                "title": "Backend Engineer",
                "company": "ExampleCo",
                "description_text": "Python FastAPI PostgreSQL backend role.",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    assert body["posting"]["source"] == "manual"
    assert body["posting"]["apply_url"] == "https://example.com/jobs/backend"
