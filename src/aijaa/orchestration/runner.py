"""In-process DB-backed task runner for the reference build."""

import traceback

import structlog

from aijaa.application import service as application_service
from aijaa.core import repo
from aijaa.core.db import session_factory
from aijaa.discovery.base import SearchCriteria
from aijaa.discovery.runner import run_discovery
from aijaa.discovery.sources.fixture import FixtureSource
from aijaa.discovery.sources.greenhouse import GreenhouseBoardSource
from aijaa.discovery.sources.lever import LeverPostingsSource
from aijaa.matching.service import run_matching
from aijaa.orchestration.governor import can_start_application, can_start_browser_task
from aijaa.orchestration.pipeline import enqueue_matching

log = structlog.get_logger()


async def run_one() -> bool:
    async with session_factory()() as s:
        task = await repo.claim_due_task(s)
        if task is None:
            return False
        try:
            await _execute_task(s, task)
            await repo.complete_task(s, task.id)
            return True
        except _RetryLater as retry:
            await repo.fail_task(s, task.id, retry.reason, retry.seconds)
            return True
        except Exception as e:  # noqa: BLE001 - task failure must be captured
            log.warning("task_failed", task_id=task.id, task_type=task.task_type, error=str(e))
            await repo.fail_task(s, task.id, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            return True


async def drain(max_tasks: int = 100) -> int:
    ran = 0
    while ran < max_tasks and await run_one():
        ran += 1
    return ran


class _RetryLater(Exception):
    def __init__(self, reason: str, seconds: int = 60):
        self.reason = reason
        self.seconds = seconds
        super().__init__(reason)


async def _execute_task(s, task) -> None:
    payload = task.payload or {}
    if task.task_type == "run_discovery":
        sources = []
        if payload.get("fixtures_dir"):
            sources.append(FixtureSource(payload["fixtures_dir"]))
        if payload.get("greenhouse_orgs"):
            sources.append(GreenhouseBoardSource(payload["greenhouse_orgs"]))
        if payload.get("lever_orgs"):
            sources.append(LeverPostingsSource(payload["lever_orgs"]))
        criteria = None
        if payload.get("posted_within_days"):
            criteria = SearchCriteria(posted_within_days=payload["posted_within_days"])
        stats = await run_discovery(s, sources, criteria)
        await repo.audit(s, "", "task", task.id, "discovery_completed", "system", stats)
        for seeker_id in payload.get("seeker_ids", []):
            await enqueue_matching(s, seeker_id)
        return

    if task.task_type == "run_matching":
        await run_matching(s, payload["seeker_id"])
        return

    if task.task_type == "run_tailor":
        app = await _load_app(s, payload["application_id"])
        app = await application_service.tailor_for_application(s, app)
        await repo.enqueue_task(
            s,
            "run_analyze",
            f"application:{app.id}:analyze",
            {"application_id": app.id},
            app.seeker_id,
            app.id,
        )
        return

    if task.task_type in {"run_analyze", "run_apply", "resume_after_human"}:
        app = await _load_app(s, payload["application_id"])
        ok, reason = await can_start_browser_task(s, app.seeker_id)
        if not ok:
            raise _RetryLater(reason)
        posting = await repo.get_posting(s, app.posting_id)
        apply_url = (posting.apply_url or posting.canonical_url) if posting else ""
        if task.task_type in {"run_apply", "resume_after_human"}:
            allowed, reason, seconds = await can_start_application(s, app, apply_url)
            if not allowed:
                raise _RetryLater(reason, seconds)
            await repo.audit(s, app.seeker_id, "application", app.id, "application_start", "system", {})
        await application_service.run_application(s, app.id)
        return

    if task.task_type == "run_validate":
        app = await _load_app(s, payload["application_id"])
        await repo.audit(s, app.seeker_id, "application", app.id, "validate_queued_noop", "system", {})
        return

    raise ValueError(f"unknown task type: {task.task_type}")


async def _load_app(s, application_id: str):
    app = await repo.get_application(s, application_id)
    if app is None:
        raise ValueError("application not found")
    if app.status in {"submitted", "confirmed"}:
        raise ValueError(f"application is already {app.status}")
    return app
