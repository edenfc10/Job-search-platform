"""Deterministic ATS scorer (no LLM). Weights: keyword coverage 60 (must 3x
nice 1x), title/seniority alignment 15, section completeness 10, format
safety 15."""

import re

from pydantic import BaseModel

from aijaa.core.models import JobRequirements
from aijaa.resume.ir import ResumeIR

_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#./]{1,}")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


class KeywordHit(BaseModel):
    term: str
    must_have: bool
    hit: bool


class ATSReport(BaseModel):
    score: int
    keyword_score: float
    title_score: float
    section_score: float
    format_score: float
    keywords: list[KeywordHit]


def _ir_text(ir: ResumeIR) -> str:
    parts = [ir.summary, " ".join(ir.skills), " ".join(ir.certifications)]
    for e in ir.experience:
        parts.append(e.title)
        parts.extend(b.text for b in e.bullets)
    return " ".join(parts)


def score(ir: ResumeIR, requirements: JobRequirements, job_title: str = "") -> ATSReport:
    text_tokens = _tokens(_ir_text(ir))
    text_lower = _ir_text(ir).lower()

    hits: list[KeywordHit] = []
    weighted_hit = 0.0
    weighted_total = 0.0
    for kw in requirements.keywords:
        weight = 3.0 if kw.must_have else 1.0
        variants = [kw.term, *kw.aliases]
        hit = any(v.lower() in text_lower or v.lower() in text_tokens for v in variants)
        hits.append(KeywordHit(term=kw.term, must_have=kw.must_have, hit=hit))
        weighted_total += weight
        weighted_hit += weight if hit else 0.0
    keyword_score = 60.0 * (weighted_hit / weighted_total) if weighted_total else 45.0

    resume_titles = _tokens(" ".join(e.title for e in ir.experience))
    title_overlap = resume_titles & _tokens(job_title)
    title_score = 15.0 * min(len(title_overlap) / 2, 1.0) if job_title else 10.0
    if requirements.seniority and requirements.seniority.lower() in resume_titles:
        title_score = min(15.0, title_score + 5.0)

    sections = [bool(ir.summary), bool(ir.experience), bool(ir.skills), bool(ir.education)]
    section_score = 10.0 * sum(sections) / len(sections)

    # Format safety: the IR-based renderer is structurally ATS-safe; penalize
    # only content-level issues.
    format_score = 15.0
    if any(len(b.text) > 400 for e in ir.experience for b in e.bullets):
        format_score -= 3.0
    if not ir.contact_line:
        format_score -= 4.0
    if not ir.full_name:
        format_score -= 4.0

    total = int(round(keyword_score + title_score + section_score + format_score))
    return ATSReport(
        score=max(0, min(100, total)),
        keyword_score=round(keyword_score, 1),
        title_score=round(title_score, 1),
        section_score=round(section_score, 1),
        format_score=round(format_score, 1),
        keywords=hits,
    )
