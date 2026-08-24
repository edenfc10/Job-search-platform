import json
import os
import tempfile
from datetime import UTC, datetime, timedelta

import httpx
import pytest

import aijaa.core.db as db
import aijaa.llm.factory as llm_factory


@pytest.fixture(autouse=True)
async def isolated_env(tmp_path, monkeypatch):
    await db.dispose_for_tests()
    monkeypatch.setenv("AIJAA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("AIJAA_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("AIJAA_FAKE_LLM", "true")
    monkeypatch.setenv("AIJAA_DRY_RUN", "true")
    db.reset_for_tests()
    llm_factory.reset_for_tests()
    yield
    await db.dispose_for_tests()
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


def _days_ago(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).isoformat()


def _fresh_postings_dir() -> str:
    """Postings dated relative to whenever the suite actually runs, not a
    hardcoded absolute date — a static fixture with fixed dates silently ages
    out of the 21-day freshness window as real time passes. Same companies/
    titles/keywords as the original fixture; only the dates are computed."""
    postings = [
        {
            "source": "fixture",
            "url": "https://boards.example.com/cloudify/senior-backend-engineer?utm_source=feed",
            "company": "Cloudify",
            "title": "Senior Backend Engineer",
            "location": "Tel Aviv, Israel",
            "remote": True,
            "description_html_or_text": "<p>We are hiring a Senior Backend Engineer. Required: Python, FastAPI, PostgreSQL, Kubernetes, Docker, AWS. You will build microservices, improve API latency, and lead engineers. Redis experience is a plus. Salary ₪32,000 - ₪42,000 monthly. Hybrid from Tel Aviv or remote.</p>",
            "posted_at_iso": _days_ago(6),
        },
        {
            "source": "fixture",
            "url": "https://boards.example.com/datastream/backend-engineer",
            "company": "DataStream",
            "title": "Backend Engineer (Python)",
            "location": "Remote",
            "remote": True,
            "description_html_or_text": "Backend Engineer needed. Must have Python and PostgreSQL. Nice to have: Kubernetes, AWS, Docker, Redis, ETL pipelines, microservices at scale. Senior engineers welcome.",
            "posted_at_iso": _days_ago(2),
        },
        {
            "source": "fixture",
            "url": "https://boards.example.com/medcare/registered-nurse",
            "company": "MedCare",
            "title": "Registered Nurse",
            "location": "Haifa, Israel",
            "description_html_or_text": "Registered Nurse for the cardiology department. Nursing license required. Shift work. Patient care experience essential.",
            "posted_at_iso": _days_ago(4),
        },
        {
            "source": "fixture",
            "url": "https://boards.example.com/oldco/python-developer",
            "company": "OldCo",
            "title": "Python Developer",
            "location": "Tel Aviv",
            "description_html_or_text": "Python developer with PostgreSQL and AWS. Docker, Kubernetes and FastAPI experience required. Microservices architecture.",
            "posted_at_iso": _days_ago(200),  # always outside the 21-day window
        },
        {
            "source": "fixture",
            "url": "https://boards.example.com/betwin/backend-engineer",
            "company": "BetWin",
            "title": "Senior Backend Engineer",
            "location": "Tel Aviv",
            "description_html_or_text": "Senior Backend Engineer for our online gambling platform. Python, FastAPI, PostgreSQL, Kubernetes, AWS, Docker, Redis, microservices.",
            "posted_at_iso": _days_ago(3),
        },
        {
            "source": "fixture",
            "url": "https://boards.example.com/cloudify/senior-backend-engineer?utm_campaign=x",
            "company": "Cloudify",
            "title": "Senior Backend Engineer",
            "location": "Tel Aviv, Israel",
            "remote": True,
            "description_html_or_text": "Duplicate listing of the Cloudify role via another feed. Python, FastAPI, PostgreSQL, Kubernetes.",
            "posted_at_iso": _days_ago(6),
        },
    ]
    d = tempfile.mkdtemp(prefix="aijaa_fixture_postings_")
    with open(os.path.join(d, "batch1.json"), "w", encoding="utf-8") as f:
        json.dump(postings, f)
    return d


FIXTURES_DIR = _fresh_postings_dir()


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
