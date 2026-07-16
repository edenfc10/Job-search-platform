from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.db import get_session
from aijaa.core.models import utcnow
from aijaa.core.tables import ApplicationRow, LLMUsageRow
from aijaa.discovery.base import SearchCriteria
from aijaa.discovery.runner import run_discovery
from aijaa.discovery.sources.fixture import FixtureSource
from aijaa.discovery.sources.greenhouse import GreenhouseBoardSource
from aijaa.discovery.sources.lever import LeverPostingsSource
from aijaa.llm.usage import current_seeker_id
from aijaa.matching.service import run_matching
from aijaa.observability.webhooks import emit
from aijaa.orchestration.pipeline import next_discovery_at

router = APIRouter(prefix="/v1", tags=["pipeline"])


class DiscoveryRequest(BaseModel):
    fixtures_dir: str | None = None
    greenhouse_orgs: list[str] = []
    lever_orgs: list[str] = []
    posted_within_days: int | None = None


@router.post("/discovery/run")
async def discovery_run(body: DiscoveryRequest, s: AsyncSession = Depends(get_session)):
    sources = []
    if body.fixtures_dir:
        sources.append(FixtureSource(body.fixtures_dir))
    if body.greenhouse_orgs:
        sources.append(GreenhouseBoardSource(body.greenhouse_orgs))
    if body.lever_orgs:
        sources.append(LeverPostingsSource(body.lever_orgs))
    if not sources:
        raise HTTPException(422, "configure at least one source (fixtures_dir or org lists)")
    criteria = None
    if body.posted_within_days:
        criteria = SearchCriteria(posted_within_days=body.posted_within_days)
    return await run_discovery(s, sources, criteria)


@router.post("/seekers/{seeker_id}/match/run")
async def match_run(seeker_id: str, s: AsyncSession = Depends(get_session)):
    current_seeker_id.set(seeker_id)
    try:
        stats = await run_matching(s, seeker_id)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    if stats["matches_created"]:
        await emit("matches.pending", {"seeker_id": seeker_id, "count": stats["matches_created"]})
    return stats


@router.get("/seekers/{seeker_id}/pipeline")
async def pipeline_status(seeker_id: str, s: AsyncSession = Depends(get_session)):
    status_rows = (
        await s.execute(
            select(ApplicationRow.status, func.count())
            .where(ApplicationRow.seeker_id == seeker_id)
            .group_by(ApplicationRow.status)
        )
    ).all()
    tasks = await repo.task_counts(s, seeker_id)
    return {
        "seeker_id": seeker_id,
        "applications": {status: count for status, count in status_rows},
        "tasks": tasks,
        "in_flight_tasks": tasks.get("running", 0),
        "dead_letters": await repo.dead_letter_count(s, seeker_id),
        "next_scheduled_discovery": next_discovery_at(),
    }


@router.get("/usage")
async def usage_rollup(window: str = Query("30d"), s: AsyncSession = Depends(get_session)):
    days = int(window[:-1]) if window.endswith("d") and window[:-1].isdigit() else 30
    since = utcnow() - timedelta(days=days)
    rows = (
        await s.execute(
            select(
                LLMUsageRow.seeker_id,
                LLMUsageRow.component,
                LLMUsageRow.model,
                func.sum(LLMUsageRow.input_tokens),
                func.sum(LLMUsageRow.output_tokens),
                func.count(),
            )
            .where(LLMUsageRow.ts >= since)
            .group_by(LLMUsageRow.seeker_id, LLMUsageRow.component, LLMUsageRow.model)
        )
    ).all()
    return [
        {
            "seeker_id": seeker_id,
            "component": component,
            "model": model,
            "input_tokens": input_tokens or 0,
            "output_tokens": output_tokens or 0,
            "calls": calls,
            "window": window,
        }
        for seeker_id, component, model, input_tokens, output_tokens, calls in rows
    ]
