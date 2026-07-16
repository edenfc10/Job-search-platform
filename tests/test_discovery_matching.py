from aijaa.discovery.base import RawPosting
from aijaa.discovery.normalize import canonical_url, normalize, parse_salary


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
