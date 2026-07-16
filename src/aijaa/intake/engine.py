"""Adaptive intake engine: each turn merges structured patches + LLM-extracted
data from free text, versions the profile, and returns rubric-driven
completeness + the next best questions."""

from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.models import CareerPreferences, ProfessionalProfile
from aijaa.intake.rubric import completeness
from aijaa.llm.factory import get_llms


class IntakeTurnRequest(BaseModel):
    free_text: str = ""
    profile_patch: dict = {}
    preferences_patch: dict = {}


class IntakeTurnResponse(BaseModel):
    profile_version: int
    overall_completeness: int
    section_scores: dict[str, int]
    intake_complete: bool
    next_questions: list[dict]


def deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _apply_patch(model: BaseModel, patch: dict[str, Any], cls):
    if not patch:
        return model
    merged = deep_merge(model.model_dump(mode="json"), patch)
    return cls.model_validate(merged)


async def run_turn(
    s: AsyncSession, seeker_id: str, body: IntakeTurnRequest
) -> IntakeTurnResponse:
    profile = await repo.latest_profile(s, seeker_id) or ProfessionalProfile(seeker_id=seeker_id)
    prefs = await repo.get_preferences(s, seeker_id) or CareerPreferences(seeker_id=seeker_id)

    # 1. Client-supplied structured patches apply first (they are ground truth).
    profile = _apply_patch(profile, body.profile_patch, ProfessionalProfile)
    prefs = _apply_patch(prefs, body.preferences_patch, CareerPreferences)

    # 2. LLM extracts from free text and proposes next questions.
    _, _, missing, _ = completeness(profile, prefs)
    extraction = await get_llms().intake.turn(profile, prefs, body.free_text, missing)
    profile = _apply_patch(profile, extraction.profile_patch, ProfessionalProfile)
    prefs = _apply_patch(prefs, extraction.preferences_patch, CareerPreferences)

    # 3. Persist (new profile version each turn) and score.
    version = await repo.save_profile(s, seeker_id, profile)
    await repo.save_preferences(s, seeker_id, prefs)
    overall, scores, missing, complete = completeness(profile, prefs)

    questions = [q.model_dump() for q in extraction.next_questions]
    await repo.audit(
        s, seeker_id, "profile", seeker_id, "intake_turn",
        actor="system", detail={"version": version, "completeness": overall},
    )
    return IntakeTurnResponse(
        profile_version=version,
        overall_completeness=overall,
        section_scores=scores,
        intake_complete=complete,
        next_questions=[] if complete else questions,
    )
