from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core.db import get_session
from aijaa.discovery.base import SearchCriteria
from aijaa.discovery.runner import run_discovery
from aijaa.discovery.sources.fixture import FixtureSource
from aijaa.discovery.sources.greenhouse import GreenhouseBoardSource
from aijaa.discovery.sources.lever import LeverPostingsSource
from aijaa.llm.usage import current_seeker_id
from aijaa.matching.service import run_matching
from aijaa.observability.webhooks import emit

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
