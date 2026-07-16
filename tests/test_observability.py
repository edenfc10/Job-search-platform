from aijaa.observability.logging import redact_processor


def test_redaction_processor_scrubs_configured_keys():
    event = redact_processor(
        None,
        "info",
        {
            "email": "dana@example.com",
            "nested": {"phone": "+972", "ok": "visible"},
            "items": [{"webhook_signing_secret": "secret"}],
        },
    )
    assert event["email"] == "[redacted]"
    assert event["nested"]["phone"] == "[redacted]"
    assert event["nested"]["ok"] == "visible"
    assert event["items"][0]["webhook_signing_secret"] == "[redacted]"


async def test_metrics_endpoint_and_usage_rollups(client, session):
    from aijaa.core import repo

    seeker = (
        await client.post(
            "/v1/seekers",
            json={"external_ref": "u", "consent_recorded_at": "2026-07-16T08:00:00Z"},
        )
    ).json()["seeker_id"]
    await repo.add_llm_usage(session, seeker, "matcher", "fake", 10, 5)

    metrics = await client.get("/metrics")
    assert metrics.status_code == 200
    assert "aijaa_llm_tokens_total" in metrics.text

    seeker_usage = await client.get(f"/v1/seekers/{seeker}/usage?window=30d")
    assert seeker_usage.json()[0]["input_tokens"] == 10

    global_usage = await client.get("/v1/usage?window=30d")
    assert any(row["seeker_id"] == seeker for row in global_usage.json())


async def test_timeline_events_are_chronological(client, session):
    from aijaa.core import repo
    from aijaa.core.models import ApplicationRecord, Evidence, JobPosting, utcnow

    seeker = await repo.create_seeker(session, "timeline", utcnow())
    posting = JobPosting(
        source="t", canonical_url="https://x.example/timeline", company="X", title="Engineer"
    )
    posting_id, _ = await repo.upsert_posting(session, posting)
    app = ApplicationRecord(seeker_id=seeker, posting_id=posting_id, match_id="m1")
    app.evidence.append(Evidence(kind="note", value="created"))
    await repo.create_application(session, app)
    await repo.transition_application(session, app, "matched", "system")

    r = await client.get(f"/v1/applications/{app.id}/timeline")
    assert r.status_code == 200
    events = r.json()["events"]
    assert [e["ts"] for e in events] == sorted(e["ts"] for e in events)
    assert {e["kind"] for e in events} >= {"status", "audit", "evidence"}
