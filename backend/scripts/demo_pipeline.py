"""End-to-end demo of the AIJAA pipeline against fixtures, using fake LLMs and
the local HTTP driver — no API usage, no network. Prints each stage so QA can
watch the whole flow: intake -> resume -> discovery -> match -> approve ->
handoff -> tailor -> analyze -> fill (stops at the pre-submit gate) ->
confirm-submit (dry-run suppressed).

Run:  AIJAA_DATABASE_URL=sqlite+aiosqlite:///./demo.db \
      AIJAA_ARTIFACTS_DIR=./demo_artifacts uv run python backend/scripts/demo_pipeline.py
"""

import asyncio
import os

os.environ.setdefault("AIJAA_DATABASE_URL", "sqlite+aiosqlite:///./demo.db")
os.environ.setdefault("AIJAA_ARTIFACTS_DIR", "./demo_artifacts")
os.environ.setdefault("AIJAA_FAKE_LLM", "true")
os.environ.setdefault("AIJAA_DRY_RUN", "true")

from datetime import UTC, datetime  # noqa: E402

import httpx  # noqa: E402

from aijaa.application import service  # noqa: E402
from aijaa.application.browser import HttpFormDriver  # noqa: E402
from aijaa.core import repo  # noqa: E402
from aijaa.core.db import init_db, session_factory  # noqa: E402
from aijaa.discovery.runner import run_discovery  # noqa: E402
from aijaa.discovery.sources.fixture import FixtureSource  # noqa: E402
from aijaa.intake.engine import IntakeTurnRequest, run_turn  # noqa: E402
from aijaa.matching.service import run_matching  # noqa: E402
from aijaa.resume.service import build_master_resume  # noqa: E402
from aijaa.testkit.mockboard import create_mock_ats  # noqa: E402

HERE = os.path.dirname(__file__)
FIXTURES = os.path.join(HERE, "..", "fixtures", "postings")

PROFILE = {
    "contact": {"full_name": "Dana Levi", "email": "dana@example.com",
                "phone": "+972-50-1234567", "location": "Tel Aviv, Israel",
                "links": ["https://linkedin.com/in/danalevi"]},
    "work_history": [{
        "company": "CloudWorks", "title": "Senior Backend Engineer", "start": "2021-03",
        "achievements": [
            {"fact_id": "f1", "text": "Reduced API p95 latency by 40% by rearchitecting the caching layer in Python and Redis", "quantified": True},
            {"fact_id": "f2", "text": "Led a team of 5 engineers building FastAPI microservices on Kubernetes serving 2M users", "quantified": True},
        ]}],
    "skills": [{"fact_id": f"s{i}", "text": t} for i, t in enumerate(
        ["Python", "FastAPI", "PostgreSQL", "Kubernetes", "AWS", "Docker", "Redis"])],
    "education": [{"institution": "Tel Aviv University", "degree": "B.Sc.", "field": "CS", "year": "2018"}],
}
PREFS = {"target_titles": ["Senior Backend Engineer"], "seniority": "senior",
         "locations": ["Tel Aviv", "Remote"], "remote_policy": "hybrid",
         "min_salary": 30000, "currency": "ILS", "work_authorization": "Israeli citizen",
         "dealbreakers": ["gambling"], "resume_languages": ["en", "he"]}


def hr(title):
    print(f"\n{'='*66}\n {title}\n{'='*66}")


async def main():
    await init_db()
    async with session_factory()() as s:
        hr("1. INTAKE")
        seeker_id = await repo.create_seeker(s, "demo", datetime.now(UTC))
        resp = await run_turn(s, seeker_id, IntakeTurnRequest(
            profile_patch=PROFILE, preferences_patch=PREFS))
        print(f"   seeker={seeker_id[:8]}  completeness={resp.overall_completeness} "
              f"complete={resp.intake_complete}")

        hr("2. RESUME (bilingual)")
        for lang in ("en", "he"):
            doc = await build_master_resume(s, seeker_id, lang)
            print(f"   [{lang}] docx={os.path.relpath(doc.artifacts['docx'])}")

        hr("3. DISCOVERY")
        stats = await run_discovery(s, [FixtureSource(FIXTURES)])
        print(f"   {stats}")

        hr("4. MATCHING (7/10 floor, dealbreaker filter)")
        mstats = await run_matching(s, seeker_id)
        print(f"   {mstats}")
        matches = await repo.list_matches(s, seeker_id, "pending")
        for m in matches:
            p = await repo.get_posting(s, m.posting_id)
            print(f"   [{m.rerank_score:3d}] {p.company:12s} {p.title:32s} risks={m.risks}")

        hr("5. APPROVAL + RECRUITER HANDOFF")
        target = next(m for m in matches if m.rerank_score == max(x.rerank_score for x in matches))
        target.status, target.decided_by = "approved", "recruiter@demo"
        target.decided_at = datetime.now(UTC)
        await repo.save_match(s, target)
        app = await repo.get_application_for_match(s, target.id)
        await repo.transition_application(s, app, "approved", "operator:recruiter@demo")
        # Point this posting's apply flow at the in-process mock ATS.
        posting = await repo.get_posting(s, target.posting_id)
        posting.apply_url = "http://mock/forms/greenhouse_simple"
        await repo.update_posting(s, posting)
        print(f"   approved {target.id[:8]} by recruiter@demo")

        # Driver bound to the mock ATS via ASGI — no network, no ports.
        transport = httpx.ASGITransport(app=create_mock_ats())
        mock_client = httpx.AsyncClient(transport=transport, base_url="http://mock",
                                        follow_redirects=True)
        driver = HttpFormDriver(mock_client)

        hr("6. APPLICATION ENGINE (tailor -> analyze -> fill -> gate)")
        app = await service.run_application(s, app.id, driver=driver)
        print(f"   status={app.status}  (DRY_RUN: stops before submit)")
        print(f"   plan: platform={app.plan['platform']} confidence={app.plan['confidence']}")
        print(f"   evidence kinds: {sorted({e.kind for e in app.evidence})}")

        hr("7. CONFIRM-SUBMIT (dry-run suppressed)")
        result = await service.confirm_and_submit(s, app.id, "recruiter@demo", driver=driver)
        print(f"   status={result.status}  submit_suppressed={any(e.kind=='dry_run' for e in result.evidence)}")
        await mock_client.aclose()

        hr("DONE — full pipeline exercised with zero API usage")


if __name__ == "__main__":
    asyncio.run(main())
