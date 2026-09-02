import httpx

from aijaa.application.browser import HttpFormDriver
from aijaa.application.executor import confirm_submit
from aijaa.core import repo
from aijaa.core.db import init_db, session_factory
from aijaa.testkit.mockboard import create_mock_ats
from conftest import FIXTURES_DIR, create_complete_seeker


async def _ready_application(client, company: str):
    seeker_id = await create_complete_seeker(client)
    await client.post(f"/v1/seekers/{seeker_id}/resume", json={"language": "en"})
    await client.post("/v1/discovery/run", json={"fixtures_dir": FIXTURES_DIR})
    await client.post(f"/v1/seekers/{seeker_id}/match/run")
    matches = (await client.get(f"/v1/seekers/{seeker_id}/matches")).json()
    target = next(m for m in matches if m["posting"]["company"] == company)
    await client.post(
        f"/v1/matches/{target['match_id']}/decision",
        json={"decision": "approved", "decided_by": "qa"},
    )
    return seeker_id, target["match_id"]


async def test_mockboard_greenhouse_feed_serves_twenty_jobs():
    transport = httpx.ASGITransport(app=create_mock_ats())
    async with httpx.AsyncClient(transport=transport, base_url="http://mock") as c:
        r = await c.get("/v1/boards/mock/jobs")
    assert r.status_code == 200
    assert len(r.json()["jobs"]) == 20


async def test_mockboard_live_submit_records_exactly_once(client, monkeypatch):
    from aijaa.application import service
    from aijaa.core.db import reset_for_tests

    _, match_id = await _ready_application(client, "Cloudify")
    await init_db()
    async with session_factory()() as s:
        app = await repo.get_application_for_match(s, match_id)
        posting = await repo.get_posting(s, app.posting_id)
        posting.apply_url = "http://mock/forms/single"
        await repo.update_posting(s, posting)

        mock = create_mock_ats()
        transport = httpx.ASGITransport(app=mock)
        mock_client = httpx.AsyncClient(transport=transport, base_url="http://mock")
        driver = HttpFormDriver(mock_client)
        app = await service.run_application(s, app.id, driver=driver)
        assert app.status == "ready_to_submit"

    monkeypatch.setenv("AIJAA_DRY_RUN", "false")
    reset_for_tests()
    await init_db()
    async with session_factory()() as s:
        app = await repo.get_application(s, app.id)
        result = await confirm_submit(s, app, driver, "qa", "/tmp/aijaa_e2e_submit")
    await mock_client.aclose()

    assert result.status == "confirmed"
    assert len(mock.state.submissions) == 1


async def test_mockboard_captcha_never_submits(client):
    from aijaa.application import service

    _, match_id = await _ready_application(client, "Cloudify")
    await init_db()
    async with session_factory()() as s:
        app = await repo.get_application_for_match(s, match_id)
        posting = await repo.get_posting(s, app.posting_id)
        posting.apply_url = "http://mock/forms/captcha"
        await repo.update_posting(s, posting)
        mock = create_mock_ats()
        transport = httpx.ASGITransport(app=mock)
        mock_client = httpx.AsyncClient(transport=transport, base_url="http://mock")
        driver = HttpFormDriver(mock_client)
        result = await service.run_application(s, app.id, driver=driver)
        await mock_client.aclose()

    assert result.status == "needs_human"
    assert "captcha_present" in result.needs_human_reason
    assert mock.state.submissions == []
