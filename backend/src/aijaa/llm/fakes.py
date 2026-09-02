"""Deterministic fake LLMs. Default implementations (AIJAA_FAKE_LLM=true):
the whole pipeline runs end-to-end with zero API usage — used by tests, demos,
and QA. Claude implementations (llm/claude.py) swap in per-protocol."""

import re

from aijaa.core.models import (
    CareerPreferences,
    JobPosting,
    JobRequirements,
    Keyword,
    ProfessionalProfile,
)
from aijaa.llm.base import (
    ConfirmationJudgment,
    GeneratedAnswer,
    IntakeExtraction,
    NextQuestion,
    RerankItem,
)
from aijaa.resume.ir import ResumeIR, base_ir_from_profile

_SECTION_QUESTIONS = {
    "contact": NextQuestion(
        question="What is your full name, email, and current location?",
        why_it_matters="Applications cannot be submitted without contact details.",
        section="contact",
    ),
    "work_history": NextQuestion(
        question=(
            "Walk me through your most recent role: company, title, dates, and 2-3 "
            "achievements with concrete numbers (revenue, users, percentages, team size)."
        ),
        why_it_matters="Quantified achievements are what recruiters and ATS score highest.",
        section="work_history",
    ),
    "skills": NextQuestion(
        question="List your strongest technical and professional skills (aim for 8-12).",
        why_it_matters="Skills drive both job matching and ATS keyword coverage.",
        section="skills",
    ),
    "education": NextQuestion(
        question="What degrees or certifications do you hold, from which institutions?",
        why_it_matters="Many postings hard-filter on education and certifications.",
        section="education",
    ),
    "preferences": NextQuestion(
        question=(
            "What roles are you targeting, in which locations (or remote), what is your "
            "minimum salary, and do you have work authorization constraints?"
        ),
        why_it_matters="These are hard filters — without them we cannot curate matches.",
        section="preferences",
    ),
    "links": NextQuestion(
        question="Share links worth showing (LinkedIn, GitHub, portfolio).",
        why_it_matters="Links strengthen credibility and some forms require them.",
        section="links",
    ),
}

_GENERIC_ROLE_TOKENS = {
    "assistant",
    "director",
    "head",
    "lead",
    "manager",
    "officer",
    "professional",
    "senior",
    "specialist",
}

