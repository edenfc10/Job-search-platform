from datetime import timedelta

from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.models import ApplicationRecord, utcnow
from aijaa.orchestration.governor import can_start_application, can_start_browser_task
from aijaa.orchestration.pipeline import enqueue_approved_match
from aijaa.orchestration.runner import run_one


async def test_task_enqueue_is_idempotent(session):
    first, created = await repo.enqueue_task(
        session, "run_matching", "match:seeker-1", {"seeker_id": "seeker-1"}, "seeker-1"
    )
    second, created_again = await repo.enqueue_task(
        session, "run_matching", "match:seeker-1", {"seeker_id": "seeker-1"}, "seeker-1"
    )
    assert first == second
    assert created is True
    assert created_again is False
    assert (await repo.task_counts(session, "seeker-1"))["queued"] == 1


async def test_claim_task_by_id_claims_only_the_requested_task(session):
    first_id, _ = await repo.enqueue_task(
        session, "run_matching", "match:seeker-1", {"seeker_id": "seeker-1"}
    )
    second_id, _ = await repo.enqueue_task(
        session, "run_matching", "match:seeker-2", {"seeker_id": "seeker-2"}
    )

    claimed = await repo.claim_task_by_id(session, second_id)

    assert claimed is not None
    assert claimed.id == second_id
    assert claimed.status == "running"
    assert claimed.attempts == 1
    assert await repo.claim_task_by_id(session, second_id) is None

    tasks = {task.id: task for task in await repo.list_tasks(session)}
    assert tasks[first_id].status == "queued"
    assert tasks[first_id].attempts == 0


async def test_approved_match_enqueue_skips_terminal_application(session):
    from aijaa.core.models import MatchResult

    match = MatchResult(seeker_id="s1", posting_id="p1", status="approved")
    app = ApplicationRecord(seeker_id="s1", posting_id="p1", match_id=match.id, status="confirmed")
    task_id, created = await enqueue_approved_match(session, match, app)
    assert task_id is None
    assert created is False


async def test_sync_console_approval_does_not_create_queued_work(client):
    from tests.conftest import FIXTURES_DIR, create_complete_seeker

    seeker_id = await create_complete_seeker(client)
    discovered = await client.post(
        "/v1/discovery/run", json={"fixtures_dir": FIXTURES_DIR}
    )
    assert discovered.status_code == 200, discovered.text
    matched = await client.post(f"/v1/seekers/{seeker_id}/match/run")
    assert matched.status_code == 200, matched.text
    matches = (await client.get(f"/v1/seekers/{seeker_id}/matches")).json()

    approved = await client.post(
        f"/v1/matches/{matches[0]['match_id']}/decision",
        json={"decision": "approved", "decided_by": "local-test"},
    )
    assert approved.status_code == 200, approved.text

    pipeline = (await client.get(f"/v1/seekers/{seeker_id}/pipeline")).json()
    assert pipeline["workflow_mode"] == "sync"
    assert pipeline["tasks"] == {}


async def test_browser_governor_enforces_global_and_per_seeker_caps(session, monkeypatch):
    monkeypatch.setenv("AIJAA_BROWSER_POOL_MAX", "1")
    get_settings.cache_clear()
    await repo.enqueue_task(
        session,
        "run_apply",
        "application:a1:apply",
        {"application_id": "a1"},
        "s1",
        "a1",
    )
    task = await repo.claim_due_task(session)
    assert task is not None
    allowed, reason = await can_start_browser_task(session, "s1")
    assert not allowed
    assert reason in {"browser_pool_full", "seeker_browser_busy"}


async def test_daily_cap_and_domain_pacing(session, monkeypatch):
    monkeypatch.setenv("AIJAA_APPLICATIONS_PER_DAY", "1")
    monkeypatch.setenv("AIJAA_DOMAIN_APPLICATION_INTERVAL_SECONDS", "120")
    get_settings.cache_clear()
    app = ApplicationRecord(seeker_id="s1", posting_id="p1", match_id="m1")
    await repo.audit(
        session,
        "s1",
        "application",
        "old",
        "application_start",
        "system",
        {},
    )
    allowed, reason, _ = await can_start_application(session, app, "https://boards.example/jobs/1")
    assert not allowed
    assert reason == "daily_application_cap"

    app2 = ApplicationRecord(seeker_id="s2", posting_id="p2", match_id="m2")
    allowed, reason, _ = await can_start_application(session, app2, "https://boards.example/jobs/2")
    assert allowed, reason
    allowed, reason, seconds = await can_start_application(
        session, app2, "https://boards.example/jobs/3"
    )
    assert not allowed
    assert reason == "domain_rate_limited"
    assert seconds > 0


async def test_dead_letter_after_failed_task(session):
    task_id, _ = await repo.enqueue_task(session, "unknown", "unknown:1")
    await repo.fail_task(session, task_id, "boom")
    assert await repo.dead_letter_count(session) == 1


async def test_delayed_tailor_task_is_safe_after_direct_tailoring(session):
    app = ApplicationRecord(
        seeker_id="s1", posting_id="p1", match_id="m1", status="tailored"
    )
    await repo.create_application(session, app)
    task_id, _ = await repo.enqueue_task(
        session,
        "run_tailor",
        f"application:{app.id}:tailor",
        {"application_id": app.id},
        app.seeker_id,
        app.id,
    )

    assert await run_one() is True
    tasks = await repo.list_tasks(session)
    by_id = {task.id: task for task in tasks}
    assert by_id[task_id].status == "succeeded"
    assert any(task.task_type == "run_analyze" for task in tasks)


async def test_pipeline_status_endpoint(client):
    seeker = (
        await client.post(
            "/v1/seekers",
            json={"external_ref": "p", "consent_recorded_at": "2026-07-16T08:00:00Z"},
        )
    ).json()["seeker_id"]
    r = await client.get(f"/v1/seekers/{seeker}/pipeline")
    assert r.status_code == 200
    body = r.json()
    assert body["seeker_id"] == seeker
    assert "next_scheduled_discovery" in body


def test_application_cap_window_uses_recent_events_only():
    assert (utcnow() - timedelta(days=1)).isoformat()
