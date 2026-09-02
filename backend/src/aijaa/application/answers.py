"""Field classification and answer resolution.

Classification rules are CODE. The LLM may only generate prose for fields
classified `generate` — it can never downgrade a needs_human field to auto."""

import re

from pydantic import BaseModel

from aijaa.application.forms import FormField
from aijaa.core.models import CareerPreferences, ProfessionalProfile

NEEDS_HUMAN_PATTERNS = re.compile(
    r"salary|compensation|pay expectation|desired pay|clearance|criminal|felony|"
    r"background check|reference|gender|ethnic|race|disability|veteran",
    re.I,
)
AUTO_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"full.?name|your name|^name$", re.I), "full_name"),
    (re.compile(r"first.?name", re.I), "first_name"),
    (re.compile(r"last.?name|surname", re.I), "last_name"),
    (re.compile(r"e-?mail", re.I), "email"),
    (re.compile(r"phone|mobile|tel", re.I), "phone"),
    (re.compile(r"location|city|address", re.I), "location"),
    (re.compile(r"linkedin", re.I), "linkedin"),
    (re.compile(r"github|portfolio|website|url", re.I), "link"),
    (re.compile(r"notice|availability|start date", re.I), "availability"),
    (re.compile(r"work authorization|authorized to work|visa|eligib", re.I), "work_auth"),
    (re.compile(r"resume|\bcv\b", re.I), "resume_file"),
    (re.compile(r"cover.?letter", re.I), "cover_letter"),
]


class PlannedField(BaseModel):
    field: FormField
    source: str  # auto:<key> | generate | needs_human | attach_resume | skip
    reason: str = ""


def classify_field(f: FormField) -> PlannedField:
    text = f"{f.name} {f.label}"
    if f.type == "hidden":
        return PlannedField(field=f, source="skip", reason="hidden field")
    if NEEDS_HUMAN_PATTERNS.search(text):
        return PlannedField(field=f, source="needs_human", reason="sensitive question")
    for pattern, key in AUTO_MAP:
        if pattern.search(text):
            if key == "resume_file":
                return PlannedField(field=f, source="attach_resume")
            if key == "cover_letter":
                return PlannedField(
                    field=f, source="generate" if f.type == "textarea" else "skip"
                )
            return PlannedField(field=f, source=f"auto:{key}")
    if f.type == "file":
        return PlannedField(field=f, source="attach_resume")
    if f.type == "textarea":
        return PlannedField(field=f, source="generate", reason="open question")
    if f.type in ("checkbox", "radio", "select"):
        return PlannedField(
            field=f,
            source="needs_human" if f.required else "skip",
            reason="choice field needs human judgment",
        )
    if f.required:
        return PlannedField(field=f, source="needs_human", reason="unmapped required field")
    return PlannedField(field=f, source="skip", reason="unmapped optional field")


def resolve_auto(key: str, profile: ProfessionalProfile, prefs: CareerPreferences) -> str:
    c = profile.contact
    name_parts = c.full_name.split(" ", 1)
    values = {
        "full_name": c.full_name,
        "first_name": name_parts[0] if name_parts else "",
        "last_name": name_parts[1] if len(name_parts) > 1 else "",
        "email": c.email,
        "phone": c.phone or "",
        "location": c.location or "",
        "linkedin": next((l for l in c.links if "linkedin" in l), ""),  # noqa: E741
        "link": next((l for l in c.links if "linkedin" not in l), c.links[0] if c.links else ""),  # noqa: E741
        "availability": prefs.availability or "Available upon agreement",
        "work_auth": prefs.work_authorization or "",
    }
    return values.get(key, "")
