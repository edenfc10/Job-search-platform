"""Submission validation & receipts. Terminal states always carry evidence.
No-double-submit governs the retry policy: only PRE-submit transient errors
may retry; anything at/after the submit click escalates to needs_human."""

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import repo
from aijaa.core.models import ApplicationRecord, Evidence
from aijaa.core.status import ApplicationStatus
from aijaa.llm.factory import get_llms


async def validate_submission(
    s: AsyncSession, app: ApplicationRecord, page_text: str
) -> ApplicationRecord:
    judgment = await get_llms().confirmation.judge(page_text)
    if judgment.verdict == "confirmed":
        app.confirmation_ref = judgment.confirmation_ref
        app.evidence.append(
            Evidence(kind="confirmation_ref", value=judgment.confirmation_ref or judgment.evidence)
        )
        return await repo.transition_application(
            s, app, ApplicationStatus.confirmed.value, "system", judgment.evidence
        )
    if judgment.verdict == "unconfirmed":
        # Explicit failure page AFTER a submit click -> needs_human (do not retry).
        app.needs_human_reason = "submit_error_after_click"
        app.evidence.append(Evidence(kind="note", value=judgment.evidence))
        return await repo.transition_application(
            s, app, ApplicationStatus.needs_human.value, "system", app.needs_human_reason
        )
    # Ambiguous: stay submitted, flagged. Never mark failed, never retry.
    app.evidence.append(Evidence(kind="note", value=f"unconfirmed_after_window: {judgment.evidence}"))
    await repo.save_application(s, app)
    await repo.audit(
        s, app.seeker_id, "application", app.id, "unconfirmed_after_window", "system",
        {"evidence": judgment.evidence},
    )
    return app


# ---------------------------------------------------------------- retry policy

class RetryDecision(BaseModel):
    action: str  # "retry" | "needs_human" | "fail"
    reason: str


def retry_decision(phase: str, error_kind: str) -> RetryDecision:
    """Single authority on what may be retried. `phase` is 'pre_submit' or
    'post_submit_click'. Transient pre-submit errors retry; anything touching
    the submit click escalates — a duplicate application is worse than a stall."""
    transient = {"network", "timeout", "http_5xx"}
    if phase == "post_submit_click":
        return RetryDecision(action="needs_human", reason="possibly_submitted; never retry a click")
    if phase == "pre_submit":
        if error_kind in transient:
            return RetryDecision(action="retry", reason="transient pre-submit error")
        if error_kind in {"posting_closed", "form_gone", "plan_unexecutable"}:
            return RetryDecision(action="fail", reason="definitive pre-submit failure")
        return RetryDecision(action="needs_human", reason="unclassified pre-submit error")
    return RetryDecision(action="needs_human", reason="unknown phase")