_TOKEN_RE = re.compile(r"[^\W_][\w+#./&-]*", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


class FakeIntakeLLM:
    """Applies structured patches as-is; free text lands in summary_notes.
    Next questions come from the rubric's missing sections."""

    async def turn(self, profile, prefs, free_text, missing_sections) -> IntakeExtraction:
        patch: dict = {}
        if free_text.strip():
            joined = (profile.summary_notes + "\n" + free_text).strip()
            patch["summary_notes"] = joined
        questions = [
            _SECTION_QUESTIONS[s] for s in missing_sections if s in _SECTION_QUESTIONS
        ][:3]
        return IntakeExtraction(profile_patch=patch, next_questions=questions)


class FakeResumeLLM:
    """Verbatim-fact resume: bullets are the achievement facts themselves."""

    async def write(self, profile: ProfessionalProfile, language: str) -> ResumeIR:
        ir = base_ir_from_profile(profile, language)
        titles = [e.title for e in profile.work_history[:2]]
        top_skills = ", ".join(s.text for s in profile.skills[:5])
        if titles:
            ir.summary = f"{' / '.join(dict.fromkeys(titles))} with expertise in {top_skills}."
        return ir


_TECH_VOCAB = {
    "python", "java", "javascript", "typescript", "react", "node", "go", "rust", "sql",
    "postgres", "mysql", "mongodb", "redis", "aws", "gcp", "azure", "docker", "kubernetes",
    "terraform", "ci/cd", "graphql", "rest", "api", "ml", "ai", "llm", "etl", "spark",
    "kafka", "salesforce", "hubspot", "seo", "sem", "crm", "figma", "excel", "tableau",
    "powerbi", "agile", "scrum", "devops", "microservices", "django", "fastapi", "flask",
}

_ALIASES = {
    "kubernetes": ["k8s"], "javascript": ["js"], "typescript": ["ts"],
    "postgres": ["postgresql"], "ci/cd": ["cicd", "continuous integration"],
    "aws": ["amazon web services"], "gcp": ["google cloud"],
}


class FakeJDAnalysisLLM:
    async def analyze(self, posting: JobPosting) -> JobRequirements:
        text = posting.description_text
        toks = _tokens(text)
        keywords = []
        lowered = text.lower()
        for term in sorted(_TECH_VOCAB & toks):
            must = bool(re.search(rf"(required|must).{{0,120}}\b{re.escape(term)}\b", lowered)) or bool(
                re.search(rf"\b{re.escape(term)}\b.{{0,120}}(required|must)", lowered)
            )
            keywords.append(Keyword(term=term, aliases=_ALIASES.get(term, []), must_have=must))
        seniority = None
        for level in ("principal", "staff", "senior", "lead", "junior", "entry"):
            if level in toks:
                seniority = level
                break
        must_lines = [
            ln.strip("-• \t")
            for ln in text.splitlines()
            if re.search(r"required|must have|minimum", ln.lower()) and len(ln.strip()) > 10
        ]
        return JobRequirements(
            must_have=must_lines[:10],
            keywords=keywords,
            seniority=seniority,
            disqualifiers=[
                d for d in ("security clearance", "on-site only") if d in lowered
            ],
        )


class FakeTailorLLM:
    """Truth-safe tailoring: reorder only. Bullets and skills that overlap the
    JD keywords move up; nothing is rewritten or invented."""

    async def tailor(self, ir: ResumeIR, requirements: JobRequirements, profile) -> ResumeIR:
        tailored = ir.model_copy(deep=True)
        kw = {k.term for k in requirements.keywords} | {
            a for k in requirements.keywords for a in k.aliases
        }

        def bullet_score(b) -> int:
            return len(_tokens(b.text) & kw)

        for entry in tailored.experience:
            entry.bullets.sort(key=bullet_score, reverse=True)
        tailored.skills.sort(key=lambda s: len(_tokens(s) & kw), reverse=True)
        return tailored


class FakeRerankLLM:
    async def rerank(self, profile, prefs: CareerPreferences, postings) -> list[RerankItem]:
        seeker_toks = _tokens(
            " ".join(
                [s.text for s in profile.skills]
                + [e.title for e in profile.work_history]
                + prefs.target_titles
            )
        )
        items = []
        for p in postings:
            post_toks = _tokens(p.title + " " + p.description_text)
            meaningful_seeker = seeker_toks - _GENERIC_ROLE_TOKENS
            meaningful_post = post_toks - _GENERIC_ROLE_TOKENS
            overlap = meaningful_seeker & meaningful_post
            denom = min(max(len(meaningful_seeker), 3), 20)
            title_overlap = (
                (_tokens(p.title) - _GENERIC_ROLE_TOKENS)
                & (_tokens(" ".join(prefs.target_titles)) - _GENERIC_ROLE_TOKENS)
            )
            title_bonus = 25 if title_overlap else 0
            score = min(100, int(70 * len(overlap) / denom) + title_bonus + 10)
            risks = []
            if p.salary_min is None and p.salary_max is None:
                risks.append("salary_unknown")
            if prefs.seniority and prefs.seniority.lower() not in _tokens(p.title):
                risks.append("seniority_mismatch")
            top = sorted(overlap)[:4]
            items.append(
                RerankItem(
                    posting_id=p.id,
                    score=score,
                    rationale=(
                        f"Overlap on {', '.join(top)} and title alignment with target roles."
                        if top
                        else "Weak overlap with the seeker's profile."
                    ),
                    risks=risks,
                )
            )
        return items


class FakeAnswerLLM:
    async def answer(self, question: str, profile, prefs) -> GeneratedAnswer:
        q = question.lower()
        if any(w in q for w in ("salary", "compensation", "pay expectation")):
            return GeneratedAnswer(
                text="", needs_human=True, reason="compensation question requires human input"
            )
        if any(w in q for w in ("clearance", "criminal", "felony", "background")):
            return GeneratedAnswer(
                text="", needs_human=True, reason="legal/clearance question requires human input"
            )
        recent = profile.work_history[0] if profile.work_history else None
        if recent and recent.achievements:
            fact = recent.achievements[0]
            return GeneratedAnswer(
                text=(
                    f"In my role as {recent.title} at {recent.company}, {fact.text[0].lower()}"
                    f"{fact.text[1:]} I believe this experience is directly relevant here."
                ),
                fact_ids=[fact.fact_id],
            )
        return GeneratedAnswer(text="", needs_human=True, reason="insufficient profile facts")


# Keyword match is case-insensitive; the captured reference stays case-sensitive
# (must start with an uppercase letter or digit) so we don't grab words like "number".
_REF_RE = re.compile(
    r"(?i:reference|confirmation|application)[\s:#]*(?i:number|id|no\.?)?[\s:#]*([A-Z0-9][A-Z0-9-]{4,})"
)


class FakeConfirmationLLM:
    async def judge(self, page_text: str) -> ConfirmationJudgment:
        lowered = page_text.lower()
        markers = ("thank you for applying", "application received", "successfully submitted",
                   "application has been received", "we have received your application")
        m = _REF_RE.search(page_text)
        if any(s in lowered for s in markers):
            return ConfirmationJudgment(
                verdict="confirmed",
                confirmation_ref=m.group(1) if m else None,
                evidence=next(s for s in markers if s in lowered),
            )
        if "error" in lowered or "problem" in lowered:
            return ConfirmationJudgment(verdict="unconfirmed", evidence="error marker on page")
        return ConfirmationJudgment(verdict="ambiguous", evidence="no confirmation markers found")
