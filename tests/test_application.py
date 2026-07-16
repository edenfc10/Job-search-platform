"""Application engine: analyzer, executor (pre-submit gate, CAPTCHA stop,
human handoff), validator (confirmation + no-double-submit)."""


from tests.conftest import FIXTURES_DIR, create_complete_seeker
from tests.fixture_driver import FORMS_DIR, FixtureDriver

from aijaa.application import service
from aijaa.application.fingerprint import fingerprint
from aijaa.application.forms import detect_interrupts, extract_form
from aijaa.application.validator import retry_decision
from aijaa.core import repo
from aijaa.core.db import reset_for_tests as reset_db


def _read(name: str) -> str:
    import os

    with open(os.path.join(FORMS_DIR, name), encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- unit tests

def test_fingerprint_table():
    assert fingerprint("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
    assert fingerprint("https://jobs.lever.co/acme/1") == "lever"
    assert fingerprint("https://acme.myworkdayjobs.com/x") == "workday"
    assert fingerprint("https://acme.icims.com/jobs/1") == "icims"
    assert fingerprint("https://custom.example.com/apply", "<form></form>") == "custom_form"
    assert fingerprint("https://x.example.com/nope") == "unknown"


def test_interrupt_detection():
    assert "captcha_present" in detect_interrupts(_read("captcha_wall.html"))
    assert detect_interrupts(_read("greenhouse_simple.html")) == []
    assert "login_required" in detect_interrupts('<input type="password" name="pw">')
    assert "posting_closed" in detect_interrupts("<p>This position has been filled.</p>")


def test_form_extraction_and_classification():
    from aijaa.application.answers import classify_field

    form = extract_form(_read("greenhouse_simple.html"))
    assert form is not None
    names = {f.name for f in form.fields}
    assert {"full_name", "email", "phone", "resume", "why"} <= names
    assert "csrf" not in names or next(f for f in form.fields if f.name == "csrf").type == "hidden"
    by_name = {f.name: classify_field(f) for f in form.fields}
    assert by_name["full_name"].source == "auto:full_name"
    assert by_name["email"].source == "auto:email"
    assert by_name["resume"].source == "attach_resume"
    assert by_name["why"].source == "generate"


def test_retry_decision_table():
    # post-submit click: always needs_human, never retry
    for kind in ("network", "timeout", "http_5xx", "unknown"):
        assert retry_decision("post_submit_click", kind).action == "needs_human"
    # pre-submit transient -> retry
    for kind in ("network", "timeout", "http_5xx"):
        assert retry_decision("pre_submit", kind).action == "retry"
    # pre-submit definitive -> fail
    assert retry_decision("pre_submit", "posting_closed").action == "fail"
    # pre-submit unclassified -> needs_human
    assert retry_decision("pre_submit", "weird").action == "needs_human"


# ---------------------------------------------------- end-to-end engine tests

async def _approved_application(client, session, company: str):
    """Drive the MVP flow to an approved application for a given company."""
    seeker_id = await create_complete_seeker(client)
    await client.post(f"/v1/seekers/{seeker_id}/resume", json={"language": "en"})
    await client.post("/v1/discovery/run", json={"fixtures_dir": FIXTURES_DIR})
    await client.post(f"/v1/seekers/{seeker_id}/match/run")
    matches = (await client.get(f"/v1/seekers/{seeker_id}/matches",
                                params={"status": "pending"})).json()
    target = next(m for m in matches if m["posting"]["company"] == company)
    await client.post(
        f"/v1/matches/{target['match_id']}/decision",
        json={"decision": "approved", "decided_by": "recruiter@x"},
    )
    reset_db()  # new engine/session below reads the same sqlite file
    return seeker_id, target["match_id"]


async def _run_with_driver(seeker_id, match_id, driver):
    from aijaa.core.db import init_db, session_factory

    await init_db()
    async with session_factory()() as s:
        app = await repo.get_application_for_match(s, match_id)
        return await service.run_application(s, app.id, driver=driver), app.id


async def test_simple_form_fills_and_stops_at_gate(client, session):
    seeker_id, match_id = await _approved_application(client, session, "Cloudify")
    driver = FixtureDriver("greenhouse_simple.html")
    app, app_id = await _run_with_driver(seeker_id, match_id, driver)
    # DRY_RUN: fills everything, stops at ready_to_submit — never auto-submits
    assert app.status == "ready_to_submit", app.timeline
    assert driver.submit_calls == 0
    kinds = {e.kind for e in app.evidence}
    assert "review_packet" in kinds and "screenshot" in kinds
    assert app.plan["platform"] == "greenhouse"
    assert app.plan["confidence"] == "high"


async def test_captcha_stops_without_bypass(client, session):
    # Point the Cloudify posting's apply flow at a CAPTCHA wall via fixture.
    seeker_id, match_id = await _approved_application(client, session, "Cloudify")
    driver = FixtureDriver("captcha_wall.html")
    app, _ = await _run_with_driver(seeker_id, match_id, driver)
    assert app.status == "needs_human"
    assert "captcha_present" in app.needs_human_reason
    assert driver.submit_calls == 0  # never attempts the form


async def test_comp_question_pauses_then_resumes(client, session):
    from aijaa.core.db import init_db, session_factory

    seeker_id, match_id = await _approved_application(client, session, "DataStream")
    driver = FixtureDriver("comp_question.html")
    app, app_id = await _run_with_driver(seeker_id, match_id, driver)
    # salary field routes to needs_human
    assert app.status == "needs_human"
    assert any(q["field"] == "salary" for q in app.pending_questions)

    # human provides the answer -> resumes -> ready_to_submit
    await init_db()
    async with session_factory()() as s:
        resumed = await service.provide_human_input(
            s, app_id, {"salary": "₪35,000/month"}, "recruiter@x", driver=driver
        )
    assert resumed.status == "ready_to_submit"


async def test_dry_run_submit_suppressed(client, session):
    from aijaa.core.db import init_db, session_factory

    seeker_id, match_id = await _approved_application(client, session, "Cloudify")
    driver = FixtureDriver("greenhouse_simple.html")
    app, app_id = await _run_with_driver(seeker_id, match_id, driver)
    assert app.status == "ready_to_submit"
    # confirm-submit under DRY_RUN must NOT click submit
    await init_db()
    async with session_factory()() as s:
        result = await service.confirm_and_submit(s, app_id, "recruiter@x")
    assert result.status == "applying"  # returned to applying, submit suppressed
    assert any(e.kind == "dry_run" for e in result.evidence)


async def test_live_submit_confirms(client, session, monkeypatch):
    from aijaa.core.db import init_db, session_factory

    seeker_id, match_id = await _approved_application(client, session, "Cloudify")
    driver = FixtureDriver("greenhouse_simple.html", submit_result="confirm")
    app, app_id = await _run_with_driver(seeker_id, match_id, driver)

    monkeypatch.setenv("AIJAA_DRY_RUN", "false")
    reset_db()
    await init_db()
    async with session_factory()() as s:
        from aijaa.application.executor import confirm_submit

        app2 = await repo.get_application(s, app_id)
        result = await confirm_submit(s, app2, driver, "recruiter@x", "/tmp/aijaa_qa/submit")
    assert result.status == "confirmed"
    assert result.confirmation_ref == "APP-2026-77123"
    assert driver.submit_calls == 1  # exactly one submit


async def test_ambiguous_submit_never_retries(client, session, monkeypatch):
    from aijaa.application.executor import confirm_submit
    from aijaa.core.db import init_db, session_factory

    seeker_id, match_id = await _approved_application(client, session, "Cloudify")
    driver = FixtureDriver("greenhouse_simple.html", raise_on_submit=True)
    app, app_id = await _run_with_driver(seeker_id, match_id, driver)

    monkeypatch.setenv("AIJAA_DRY_RUN", "false")
    reset_db()
    await init_db()
    async with session_factory()() as s:
        app2 = await repo.get_application(s, app_id)
        result = await confirm_submit(s, app2, driver, "recruiter@x", "/tmp/aijaa_qa/amb")
    assert result.status == "needs_human"
    assert "possibly_submitted" in result.needs_human_reason
    assert driver.submit_calls == 1  # the click was attempted once, never retried
