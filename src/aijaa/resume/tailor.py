"""Fact-safe tailoring: analyze JD (cached on the posting), tailor the master
IR, hard-gate with the fabrication guard, and report before/after ATS scores."""

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.models import JobPosting, JobRequirements, ResumeDocument
from aijaa.llm.factory import get_llms
from aijaa.resume.ats_score import ATSReport, score
from aijaa.resume.guard import check_ir
from aijaa.resume.ir import ResumeIR
from aijaa.resume.service import render_artifacts


class TailorReport(BaseModel):
    score_before: int
    score_after: int
    report_before: ATSReport
    report_after: ATSReport
    guard_fallback_used: bool = False


async def ensure_requirements(s: AsyncSession, posting: JobPosting) -> JobRequirements:
    if posting.requirements is not None:
        return posting.requirements
    requirements = await get_llms().jd.analyze(posting)
    posting.requirements = requirements
    await repo.update_posting(s, posting)
    return requirements


async def tailor_resume(
    s: AsyncSession, seeker_id: str, posting: JobPosting, master: ResumeDocument
) -> tuple[ResumeDocument, TailorReport]:
    profile = await repo.latest_profile(s, seeker_id)
    assert profile is not None
    requirements = await ensure_requirements(s, posting)
    master_ir = ResumeIR.model_validate(master.ir)

    report_before = score(master_ir, requirements, posting.title)
    tailored_ir = await get_llms().tailor.tailor(master_ir, requirements, profile)
    tailored_ir.language = master_ir.language

    guard_fallback = False
    violations = check_ir(tailored_ir, profile)
    if violations:
        # Hard gate: reject the tailored IR, apply safe reordering only.
        from aijaa.llm.fakes import FakeTailorLLM

        tailored_ir = await FakeTailorLLM().tailor(master_ir, requirements, profile)
        guard_fallback = True

    report_after = score(tailored_ir, requirements, posting.title)
    doc = ResumeDocument(
        seeker_id=seeker_id,
        kind="tailored",
        language=master.language,
        posting_id=posting.id,
        ir=tailored_ir.model_dump(),
        ats_score_before=report_before.score,
        ats_score_after=report_after.score,
    )
    doc.artifacts = render_artifacts(tailored_ir, seeker_id, f"tailored_{posting.id[:8]}_{doc.id[:6]}")
    await repo.save_resume(s, doc)
    await repo.audit(
        s, seeker_id, "resume", doc.id, "resume_tailored", "system",
        {"posting_id": posting.id, "before": report_before.score, "after": report_after.score,
         "guard_fallback": guard_fallback},
    )
    return doc, TailorReport(
        score_before=report_before.score,
        score_after=report_after.score,
        report_before=report_before,
        report_after=report_after,
        guard_fallback_used=guard_fallback,
    )
