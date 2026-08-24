import json

from aijaa.discovery.base import RawPosting
from aijaa.discovery.normalize import canonical_url, normalize, parse_salary
from aijaa.discovery.sources.fixture import FixtureSource


async def test_fake_matcher_does_not_treat_manager_as_domain_fit():
    from aijaa.core.models import (
        CareerPreferences,
        Contact,
        JobPosting,
        ProfessionalProfile,
        ProfileFact,
        WorkExperience,
    )
    from aijaa.llm.fakes import FakeRerankLLM

    profile = ProfessionalProfile(
        seeker_id="s",
        contact=Contact(full_name="Real Person", email="real@example.org"),
        work_history=[WorkExperience(company="A", title="Manager", start="2020")],
        skills=[ProfileFact(fact_id="s1", text="Excel", kind="skill")],
    )
    prefs = CareerPreferences(seeker_id="s", target_titles=["Manager"])
    posting = JobPosting(
        source="fixture",
        canonical_url="https://jobs.example/legal",
        company="Legal Co",
        title="Regulation Manager",
        description_text="Government relations, legal policy and regulatory compliance",
        content_hash="legal",
    )
    [result] = await FakeRerankLLM().rerank(profile, prefs, [posting])
    assert result.score < 70


def test_canonical_url_strips_tracking():
    assert canonical_url("https://X.example.com/job/1/?utm_source=a&gh_src=b&x=1") == (
        "https://x.example.com/job/1?x=1"
    )


def test_salary_parsing():
    assert parse_salary("₪32,000 - ₪42,000 monthly") == (32000, 42000)
    assert parse_salary("$120,000 to $150,000") == (120000, 150000)
    assert parse_salary("competitive pay") == (None, None)


def test_normalize_drops_stale():
    raw = RawPosting(
        source="t", url="https://a.example/1", company="A", title="Eng",
        description_html_or_text="x", posted_at_iso="2025-01-01T00:00:00+00:00",
    )
    assert normalize(raw, posted_within_days=21) is None


def test_normalize_infers_missing_date():
    raw = RawPosting(
        source="t", url="https://a.example/1", company="A", title="Eng",
        description_html_or_text="<b>Python</b> role",
    )
    p = normalize(raw, 21)
    assert p is not None and p.posted_at_inferred
    assert p.description_text == "Python role"


async def test_fixture_relative_date_does_not_expire(tmp_path):
    fixture = tmp_path / "jobs.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "source": "fixture",
                    "url": "https://jobs.example/1",
                    "company": "A",
                    "title": "Counsel",
                    "description_html_or_text": "Legal role",
                    "posted_days_ago": 2,
                }
            ]
        ),
        encoding="utf-8",
    )
    raws = await FixtureSource(str(tmp_path)).fetch(None)
    assert len(raws) == 1
    assert normalize(raws[0], posted_within_days=21) is not None


async def test_discovery_uses_current_request_port_for_mock_forms(client, session):
    from tests.conftest import FIXTURES_DIR

    from aijaa.core import repo

    response = await client.post("/v1/discovery/run", json={"fixtures_dir": FIXTURES_DIR})
    assert response.status_code == 200, response.text
    postings = await repo.list_postings(session)
    assert postings
    assert all(posting.apply_url.startswith("http://test/mockboard/forms/") for posting in postings)


async def test_legal_cv_surfaces_legal_fixture(client):
    cv = """Daniel Cohen
Lawyer, Tel Aviv, Israel
daniel@example.com
SKILLS
Government Relations
Regulation
Legal Consulting
Litigation
Legislation
Public Policy
Stakeholder Management
Compliance
LANGUAGES
Hebrew
English
PROFILE
Experienced lawyer targeting a Regulation and Government Relations Manager role.
EMPLOYMENT HISTORY
Regulation Manager, Trade Association
2019 — Present
• Represented clients before government authorities and Knesset committees
EDUCATION
2010 - 2014 | LLB Bachelor of Laws, Reichman University
"""
    interpreted = (await client.post("/v1/cv/interpret", json={"text": cv})).json()
    seeker = await client.post(
        "/v1/seekers",
        json={"external_ref": "legal-e2e", "consent_recorded_at": "2026-08-11T00:00:00Z"},
    )
    seeker_id = seeker.json()["seeker_id"]
    saved = await client.post(
        f"/v1/seekers/{seeker_id}/intake/turns",
        json={
            "profile_patch": interpreted["profile_patch"],
            "preferences_patch": interpreted["preferences_patch"],
        },
    )
    assert saved.status_code == 200, saved.text

    discovered = await client.post(
        "/v1/discovery/run", json={"fixtures_dir": "fixtures/postings"}
    )
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["stale_dropped"] == 1

    matched = await client.post(f"/v1/seekers/{seeker_id}/match/run")
    assert matched.status_code == 200, matched.text
    assert matched.json()["matches_created"] >= 1
    results = (await client.get(f"/v1/seekers/{seeker_id}/matches")).json()
    assert "Public Affairs Group" in {item["posting"]["company"] for item in results}


