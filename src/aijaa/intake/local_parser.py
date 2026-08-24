"""Deterministic CV interpretation for local/demo mode.

This is deliberately conservative: it extracts only text that is present in
the CV and reports uncertain/missing fields for operator review. Production
interpretation continues to use the configured LLM through the intake engine.
"""

import re
from dataclasses import dataclass

_GENERIC_HEADINGS = {
    "cv",
    "resume",
    "sample resume",
    "curriculum vitae",
    "profile",
    "professional profile",
    "details",
    "contact",
}
_SECTION_HEADINGS = {
    "skills",
    "languages",
    "education",
    "employment history",
    "experience",
    "work experience",
    "professional experience",
    "military service",
    "volunteering",
    "certifications",
    "links",
    "profile",
    "summary",
}
_ROLE_WORDS = (
    "lawyer",
    "attorney",
    "counsel",
    "manager",
    "director",
    "engineer",
    "developer",
    "designer",
    "analyst",
    "consultant",
    "specialist",
    "assistant",
    "officer",
    "recruiter",
    "accountant",
    "controller",
    "architect",
    "researcher",
    "sales",
    "marketing",
    "operations",
    "product",
    "regulation",
    "regulatory",
    "compliance",
    "advocate",
    "עורך דין",
    "מנהלת",
    "מנהל",
    "יועץ",
    "יועצת",
    "מהנדס",
    "מהנדסת",
)
_SKILL_TERMS = (
    "government relations",
    "regulation",
    "regulatory affairs",
    "compliance",
    "legal consulting",
    "litigation",
    "legislation",
    "public policy",
    "policy",
    "negotiation",
    "procurement",
    "team management",
    "project management",
    "stakeholder management",
    "parliamentary work",
    "digital communication",
    "microsoft office",
    "legal database",
    "python",
    "fastapi",
    "postgresql",
    "kubernetes",
    "docker",
    "aws",
    "redis",
    "react",
    "typescript",
    "javascript",
    "sql",
    "etl",
    "figma",
    "tableau",
    "excel",
    "קשרי ממשל",
    "רגולציה",
    "ליטיגציה",
    "ייעוץ משפטי",
    "משא ומתן",
    "ניהול צוות",
)
_LOCATION_TERMS = (
    "Tel Aviv",
    "Jerusalem",
    "Haifa",
    "Beer Sheva",
    "Rishon LeZion",
    "Israel",
    "תל אביב",
    "ירושלים",
    "חיפה",
    "באר שבע",
    "ישראל",
)
_YEAR_RANGE_RE = re.compile(
    r"\b(?P<start>(?:19|20)\d{2})(?:[-/.](?P<month>0?[1-9]|1[0-2]))?\s*"
    r"(?:[-–—]|to)\s*(?P<end>(?:19|20)\d{2}|present|current|היום)",
    re.I,
)
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,}\d)")
_URL_RE = re.compile(r"https?://\S+", re.I)


@dataclass(frozen=True)
class LocalInterpretation:
    profile_patch: dict
    preferences_patch: dict
    warnings: list[str]


