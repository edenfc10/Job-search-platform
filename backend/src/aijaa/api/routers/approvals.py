"""Approval workflow + recruiter handoff packet (the MVP boundary: a human
recruiter reviews curated matches, approves per job, and gets everything
needed to apply manually — or hands off to the automated engine in Phase B)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.config import get_settings
from aijaa.core.db import get_session
from aijaa.core.models import utcnow
from aijaa.core.status import ApplicationStatus
from aijaa.orchestration.pipeline import enqueue_approved_match

router = APIRouter(prefix="/v1", tags=["approvals"])


@router.get("/seekers/{seeker_id}/matches")
async def list_matches(
    seeker_id: str, status: str | None = None, s: AsyncSession = Depends(get_session)
):
    matches = await repo.list_matches(s, seeker_id, status)
    out = []
    for m in matches:
        posting = await repo.get_posting(s, m.posting_id)
        app = await repo.get_application_for_match(s, m.id)
        out.append(
            {
                "match_id": m.id,
                "application_id": app.id if app else None,
                "score": m.rerank_score,
                "rationale": m.rationale,
                "risks": m.risks,
                "status": m.status,
                "decided_by": m.decided_by,
                "application_status": app.status if app else None,
                "posting": {
                    "id": posting.id,
                    "title": posting.title,
                    "company": posting.company,
                    "location": posting.location,
                    "url": posting.canonical_url,
                    "posted_at": posting.posted_at.isoformat() if posting.posted_at else None,
                    "salary_min": posting.salary_min,
                    "salary_max": posting.salary_max,
                }
                if posting
                else None,
            }
        )
    return out


class DecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    decided_by: str
    note: str | None = None


@router.post("/matches/{match_id}/decision")
async def decide(match_id: str, body: DecisionRequest, s: AsyncSession = Depends(get_session)):
    match = await repo.get_match(s, match_id)
    if match is None:
        raise HTTPException(404, "match not found")
    if match.status == body.decision:
        return {"match_id": match_id, "status": match.status, "idempotent": True}
    if match.status != "pending":
        raise HTTPException(409, f"match already decided: {match.status} (decisions are immutable)")
    if not body.decided_by.strip():
        raise HTTPException(422, "decided_by is required — approvals must be attributable")

    match.status = body.decision
    match.decided_by = body.decided_by
    match.decided_at = utcnow()
    match.decision_note = body.note
    await repo.save_match(s, match)

    app = await repo.get_application_for_match(s, match_id)
    if app:
        new_status = (
            ApplicationStatus.approved.value
            if body.decision == "approved"
            else ApplicationStatus.failed.value
        )
        await repo.transition_application(
            s, app, new_status, actor=f"operator:{body.decided_by}",
            reason=body.note or body.decision,
        )
        if body.decision == "approved" and get_settings().workflow_mode == "queue":
            await enqueue_approved_match(s, match, app)
    await repo.audit(
        s, match.seeker_id, "match", match_id, f"decision:{body.decision}",
        actor=f"operator:{body.decided_by}", detail={"note": body.note},
    )
    return {"match_id": match_id, "status": match.status}


class BatchDecisionRequest(BaseModel):
    decisions: list[dict]  # [{match_id, decision, decided_by, note?}]


@router.post("/seekers/{seeker_id}/matches/decisions")
async def decide_batch(
    seeker_id: str, body: BatchDecisionRequest, s: AsyncSession = Depends(get_session)
):
    results = []
    for d in body.decisions:
        try:
            r = await decide(d["match_id"], DecisionRequest.model_validate(d), s)
            results.append(r)
        except HTTPException as e:
            results.append({"match_id": d.get("match_id"), "error": e.detail})
    return results


@router.get("/matches/{match_id}/handoff")
async def handoff_packet(match_id: str, s: AsyncSession = Depends(get_session)):
    """Recruiter handoff packet (MVP): everything a human needs to apply
    manually — job, rationale, risks, tailored (or master) resume artifacts."""
    match = await repo.get_match(s, match_id)
    if match is None:
        raise HTTPException(404, "match not found")
    if match.status != "approved":
        raise HTTPException(409, "handoff packets are only available for approved matches")
    posting = await repo.get_posting(s, match.posting_id)
    app = await repo.get_application_for_match(s, match_id)

    resume = None
    if app and app.resume_id:
        resume = await repo.get_resume(s, match.seeker_id, app.resume_id)
    if resume is None:
        resume = await repo.latest_master_resume(s, match.seeker_id, "en") or (
            await repo.latest_master_resume(s, match.seeker_id, "he")
        )

    profile = await repo.latest_profile(s, match.seeker_id)
    return {
        "seeker": {
            "id": match.seeker_id,
            "name": profile.contact.full_name if profile else None,
            "email": profile.contact.email if profile else None,
            "phone": profile.contact.phone if profile else None,
            "links": profile.contact.links if profile else [],
        },
        "job": {
            "title": posting.title,
            "company": posting.company,
            "location": posting.location,
            "apply_url": posting.apply_url or posting.canonical_url,
            "posted_at": posting.posted_at.isoformat() if posting.posted_at else None,
        },
        "match": {
            "score": match.rerank_score,
            "rationale": match.rationale,
            "risks": match.risks,
            "approved_by": match.decided_by,
            "note": match.decision_note,
        },
        "resume": {
            "kind": resume.kind if resume else None,
            "language": resume.language if resume else None,
            "artifacts": resume.artifacts if resume else {},
            "ats_score_before": resume.ats_score_before if resume else None,
            "ats_score_after": resume.ats_score_after if resume else None,
        },
        "application_status": app.status if app else None,
    }
