import pytest

from aijaa.core import repo
from aijaa.core.models import (
    ApplicationRecord,
    CareerPreferences,
    JobPosting,
    ProfessionalProfile,
    utcnow,
)
from aijaa.core.status import (
    ApplicationStatus,
    IllegalTransition,
    transition_entry,
)


def test_legal_full_path():
    path = [
        "discovered", "matched", "approved", "tailored", "applying",
        "ready_to_submit", "submitted", "confirmed",
    ]
    for cur, nxt in zip(path, path[1:], strict=False):
        entry = transition_entry(cur, nxt, actor="test")
        assert entry["from"] == cur and entry["to"] == nxt


def test_pre_submit_gate_paths():
    # ready_to_submit can bounce back to applying (reviewer asked for re-fill)
    transition_entry("ready_to_submit", "applying", "operator:qa")
    # needs_human can resolve a possibly-submitted as submitted
    transition_entry("needs_human", "submitted", "operator:qa")


@pytest.mark.parametrize(
    "cur,nxt",
    [
        ("discovered", "approved"),      # cannot skip matching
        ("matched", "applying"),         # cannot skip approval  <- the gate
        ("approved", "submitted"),       # cannot skip tailoring/filling
        ("applying", "submitted"),       # cannot submit without ready_to_submit
        ("confirmed", "failed"),         # terminal is terminal
        ("failed", "applying"),
    ],
)
def test_illegal_transitions(cur, nxt):
    with pytest.raises(IllegalTransition):
        transition_entry(cur, nxt, actor="test")


async def test_repo_tenancy_and_idempotency(session):
    s1 = await repo.create_seeker(session, "a", utcnow())
    s2 = await repo.create_seeker(session, "b", utcnow())
    await repo.save_profile(session, s1, ProfessionalProfile(seeker_id=s1))
    assert await repo.latest_profile(session, s2) is None

    posting = JobPosting(
        source="t", canonical_url="https://x.example/j1", company="X", title="Engineer",
        content_hash="h1",
    )
    pid, created = await repo.upsert_posting(session, posting)
    assert created
    _, created2 = await repo.upsert_posting(session, posting)
    assert not created2

    app = ApplicationRecord(seeker_id=s1, posting_id=pid, match_id="m1")
    assert await repo.create_application(session, app) is not None
    dupe = ApplicationRecord(seeker_id=s1, posting_id=pid, match_id="m2")
    assert await repo.create_application(session, dupe) is None  # never double-apply


async def test_transition_writes_timeline_and_audit(session):
    seeker = await repo.create_seeker(session, "a", utcnow())
    posting = JobPosting(
        source="t", canonical_url="https://x.example/j2", company="X", title="Engineer",
        content_hash="h2",
    )
    pid, _ = await repo.upsert_posting(session, posting)
    app = ApplicationRecord(seeker_id=seeker, posting_id=pid, match_id="m1")
    await repo.create_application(session, app)
    await repo.transition_application(session, app, ApplicationStatus.matched.value, "system")
    fetched = await repo.get_application(session, app.id)
    assert fetched.status == "matched"
    assert fetched.timeline[-1]["to"] == "matched"
    audit = await repo.audit_for_entity(session, seeker, app.id)
    assert any("status:discovered->matched" in a["event"] for a in audit)


def test_profile_staleness():
    from datetime import timedelta

    p = ProfessionalProfile(seeker_id="x")
    assert not repo.profile_is_stale(p, 90)
    p.updated_at = utcnow() - timedelta(days=120)
    assert repo.profile_is_stale(p, 90)


def test_preferences_defaults():
    prefs = CareerPreferences(seeker_id="x")
    assert prefs.resume_languages == ["en"]