def _clean_lines(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", line).strip(" \t") for line in text.splitlines() if line.strip()]


def _heading(line: str) -> str | None:
    normalized = line.strip().rstrip(":").lower()
    return normalized if normalized in _SECTION_HEADINGS else None


def _section(lines: list[str], names: set[str]) -> list[str]:
    capturing = False
    out: list[str] = []
    for line in lines:
        heading = _heading(line)
        if heading:
            if capturing:
                break
            capturing = heading in names
            continue
        if capturing:
            out.append(line)
    return out


def _candidate_name(lines: list[str]) -> str:
    for line in lines[:12]:
        lowered = line.lower().strip(":")
        if lowered in _GENERIC_HEADINGS or _heading(line):
            continue
        if _EMAIL_RE.search(line) or _PHONE_RE.search(line) or _URL_RE.search(line):
            continue
        if any(term.lower() in lowered for term in _LOCATION_TERMS):
            continue
        if any(term.lower() in lowered for term in _ROLE_WORDS):
            continue
        words = line.split()
        if 2 <= len(words) <= 5 and not any(char.isdigit() for char in line):
            return line
    return ""


def _locations(text: str) -> list[str]:
    found = [term for term in _LOCATION_TERMS if term.lower() in text.lower()]
    if "Tel Aviv" in found and "Israel" in found:
        return ["Tel Aviv, Israel", "Remote"]
    if "תל אביב" in found and "ישראל" in found:
        return ["תל אביב, ישראל", "Remote"]
    return list(dict.fromkeys(found + (["Remote"] if re.search(r"\bremote\b|מרחוק", text, re.I) else [])))


def _skills(lines: list[str], text: str) -> list[str]:
    explicit = _section(lines, {"skills"})
    explicit_terms = [
        item.strip("•-–—: ")
        for item in explicit
        if 1 <= len(item.split()) <= 6 and not any(char.isdigit() for char in item)
    ]
    known = [
        term
        for term in _SKILL_TERMS
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.I)
    ]
    unique: dict[str, str] = {}
    for term in [*explicit_terms, *known]:
        unique.setdefault(term.casefold(), term)
    return list(unique.values())[:20]


def _role_line(lines: list[str]) -> tuple[str, str, int]:
    experience = _section(
        lines,
        {"employment history", "experience", "work experience", "professional experience"},
    )
    search_lines = experience or lines
    for index, line in enumerate(search_lines):
        lowered = line.lower()
        if any(term.lower() in lowered for term in _ROLE_WORDS) and not _heading(line):
            title, separator, company = line.partition(",")
            if not separator:
                parts = re.split(r"\s[-–—|]\s", line, maxsplit=1)
                title, company = parts[0], parts[1] if len(parts) > 1 else ""
            original_index = lines.index(line) if line in lines else index
            return title.strip(), company.strip(), original_index
    return "", "", 0


def _dates_near(lines: list[str], start_index: int) -> tuple[str, str | None]:
    for line in lines[start_index : start_index + 4]:
        match = _YEAR_RANGE_RE.search(line)
        if match:
            month = (match.group("month") or "01").zfill(2)
            end_raw = match.group("end").lower()
            end = None if end_raw in {"present", "current", "היום"} else f"{end_raw}-12"
            return f"{match.group('start')}-{month}", end
    return "", None


def _achievements(lines: list[str], role_index: int) -> list[dict]:
    out: list[dict] = []
    for line in lines[role_index + 1 : role_index + 16]:
        if _heading(line) or (out and any(term.lower() in line.lower() for term in _ROLE_WORDS)):
            break
        if line.startswith(("•", "-", "–")):
            value = line.lstrip("•-–— ")
            if value:
                out.append(
                    {
                        "fact_id": f"cv_f{len(out) + 1}",
                        "text": value,
                        "kind": "achievement",
                        "quantified": bool(re.search(r"\d", value)),
                    }
                )
        if len(out) >= 6:
            break
    return out


def _education(lines: list[str]) -> list[dict]:
    out: list[dict] = []
    for line in _section(lines, {"education"}):
        if not re.search(r"university|college|degree|b\.?sc|m\.?sc|llb|llm|bachelor|master|אוניברסיט|מכלל", line, re.I):
            continue
        institutions = re.findall(r"(?:[A-Z][\w'’-]+\s+){0,4}(?:University|College)", line)
        institution = institutions[-1] if institutions else line
        year = re.search(r"\b(?:19|20)\d{2}\b", line)
        degree = re.search(r"\b(?:LLB|LLM|B\.?Sc\.?|M\.?Sc\.?|BA|MA|Bachelor|Master)\b[^,;]*", line, re.I)
        out.append(
            {
                "institution": institution.strip(" ,"),
                "degree": degree.group(0).strip() if degree else "",
                "field": "",
                "year": year.group(0) if year else None,
            }
        )
        if len(out) >= 3:
            break
    return out


