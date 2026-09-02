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
_HEADING_ALIASES = {
    "תקציר": "summary",
    "פרופיל": "profile",
    "ניסיון": "experience",
    "ניסיון מקצועי": "experience",
    "ניסיון תעסוקתי": "experience",
    "השכלה": "education",
    "מיומנויות": "skills",
    "כישורים": "skills",
    "שפות": "languages",
    "שירות צבאי": "military service",
    "התנדבות": "volunteering",
    "הסמכות": "certifications",
    "קישורים": "links",
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
    r"\b(?P<start_year>(?:19|20)\d{2})"
    r"(?:[-/.](?P<start_month>0?[1-9]|1[0-2]))?\s*"
    r"(?:[-–—]|to)\s*"
    r"(?:(?P<end_year>(?:19|20)\d{2})"
    r"(?:[-/.](?P<end_month>0?[1-9]|1[0-2]))?"
    r"|(?P<open_end>present|current|today|היום|כיום))\b",
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
    if normalized in _SECTION_HEADINGS:
        return normalized
    return _HEADING_ALIASES.get(normalized)


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


def _dates_near(lines: list[str], start_index: int) -> tuple[str, str | None]:
    for line in lines[start_index : start_index + 3]:
        match = _YEAR_RANGE_RE.search(line)
        if match:
            start_month = (match.group("start_month") or "01").zfill(2)
            end_year = match.group("end_year")
            end_month = (match.group("end_month") or "12").zfill(2)
            end = f"{end_year}-{end_month}" if end_year else None
            return f"{match.group('start_year')}-{start_month}", end
    return "", None


def _is_role_line(line: str) -> bool:
    if line.startswith(("•", "-", "–", "—")) or _heading(line):
        return False
    lowered = line.lower()
    return any(term.lower() in lowered for term in _ROLE_WORDS)


def _split_role_line(line: str) -> tuple[str, str, str | None]:
    without_dates = _YEAR_RANGE_RE.sub("", line)
    without_dates = without_dates.replace("()", "").strip(" ()|,·-–—")
    parts = [part.strip(" ()|,·-–—") for part in re.split(r"\s*[·|]\s*", without_dates)]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        parts = [part.strip() for part in without_dates.split(",", maxsplit=1)]
    if len(parts) < 2:
        parts = [part.strip(" ()|,·-–—") for part in re.split(r"\s[-–—]\s", without_dates)]
        parts = [part for part in parts if part]
    title = parts[0] if parts else ""
    company = parts[1] if len(parts) > 1 else ""
    location = parts[2] if len(parts) > 2 else None
    title_has_role = any(term.lower() in title.lower() for term in _ROLE_WORDS)
    company_has_role = any(term.lower() in company.lower() for term in _ROLE_WORDS)
    if company_has_role and not title_has_role:
        title, company = company, title
    return title, company, location


def _achievements(lines: list[str], role_index: int, fact_start: int) -> list[dict]:
    out: list[dict] = []
    for line in lines[role_index + 1 : role_index + 16]:
        if _heading(line) or _is_role_line(line):
            break
        if line.startswith(("•", "-", "–")):
            value = line.lstrip("•-–— ")
            if value:
                out.append(
                    {
                        "fact_id": f"cv_f{fact_start + len(out)}",
                        "text": value,
                        "kind": "achievement",
                        "quantified": bool(re.search(r"\d", value)),
                    }
                )
        if len(out) >= 6:
            break
    return out


def _work_history(lines: list[str], default_location: str | None) -> list[dict]:
    experience = _section(
        lines,
        {"employment history", "experience", "work experience", "professional experience"},
    )
    search_lines = experience or lines

    history: list[dict] = []
    fact_start = 1
    for index, line in enumerate(search_lines):
        if not _is_role_line(line):
            continue
        start, end = _dates_near(search_lines, index)
        if not start:
            continue
        title, company, location = _split_role_line(line)
        if not title or not company:
            continue
        achievements = _achievements(search_lines, index, fact_start)
        fact_start += len(achievements)
        history.append(
            {
                "company": company,
                "title": title,
                "start": start,
                "end": end,
                "location": location or default_location,
                "achievements": achievements,
            }
        )
    return history


def _education(lines: list[str]) -> list[dict]:
    out: list[dict] = []
    for line in _section(lines, {"education"}):
        if not re.search(r"university|college|degree|b\.?sc|m\.?sc|llb|llm|bachelor|master|אוניברסיט|מכלל", line, re.I):
            continue
        values = [value.strip(" |") for value in line.split(",")]
        institution = next(
            (
                value
                for value in values
                if re.search(r"university|college|אוניברסיט|מכלל", value, re.I)
            ),
            "",
        )
        year_matches = re.findall(r"\b(?:19|20)\d{2}\b", line)
        degree = re.search(
            r"\b(?:LLB|LLM|B\.?Sc\.?|M\.?Sc\.?|BA|MA|Bachelor|Master)\b[^,;]*",
            line,
            re.I,
        )
        degree_value = degree.group(0).strip() if degree else ""
        degree_part = next((value for value in values if degree_value in value), "")
        institution_index = values.index(institution) if institution in values else -1
        degree_index = values.index(degree_part) if degree_part in values else -1
        field_parts = [
            value
            for value in values[degree_index + 1 : institution_index]
            if value and not re.fullmatch(r"(?:19|20)\d{2}", value)
        ]
        out.append(
            {
                "institution": institution,
                "degree": degree_value,
                "field": ", ".join(field_parts),
                "year": year_matches[-1] if year_matches else None,
            }
        )
        if len(out) >= 3:
            break
    return out


def _target_titles(text: str, current_title: str) -> list[str]:
    targets: list[str] = []
    preference_line = re.search(r"(?:preferences?|target roles?)\s*:\s*([^\n,]+)", text, re.I)
    if preference_line:
        for value in re.split(r"\s+(?:or|או)\s+", preference_line.group(1), flags=re.I):
            value = value.strip()
            if any(term.lower() in value.lower() for term in _ROLE_WORDS):
                targets.append(value)
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


def _minimum_salary(text: str) -> int | None:
    match = re.search(
        r"(?:minimum salary|min(?:imum)? salary|salary expectation|שכר מינימלי|ציפיות שכר)"
        r"\D{0,20}(\d[\d, ]{3,})",
        text,
        re.I,
    )
    if not match:
        return None
    return int(re.sub(r"\D", "", match.group(1)))


def interpret_local_cv(text: str) -> LocalInterpretation:
    lines = _clean_lines(text)
    email = _EMAIL_RE.search(text)
    phone = _PHONE_RE.search(text)
    links = [match.rstrip("),.;") for match in _URL_RE.findall(text)]
    locations = _locations(text)
    skills = _skills(lines, text)
    name = _candidate_name(lines)
    work_history = _work_history(lines, locations[0] if locations else None)
    title = work_history[0]["title"] if work_history else ""

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
    if not work_history:
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
        "min_salary": _minimum_salary(text),
        "currency": "ILS" if re.search(r"\bILS\b|₪|Israel|ישראל", text, re.I) else "USD",
        "work_authorization": (
            "Explicitly stated in CV"
            if re.search(r"citizen|authorized to work|work authori[sz]ation|אזרחות|מורשה לעבוד", text, re.I)
            else None
        ),
        "dealbreakers": (
            ["gambling"]
            if re.search(
                r"(?:avoid|exclude|dealbreakers?|do not want|לא מעוניינ|להימנע)[^.\n]{0,50}gambling",
                text,
                re.I,
            )
            else []
        ),
        "resume_languages": ["en", "he"] if "Hebrew" in languages else ["en"],
    }
    return LocalInterpretation(profile_patch, preferences_patch, warnings)
