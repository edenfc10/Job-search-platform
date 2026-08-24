"""Small deterministic quality gates for candidate data.

These checks are intentionally independent of the LLM. A heading or demo
email must never be treated as verified candidate identity merely because the
rest of the workflow is running in local/demo mode.
"""

from aijaa.core.models import CareerPreferences, ProfessionalProfile

PLACEHOLDER_NAMES = {"cv", "resume", "sample resume", "curriculum vitae"}
PLACEHOLDER_EMAILS = {"mail@email.com", "email@example.com"}


def candidate_profile_issues(
    profile: ProfessionalProfile, prefs: CareerPreferences | None = None
) -> list[str]:
    issues: list[str] = []
    name = profile.contact.full_name.strip().casefold()
    email = profile.contact.email.strip().casefold()
    if not name:
        issues.append("candidate full name is missing")
    elif name in PLACEHOLDER_NAMES:
        issues.append("candidate full name is a CV heading/placeholder")
    if not email:
        issues.append("candidate email is missing")
    elif email in PLACEHOLDER_EMAILS:
        issues.append("candidate email is a placeholder")
    if not profile.work_history:
        issues.append("work history is missing")
    if not profile.skills:
        issues.append("verified skills are missing")
    if prefs is not None and not prefs.target_titles:
        issues.append("target titles are missing")
    return issues