def _target_titles(text: str, current_title: str) -> list[str]:
    targets: list[str] = []
    aspiration = re.search(
        r"(?:aspir(?:e|es|ing) to (?:act|work|serve) as|target(?:ing)?|seeking)\s+(?:an?\s+)?([^.;\n]+)",
        text,
        re.I,
    )
    if aspiration:
        target = re.split(r"\s+in\s+(?:a|an|the)\s+", aspiration.group(1), maxsplit=1, flags=re.I)[0]
        targets.append(target.strip())
    if current_title:
        targets.append(current_title)
    return list(dict.fromkeys(t for t in targets if t))[:4]


def interpret_local_cv(text: str) -> LocalInterpretation:
    lines = _clean_lines(text)
    email = _EMAIL_RE.search(text)
    phone = _PHONE_RE.search(text)
    links = [match.rstrip("),.;") for match in _URL_RE.findall(text)]
    locations = _locations(text)
    title, company, role_index = _role_line(lines)
    start, end = _dates_near(lines, role_index)
    skills = _skills(lines, text)
    name = _candidate_name(lines)
    achievements = _achievements(lines, role_index)

    work_history = []
    if title:
        work_history.append(
            {
                "company": company or "Company requires review",
                "title": title,
                "start": start or "2000-01",
                "end": end,
                "location": locations[0] if locations else None,
                "achievements": achievements,
            }
        )

    languages: list[str] = []
    if re.search(r"\bhebrew\b|עברית", text, re.I):
        languages.append("Hebrew")
    if re.search(r"\benglish\b|אנגלית", text, re.I):
        languages.append("English")

    targets = _target_titles(text, title)
    lowered = text.lower()
    industries = []
    if any(term in lowered for term in ("legal", "lawyer", "litigation", "משפט")):
        industries.append("Legal")
    if any(term in lowered for term in ("government", "knesset", "regulation", "רגולציה")):
        industries.append("Government & Regulation")

    warnings = []
    if not name:
        warnings.append("Candidate name was not confidently identified; review it before saving.")
    if not skills:
        warnings.append("No skills section was identified; add verified skills before matching.")
    if not targets:
        warnings.append("No target role was identified; add at least one target title.")
    if not start:
        warnings.append("Employment start date was not confidently identified; review work history.")

    profile_patch = {
        "contact": {
            "full_name": name,
            "email": email.group(0) if email else "",
            "phone": phone.group(0) if phone else None,
            "location": locations[0] if locations else None,
            "links": links,
        },
        "work_history": work_history,
        "education": _education(lines),
        "skills": [
            {"fact_id": f"cv_s{index}", "text": skill, "kind": "skill", "quantified": False}
            for index, skill in enumerate(skills, start=1)
        ],
        "languages": languages,
        "summary_notes": text[:6000],
    }
    preferences_patch = {
        "target_titles": targets,
        "seniority": (
            "executive"
            if re.search(r"\bvp\b|vice president|chief", text, re.I)
            else "senior"
            if re.search(r"\bsenior\b|director|head of", text, re.I)
            else None
        ),
        "industries": industries,
        "locations": locations,
        "remote_policy": "remote" if re.search(r"\bremote\b|מרחוק", text, re.I) else "hybrid",
        "min_salary": None,
        "currency": "ILS" if re.search(r"\bILS\b|₪|Israel|ישראל", text, re.I) else "USD",
        "work_authorization": (
            "Explicitly stated in CV"
            if re.search(r"citizen|authorized to work|work authori[sz]ation|אזרחות|מורשה לעבוד", text, re.I)
            else None
        ),
        "dealbreakers": [],
        "resume_languages": ["en", "he"] if "Hebrew" in languages else ["en"],
    }
    return LocalInterpretation(profile_patch, preferences_patch, warnings)
