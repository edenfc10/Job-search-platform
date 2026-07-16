"""Fabrication guard — a hard gate, not a warning. Verifies that generated
resume content is traceable to profile facts."""

import re

from aijaa.core.models import ProfessionalProfile
from aijaa.resume.ir import ResumeIR

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?%?")


def _numbers(text: str) -> set[str]:
    return {n.rstrip("%").replace(",", "") for n in _NUM_RE.findall(text)}


def check_ir(ir: ResumeIR, profile: ProfessionalProfile) -> list[str]:
    """Returns violation descriptions; empty list means the IR is fact-safe."""
    facts = profile.all_facts()
    violations: list[str] = []

    for entry in ir.experience:
        for b in entry.bullets:
            if not b.fact_ids:
                violations.append(f"bullet '{b.text[:60]}' cites no facts")
                continue
            missing = [fid for fid in b.fact_ids if fid not in facts]
            if missing:
                violations.append(f"bullet '{b.text[:60]}' cites unknown fact_ids {missing}")
                continue
            cited_text = " ".join(facts[fid].text for fid in b.fact_ids)
            invented = _numbers(b.text) - _numbers(cited_text) - _numbers(entry.start or "") - _numbers(entry.end or "")
            if invented:
                violations.append(
                    f"bullet '{b.text[:60]}' introduces numbers {sorted(invented)} absent from cited facts"
                )

    profile_skill_text = " ".join(
        [f.text for f in profile.skills]
        + [f.text for f in profile.certifications]
        + [f.text for e in profile.work_history for f in e.achievements]
        + [profile.summary_notes]
    ).lower()
    for skill in ir.skills:
        if skill.lower() not in profile_skill_text:
            violations.append(f"skill '{skill}' not present in profile")
    for cert in ir.certifications:
        if cert.lower() not in profile_skill_text:
            violations.append(f"certification '{cert}' not present in profile")
    return violations


def check_answer_text(text: str, fact_ids: list[str], profile: ProfessionalProfile) -> list[str]:
    """Guard for generated screening answers (prose variant)."""
    facts = profile.all_facts()
    violations = []
    known = [fid for fid in fact_ids if fid in facts]
    if not known:
        violations.append("answer cites no known facts")
        return violations
    cited_text = " ".join(facts[fid].text for fid in known)
    invented = _numbers(text) - _numbers(cited_text)
    if invented:
        violations.append(f"answer introduces numbers {sorted(invented)} absent from cited facts")
    return violations
