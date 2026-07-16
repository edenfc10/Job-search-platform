"""Application engine endpoints (Phase B). Present from the MVP build so the
API surface is stable; endpoints 409 until the analyzer/executor phases run."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.application.gate import ApprovalMissing
from aijaa.application.service import (
    confirm_and_submit,
    provide_human_input,
    run_application,
)
from aijaa.core import repo
from aijaa.core.db import get_session
from aijaa.llm.usage import current_seeker_id
from aijaa.orchestration.pipeline import enqueue_human_resume

router = APIRouter(prefix="/v1/applications", tags=["applications"])


async def _load(s: AsyncSession, application_id: str):
    app = await repo.get_application(s, application_id)
    if app is None:
        raise HTTPException(404, "application not found")
    current_seeker_id.set(app.seeker_id)
    return app


@router.post("/{application_id}/run")
async def run(application_id: str, s: AsyncSession = Depends(get_session)):
    await _load(s, application_id)
    try:
        app = await run_application(s, application_id)
    except ApprovalMissing as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return app.model_dump(mode="json")


class HumanInputRequest(BaseModel):
    answers: dict[str, str]
    provided_by: str


@router.post("/{application_id}/human-input")
async def human_input(
    application_id: str, body: HumanInputRequest, s: AsyncSession = Depends(get_session)
):
    await _load(s, application_id)
    if not body.provided_by.strip():
        raise HTTPException(422, "provided_by is required")
    app = await provide_human_input(s, application_id, body.answers, body.provided_by)
    await enqueue_human_resume(s, app)
    return app.model_dump(mode="json")


class SubmitConfirmRequest(BaseModel):
    confirmed_by: str


@router.post("/{application_id}/confirm-submit")
async def confirm_submit_endpoint(
    application_id: str, body: SubmitConfirmRequest, s: AsyncSession = Depends(get_session)
):
    await _load(s, application_id)
    if not body.confirmed_by.strip():
        raise HTTPException(422, "confirmed_by is required — the submit gate is human-attributable")
    try:
        app = await confirm_and_submit(s, application_id, body.confirmed_by)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return app.model_dump(mode="json")


@router.get("/{application_id}")
async def get_application(application_id: str, s: AsyncSession = Depends(get_session)):
    app = await repo.get_application(s, application_id)
    if app is None:
        raise HTTPException(404, "application not found")
    return app.model_dump(mode="json")


@router.get("/{application_id}/timeline")
async def timeline(application_id: str, s: AsyncSession = Depends(get_session)):
    app = await repo.get_application(s, application_id)
    if app is None:
        raise HTTPException(404, "application not found")
    audit = await repo.audit_for_entity(s, app.seeker_id, application_id)
    events = []
    for entry in app.timeline:
        events.append({"ts": entry.get("at"), "kind": "status", **entry})
    for entry in audit:
        events.append({"ts": entry["ts"], "kind": "audit", **entry})
    for evidence in app.evidence:
        events.append(
            {
                "ts": evidence.captured_at.isoformat(),
                "kind": "evidence",
                "evidence_kind": evidence.kind,
                "value": evidence.value,
            }
        )
    events.sort(key=lambda e: e.get("ts") or "")
    return {
        "application_id": application_id,
        "status": app.status,
        "timeline": app.timeline,
        "audit": audit,
        "evidence": [e.model_dump(mode="json") for e in app.evidence],
        "events": events,
    }
