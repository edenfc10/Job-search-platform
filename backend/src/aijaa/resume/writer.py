"""Master resume writer: LLM writes the IR, the fabrication guard gates it,
guarded fallback is the verbatim-fact IR."""

import structlog

from aijaa.core.models import ProfessionalProfile
from aijaa.llm.factory import get_llms
from aijaa.resume.guard import check_ir
from aijaa.resume.ir import ResumeIR, base_ir_from_profile

log = structlog.get_logger()

MAX_RETRIES = 2


async def write_master_ir(profile: ProfessionalProfile, language: str) -> ResumeIR:
    llm = get_llms().resume
    for attempt in range(MAX_RETRIES + 1):
        ir = await llm.write(profile, language)
        ir.language = language  # type: ignore[assignment]
        violations = check_ir(ir, profile)
        if not violations:
            return ir
        log.warning("resume_guard_violations", attempt=attempt, violations=violations)
    # Fall back to the verbatim-fact skeleton — always guard-safe.
    log.warning("resume_writer_fallback_verbatim")
    fallback = base_ir_from_profile(profile, language)
    fallback.summary = ir.summary if not any("summary" in v for v in violations) else ""
    return fallback
