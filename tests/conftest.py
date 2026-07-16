import os

import httpx
import pytest

import aijaa.core.db as db
import aijaa.llm.factory as llm_factory


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AIJAA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("AIJAA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AIJAA_FAKE_LLM", "true")
    monkeypatch.setenv("AIJAA_DRY_RUN", "true")
    db.reset_for_tests()
    llm_factory.reset_for_tests()
    yield
    db.reset_for_tests()
    llm_factory.reset_for_tests()


@pytest.fixture
async def session():
    await db.init_db()
    async with db.session_factory()() as s:
        yield s


@pytest.fixture
async def client():
    from aijaa.api.app import create_app

    await db.init_db()
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "postings")


PROFILE_PATCH = {
    "contact": {
        "full_name": "Dana Levi",
        "email": "dana@example.com",
        "phone": "+972-50-1234567",
        "location": "Tel Aviv, Israel",
        "links": ["https://linkedin.com/in/danalevi", "https://github.com/danalevi"],
    },
    "work_history": [
        {
            "company": "CloudWorks",
            "title": "Senior Backend Engineer",
            "start": "2021-03",
            "end": None,
            "location": "Tel Aviv",
            "achievements": [
                {"fact_id": "f1", "text": "Reduced API p95 latency by 40% by rearchitecting the caching layer in Python and Redis", "kind": "achievement", "quantified": True},
                {"fact_id": "f2", "text": "Led a team of 5 engineers building FastAPI microservices on Kubernetes serving 2M users", "kind": "achievement", "quantified": True},
            ],
        },
        {
            "company": "DataNest",
            "title": "Backend Engineer",
            "start": "2018-06",
            "end": "2021-02",
            "achievements": [
                {"fact_id": "f3", "text": "Built ETL pipelines in Python and PostgreSQL processing 500GB daily", "kind": "achievement", "quantified": True},
            ],
        },
    ],
    "education": [
        {"institution": "Tel Aviv University", "degree": "B.Sc.", "field": "Computer Science", "year": "2018"}
    ],
    "skills": [
        {"fact_id": "s1", "text": "Python", "kind": "skill"},
        {"fact_id": "s2", "text": "FastAPI", "kind": "skill"},
        {"fact_id": "s3", "text": "PostgreSQL", "kind": "skill"},
        {"fact_id": "s4", "text": "Kubernetes", "kind": "skill"},
        {"fact_id": "s5", "text": "AWS", "kind": "skill"},
        {"fact_id": "s6", "text": "Docker", "kind": "skill"},
        {"fact_id": "s7", "text": "Redis", "kind": "skill"},
    ],
    "languages": ["English", "Hebrew"],
}

PREFERENCES_PATCH = {
    "target_titles": ["Senior Backend Engineer", "Backend Engineer", "Staff Engineer"],
    "seniority": "senior",
    "industries": ["SaaS", "Cloud"],
    "locations": ["Tel Aviv", "Remote"],
    "remote_policy": "hybrid",
    "min_salary": 30000,
    "currency": "ILS",
    "work_authorization": "Israeli citizen",
    "dealbreakers": ["gambling"],
    "resume_languages": ["en", "he"],
}


async def create_complete_seeker(client: httpx.AsyncClient) -> str:
    r = await client.post(
        "/v1/seekers",
        json={"external_ref": "test-1", "consent_recorded_at": "2026-07-16T08:00:00Z"},
    )
    assert r.status_code == 200, r.text
    seeker_id = r.json()["seeker_id"]
    r = await client.post(
        f"/v1/seekers/{seeker_id}/intake/turns",
        json={"profile_patch": PROFILE_PATCH, "preferences_patch": PREFERENCES_PATCH},
    )
    assert r.status_code == 200, r.text
    assert r.json()["intake_complete"], r.json()
    return seeker_id