async def test_full_mvp_flow(client):
    """Intake -> resume -> discovery -> matching (floor + freshness + dedupe)
    -> approval -> handoff packet. The MVP slice, end to end."""
    from tests.conftest import FIXTURES_DIR, create_complete_seeker

    seeker_id = await create_complete_seeker(client)

    r = await client.post(f"/v1/seekers/{seeker_id}/resume", json={"language": "en"})
    assert r.status_code == 200

    r = await client.post("/v1/discovery/run", json={"fixtures_dir": FIXTURES_DIR})
    assert r.status_code == 200, r.text
    stats = r.json()
    assert stats["fetched"] == 6
    assert stats["stale_dropped"] == 1          # OldCo posting from 2025
    assert stats["created"] == 4                # canonical-url dupe collapses
    assert stats["updated"] == 1

    r = await client.post(f"/v1/seekers/{seeker_id}/match/run")
    assert r.status_code == 200, r.text
    mstats = r.json()
    assert mstats["matches_created"] >= 2

    r = await client.get(f"/v1/seekers/{seeker_id}/matches", params={"status": "pending"})
    matches = r.json()
    companies = {m["posting"]["company"] for m in matches}
    assert "MedCare" not in companies            # nurse job withheld below floor
    assert "BetWin" not in companies             # dealbreaker 'gambling' hard-filtered
    assert "Cloudify" in companies
    assert all(m["score"] >= 70 for m in matches)

    # decisions: attributable, immutable, idempotent
    target = next(m for m in matches if m["posting"]["company"] == "Cloudify")
    r = await client.post(
        f"/v1/matches/{target['match_id']}/decision",
        json={"decision": "approved", "decided_by": "recruiter@myrecruiter", "note": "great fit"},
    )
    assert r.status_code == 200
    r = await client.post(
        f"/v1/matches/{target['match_id']}/decision",
        json={"decision": "approved", "decided_by": "recruiter@myrecruiter"},
    )
    assert r.json().get("idempotent") is True
    r = await client.post(
        f"/v1/matches/{target['match_id']}/decision",
        json={"decision": "rejected", "decided_by": "someone-else"},
    )
    assert r.status_code == 409                 # immutable once decided

    # handoff packet for the recruiter
    r = await client.get(f"/v1/matches/{target['match_id']}/handoff")
    assert r.status_code == 200, r.text
    packet = r.json()
    assert packet["seeker"]["name"] == "Dana Levi"
    assert packet["job"]["company"] == "Cloudify"
    assert packet["match"]["approved_by"] == "recruiter@myrecruiter"
    assert packet["resume"]["artifacts"].get("docx")
    assert packet["application_status"] == "approved"

    # rejected match cannot produce a handoff
    other = next(m for m in matches if m["match_id"] != target["match_id"])
    r = await client.post(
        f"/v1/matches/{other['match_id']}/decision",
        json={"decision": "rejected", "decided_by": "recruiter@myrecruiter"},
    )
    assert r.status_code == 200
    r = await client.get(f"/v1/matches/{other['match_id']}/handoff")
    assert r.status_code == 409


async def test_gate_blocks_without_approval(client, session):
    import pytest
    from tests.conftest import FIXTURES_DIR, create_complete_seeker

    from aijaa.application.gate import ApprovalMissing, require_approval
    from aijaa.core import repo

    seeker_id = await create_complete_seeker(client)
    await client.post("/v1/discovery/run", json={"fixtures_dir": FIXTURES_DIR})
    await client.post(f"/v1/seekers/{seeker_id}/match/run")
    apps = await repo.list_applications(session, seeker_id)
    assert apps
    with pytest.raises(ApprovalMissing):
        await require_approval(session, apps[0])
