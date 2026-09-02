"""Idempotent enqueue helpers for the local DB-backed pipeline."""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.models import ApplicationRecord, MatchResult, utcnow


async def enqueue_discovery(s: AsyncSession, payload: dict) -> tuple[str, bool]:
    return await repo.enqueue_task(
        s,
        "run_discovery",
        f"discovery:{payload}",
        payload=payload,
        run_after=utcnow(),
    )


async def enqueue_matching(s: AsyncSession, seeker_id: str) -> tuple[str, bool]:
    return await repo.enqueue_task(
        s,
        "run_matching",
        f"match:{seeker_id}",
        payload={"seeker_id": seeker_id},
        seeker_id=seeker_id,
    )


async def enqueue_approved_match(
    s: AsyncSession, match: MatchResult, app: ApplicationRecord | None
) -> tuple[str | None, bool]:
    if app is None or app.status in {"submitted", "confirmed", "failed"}:
        return None, False
    return await repo.enqueue_task(
        s,
        "run_tailor",
        f"application:{app.id}:tailor",
        payload={"application_id": app.id},
        seeker_id=app.seeker_id,
        application_id=app.id,
    )


async def enqueue_human_resume(
    s: AsyncSession, app: ApplicationRecord
) -> tuple[str | None, bool]:
    if app.status in {"submitted", "confirmed", "failed"}:
        return None, False
    return await repo.enqueue_task(
        s,
        "resume_after_human",
        f"application:{app.id}:human:{len(app.human_answers)}",
        payload={"application_id": app.id},
        seeker_id=app.seeker_id,
        application_id=app.id,
    )


def next_discovery_at() -> str:
    return (utcnow() + timedelta(hours=get_settings().discovery_interval_hours)).isoformat()
