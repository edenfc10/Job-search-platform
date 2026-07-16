"""Hard pre-filters from CareerPreferences. Non-negotiable: a perfect rerank
score cannot resurrect a posting that violates these."""

from aijaa.core.models import CareerPreferences, JobPosting


def _location_ok(posting: JobPosting, prefs: CareerPreferences) -> bool:
    if posting.remote and prefs.remote_policy in ("remote", "hybrid", "any"):
        return True
    if not prefs.locations:
        return True
    if posting.location is None:
        return True  # unknown location is a risk, not a hard exclusion
    loc = posting.location.lower()
    return any(want.lower() in loc or loc in want.lower() for want in prefs.locations)


def _salary_ok(posting: JobPosting, prefs: CareerPreferences) -> bool:
    if prefs.min_salary is None:
        return True
    ceiling = posting.salary_max or posting.salary_min
    if ceiling is None:
        return True  # unknown salary -> risk flag, not exclusion
    return ceiling >= prefs.min_salary


def _dealbreakers_ok(posting: JobPosting, prefs: CareerPreferences) -> bool:
    text = (posting.title + " " + posting.description_text).lower()
    return not any(d.lower() in text for d in prefs.dealbreakers if len(d) > 3)


def passes_hard_filters(posting: JobPosting, prefs: CareerPreferences) -> bool:
    return (
        _location_ok(posting, prefs)
        and _salary_ok(posting, prefs)
        and _dealbreakers_ok(posting, prefs)
    )
