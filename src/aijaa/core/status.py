"""Application status state machine.

`ready_to_submit` is the PRD-mandated pre-submit human validation state: the
executor has filled the application and stops there until a human confirms the
final submit. It is the only state from which a real submit may happen.
"""

from datetime import UTC, datetime
from enum import StrEnum


class ApplicationStatus(StrEnum):
    discovered = "discovered"
    matched = "matched"
    approved = "approved"
    tailored = "tailored"
    applying = "applying"
    ready_to_submit = "ready_to_submit"
    needs_human = "needs_human"
    submitted = "submitted"
    confirmed = "confirmed"
    failed = "failed"


TERMINAL = {ApplicationStatus.confirmed, ApplicationStatus.failed}

ALLOWED_TRANSITIONS: dict[ApplicationStatus, set[ApplicationStatus]] = {
    ApplicationStatus.discovered: {ApplicationStatus.matched, ApplicationStatus.failed},
    ApplicationStatus.matched: {ApplicationStatus.approved, ApplicationStatus.failed},
    ApplicationStatus.approved: {ApplicationStatus.tailored, ApplicationStatus.failed},
    ApplicationStatus.tailored: {
        ApplicationStatus.applying,
        ApplicationStatus.needs_human,  # analysis-time blocker (captcha/login/account)
        ApplicationStatus.failed,
    },
    ApplicationStatus.applying: {
        ApplicationStatus.ready_to_submit,
        ApplicationStatus.needs_human,
        ApplicationStatus.failed,
    },
    ApplicationStatus.ready_to_submit: {
        ApplicationStatus.submitted,
        ApplicationStatus.applying,  # re-fill requested by reviewer
        ApplicationStatus.needs_human,
        ApplicationStatus.failed,
    },
    ApplicationStatus.needs_human: {
        ApplicationStatus.applying,
        ApplicationStatus.ready_to_submit,
        ApplicationStatus.submitted,  # human resolves "possibly submitted" as submitted
        ApplicationStatus.failed,
    },
    ApplicationStatus.submitted: {
        ApplicationStatus.confirmed,
        ApplicationStatus.needs_human,
        ApplicationStatus.failed,
    },
    ApplicationStatus.confirmed: set(),
    ApplicationStatus.failed: set(),
}


class IllegalTransition(Exception):
    pass


def transition_entry(
    current: str, new: str, actor: str, reason: str | None = None
) -> dict:
    """Validate a transition and return the timeline entry to append."""
    cur = ApplicationStatus(current)
    nxt = ApplicationStatus(new)
    if nxt not in ALLOWED_TRANSITIONS[cur]:
        raise IllegalTransition(f"{cur} -> {nxt} (actor={actor})")
    return {
        "from": cur.value,
        "to": nxt.value,
        "actor": actor,
        "reason": reason,
        "at": datetime.now(UTC).isoformat(),
    }
