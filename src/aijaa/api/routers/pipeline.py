import hashlib
import re
from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.db import get_session
from aijaa.core.models import JobPosting, utcnow
from aijaa.core.production import csv_items
from aijaa.core.tables import ApplicationRow, LLMUsageRow
from aijaa.discovery.base import SearchCriteria
from aijaa.discovery.normalize import canonical_url, strip_html
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
async def discovery_run(
    body: DiscoveryRequest, request: Request, s: AsyncSession = Depends(get_session)
):
    settings = get_settings()
    sources = []
    if body.fixtures_dir:
        if settings.production_mode:
            raise HTTPException(422, "fixture discovery is disabled in production mode")
        sources.append(FixtureSource(body.fixtures_dir))
    greenhouse_orgs = body.greenhouse_orgs or csv_items(settings.greenhouse_orgs)
    lever_orgs = body.lever_orgs or csv_items(settings.lever_orgs)
    if greenhouse_orgs:
        sources.append(GreenhouseBoardSource(greenhouse_orgs))
    if lever_orgs:
        sources.append(LeverPostingsSource(lever_orgs))
    if not sources:
        raise HTTPException(422, "configure at least one source (fixtures_dir or org lists)")
    criteria = None
    if body.posted_within_days:
        criteria = SearchCriteria(posted_within_days=body.posted_within_days)
    return await run_discovery(s, sources, criteria, fixture_base_url=str(request.base_url))


class ManualJobRequest(BaseModel):
    url: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    description_text: str | None = None


@router.post("/jobs/manual")
async def manual_job(body: ManualJobRequest, s: AsyncSession = Depends(get_session)):
    settings = get_settings()
    if not settings.enable_manual_urls:
        raise HTTPException(403, "manual job URLs are disabled")
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(422, "url must be http(s)")

    page_text = body.description_text or ""
    title = body.title or ""
    company = body.company or "Manual Source"
    if not page_text or not title:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(body.url)
                resp.raise_for_status()
                html = resp.text
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, f"could not fetch manual URL: {type(e).__name__}") from e
        page_text = page_text or strip_html(html)
        title = title or _html_title(html) or body.url

    url = canonical_url(body.url)
    posting = JobPosting(
        source="manual",
        canonical_url=url,
        apply_url=url,
        company=company,
        title=title.strip(),
        location=body.location,
        description_text=page_text[:20000],
        posted_at=utcnow(),
        posted_at_inferred=True,
        content_hash=hashlib.sha256(page_text.encode()).hexdigest()[:32],
    )
    posting_id, created = await repo.upsert_posting(s, posting)
    await repo.audit(
        s,
        "",
        "posting",
        posting_id,
        "manual_job_added",
        "operator",
        {"url": url, "created": created},
    )
    return {"posting_id": posting_id, "created": created, "posting": posting.model_dump(mode="json")}


def _html_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    return strip_html(m.group(1)) if m else ""


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
        "workflow_mode": get_settings().workflow_mode,
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
