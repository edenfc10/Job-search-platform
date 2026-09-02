from aijaa.core.models import CareerPreferences, ProfessionalProfile
from aijaa.intake.rubric import completeness
from conftest import PREFERENCES_PATCH, PROFILE_PATCH


def test_empty_profile_scores_low():
    overall, scores, missing, complete = completeness(
        ProfessionalProfile(seeker_id="x"), CareerPreferences(seeker_id="x")
    )
    assert overall == 0 and not complete
    assert "work_history" in missing and "preferences" in missing


def test_complete_profile_passes_threshold():
    profile = ProfessionalProfile.model_validate({"seeker_id": "x", **PROFILE_PATCH})
    prefs = CareerPreferences.model_validate({"seeker_id": "x", **PREFERENCES_PATCH})
    overall, scores, missing, complete = completeness(profile, prefs)
    assert overall == 100
    assert scores["work_history"] == 30
    assert missing == []
    assert complete


def test_hard_fields_gate_completion():
    profile = ProfessionalProfile.model_validate({"seeker_id": "x", **PROFILE_PATCH})
    prefs_data = {**PREFERENCES_PATCH, "min_salary": None}
    prefs = CareerPreferences.model_validate({"seeker_id": "x", "min_salary": None, **{k: v for k, v in prefs_data.items() if k != "min_salary"}})
    prefs.min_salary = None
    _, _, _, complete = completeness(profile, prefs)
    assert not complete  # salary floor missing blocks completion regardless of score


async def test_intake_turns_progress(client):
    r = await client.post(
        "/v1/seekers",
        json={"external_ref": "t", "consent_recorded_at": "2026-07-16T08:00:00Z"},
    )
    seeker_id = r.json()["seeker_id"]

    # Turn 1: free text only -> low completeness, rubric-driven questions
    r = await client.post(
        f"/v1/seekers/{seeker_id}/intake/turns",
        json={"free_text": "I'm a backend engineer from Tel Aviv."},
    )
    body = r.json()
    assert body["profile_version"] == 1
    assert not body["intake_complete"]
    assert 1 <= len(body["next_questions"]) <= 3
    sections = {q["section"] for q in body["next_questions"]}
    assert sections <= {"contact", "work_history", "skills", "education", "preferences", "links"}

    # Turn 2: structured patches -> complete, no further questions
    r = await client.post(
        f"/v1/seekers/{seeker_id}/intake/turns",
        json={"profile_patch": PROFILE_PATCH, "preferences_patch": PREFERENCES_PATCH},
    )
    body = r.json()
    assert body["profile_version"] == 2
    assert body["intake_complete"]
    assert body["next_questions"] == []

    # earlier facts survive (turn 1 free text is in summary_notes)
    r = await client.get(f"/v1/seekers/{seeker_id}/profile")
    profile = r.json()["profile"]
    assert "backend engineer" in profile["summary_notes"].lower()
    assert profile["contact"]["full_name"] == "Dana Levi"
