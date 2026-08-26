"""Profile completeness rubric — deterministic code, not LLM opinion.
intake_complete requires overall >= 85 AND all hard preference fields."""

from aijaa.core.models import CareerPreferences, ProfessionalProfile

WEIGHTS = {
    "contact": 10,
    "work_history": 30,
    "skills": 15,
    "education": 10,
    "preferences": 25,
    "links": 10,
}

COMPLETE_THRESHOLD = 85


def section_scores(profile: ProfessionalProfile, prefs: CareerPreferences) -> dict[str, int]:
    scores: dict[str, int] = {}

    contact = profile.contact
    scores["contact"] = int(
        WEIGHTS["contact"] * (0.5 * bool(contact.full_name) + 0.5 * bool(contact.email))
    )

    work = 0.0
    if profile.work_history:
        work += 0.5
        recent = profile.work_history[0]
        if recent.achievements:
            work += 0.2
            if any(f.quantified for f in recent.achievements):
                work += 0.2
        if len(profile.work_history) >= 2:
            work += 0.1
    scores["work_history"] = round(WEIGHTS["work_history"] * work)

    scores["skills"] = int(WEIGHTS["skills"] * min(len(profile.skills) / 5, 1.0))
    scores["education"] = WEIGHTS["education"] if profile.education else 0

    pref_parts = [
        bool(prefs.target_titles),
        bool(prefs.locations) or prefs.remote_policy != "any",
        prefs.min_salary is not None,
        prefs.work_authorization is not None,
        bool(prefs.dealbreakers) or prefs.availability is not None,
    ]
    scores["preferences"] = int(WEIGHTS["preferences"] * sum(pref_parts) / len(pref_parts))

    scores["links"] = WEIGHTS["links"] if contact.links else 0
    return scores


def hard_fields_present(prefs: CareerPreferences) -> bool:
    return bool(
        prefs.target_titles
        and (prefs.locations or prefs.remote_policy != "any")
        and prefs.min_salary is not None
        and prefs.work_authorization is not None
    )


def completeness(profile: ProfessionalProfile, prefs: CareerPreferences):
    scores = section_scores(profile, prefs)
    overall = sum(scores.values())
    missing = [
        s for s, v in sorted(scores.items(), key=lambda kv: kv[1] / WEIGHTS[kv[0]])
        if v < WEIGHTS[s]
    ]
    complete = overall >= COMPLETE_THRESHOLD and hard_fields_present(prefs)
    return overall, scores, missing, complete
