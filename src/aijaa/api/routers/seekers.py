from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.db import get_session
from aijaa.intake.engine import IntakeTurnRequest, IntakeTurnResponse, run_turn
from aijaa.intake.rubric import completeness
from aijaa.llm.usage import current_seeker_id
from aijaa.resume.service import build_master_resume

router = APIRouter(prefix="/v1/seekers", tags=["seekers"])


class CreateSeekerRequest(BaseModel):
    external_ref: str = ""
    consent_recorded_at: datetime


class CreateSeekerResponse(BaseModel):
    seeker_id: str


@router.post("", response_model=CreateSeekerResponse)
async def create_seeker(body: CreateSeekerRequest, s: AsyncSession = Depends(get_session)):
    seeker_id = await repo.create_seeker(s, body.external_ref, body.consent_recorded_at)
    await repo.audit(s, seeker_id, "seeker", seeker_id, "seeker_created", "operator", {})
    return CreateSeekerResponse(seeker_id=seeker_id)


async def _require_seeker(s: AsyncSession, seeker_id: str):
    seeker = await repo.get_seeker(s, seeker_id)
    if seeker is None:
        raise HTTPException(404, "seeker not found")
    current_seeker_id.set(seeker_id)
    return seeker


@router.post("/{seeker_id}/intake/turns", response_model=IntakeTurnResponse)
async def intake_turn(
    seeker_id: str, body: IntakeTurnRequest, s: AsyncSession = Depends(get_session)
):
    await _require_seeker(s, seeker_id)
    return await run_turn(s, seeker_id, body)


@router.get("/{seeker_id}/profile")
async def get_profile(seeker_id: str, s: AsyncSession = Depends(get_session)):
    await _require_seeker(s, seeker_id)
    profile = await repo.latest_profile(s, seeker_id)
    prefs = await repo.get_preferences(s, seeker_id)
    if profile is None:
        raise HTTPException(404, "no profile yet — run an intake turn")
    from aijaa.core.models import CareerPreferences

    prefs = prefs or CareerPreferences(seeker_id=seeker_id)
    overall, scores, missing, complete = completeness(profile, prefs)
    stale = repo.profile_is_stale(profile, get_settings().profile_stale_days)
    return {
        "profile": profile.model_dump(mode="json"),
        "preferences": prefs.model_dump(mode="json"),
        "completeness": {"overall": overall, "sections": scores, "complete": complete},
        "stale": stale,
    }


class BuildResumeRequest(BaseModel):
    language: str = "en"


@router.post("/{seeker_id}/resume")
async def build_resume(
    seeker_id: str, body: BuildResumeRequest, s: AsyncSession = Depends(get_session)
):
    await _require_seeker(s, seeker_id)
    if body.language not in ("en", "he"):
        raise HTTPException(422, "language must be 'en' or 'he'")
    try:
        doc = await build_master_resume(s, seeker_id, body.language)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return doc.model_dump(mode="json")


@router.get("/{seeker_id}/resume/latest")
async def latest_resume(
    seeker_id: str, language: str = "en", s: AsyncSession = Depends(get_session)
):
    await _require_seeker(s, seeker_id)
    doc = await repo.latest_master_resume(s, seeker_id, language)
    if doc is None:
        raise HTTPException(404, "no master resume for this language yet")
    return doc.model_dump(mode="json")


@router.get("/{seeker_id}/usage")
async def usage(seeker_id: str, s: AsyncSession = Depends(get_session)):
    await _require_seeker(s, seeker_id)
    from sqlalchemy import func, select

    from aijaa.core.tables import LLMUsageRow

    rows = (
        await s.execute(
            select(
                LLMUsageRow.component,
                LLMUsageRow.model,
                func.sum(LLMUsageRow.input_tokens),
                func.sum(LLMUsageRow.output_tokens),
                func.count(),
            )
            .where(LLMUsageRow.seeker_id == seeker_id)
            .group_by(LLMUsageRow.component, LLMUsageRow.model)
        )
    ).all()
    return [
        {"component": c, "model": m, "input_tokens": i or 0, "output_tokens": o or 0, "calls": n}
        for c, m, i, o, n in rows
    ]
