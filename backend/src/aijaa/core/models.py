"""Canonical domain models — single source of truth for all data shapes."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- profile


class ProfileFact(BaseModel):
    """Atomic, ground-truth statement about the seeker. Everything generated
    downstream (bullets, answers) must cite fact_ids — the fabrication guard
    enforces it."""

    fact_id: str = Field(default_factory=new_id)
    text: str
    kind: Literal["achievement", "skill", "education", "certification", "language", "other"] = (
        "other"
    )
    quantified: bool = False


class WorkExperience(BaseModel):
    company: str
    title: str
    start: str  # YYYY-MM
    end: str | None = None  # None = present
    location: str | None = None
    achievements: list[ProfileFact] = []


class Education(BaseModel):
    institution: str
    degree: str = ""
    field: str = ""
    year: str | None = None


class Contact(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str | None = None
    location: str | None = None
    links: list[str] = []


class ProfessionalProfile(BaseModel):
    seeker_id: str
    version: int = 1
    contact: Contact = Contact()
    work_history: list[WorkExperience] = []
    education: list[Education] = []
    skills: list[ProfileFact] = []
    certifications: list[ProfileFact] = []
    languages: list[str] = []
    summary_notes: str = ""
    updated_at: datetime = Field(default_factory=utcnow)

    def all_facts(self) -> dict[str, ProfileFact]:
        facts: dict[str, ProfileFact] = {}
        for exp in self.work_history:
            for f in exp.achievements:
                facts[f.fact_id] = f
        for f in [*self.skills, *self.certifications]:
            facts[f.fact_id] = f
        return facts


class CareerPreferences(BaseModel):
    seeker_id: str
    target_titles: list[str] = []
    seniority: str | None = None
    industries: list[str] = []
    locations: list[str] = []
    remote_policy: Literal["remote", "hybrid", "onsite", "any"] = "any"
    min_salary: int | None = None
    currency: str = "USD"
    work_authorization: str | None = None
    dealbreakers: list[str] = []
    availability: str | None = None
    resume_languages: list[Literal["en", "he"]] = ["en"]


# ------------------------------------------------------------------------ discovery


class Keyword(BaseModel):
    term: str
    aliases: list[str] = []
    must_have: bool = False


class JobRequirements(BaseModel):
    must_have: list[str] = []
    nice_to_have: list[str] = []
    keywords: list[Keyword] = []
    seniority: str | None = None
    responsibilities: list[str] = []
    disqualifiers: list[str] = []


class JobPosting(BaseModel):
    id: str = Field(default_factory=new_id)
    source: str
    canonical_url: str
    apply_url: str = ""
    company: str
    title: str
    location: str | None = None
    remote: bool | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = None
    description_text: str = ""
    requirements: JobRequirements | None = None
    posted_at: datetime | None = None
    posted_at_inferred: bool = False
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    content_hash: str = ""


# -------------------------------------------------------------------------- matching


class MatchResult(BaseModel):
    id: str = Field(default_factory=new_id)
    seeker_id: str
    posting_id: str
    vector_score: float = 0.0
    rerank_score: int = 0  # 0-100; < settings.match_floor is withheld
    rationale: str = ""
    risks: list[str] = []
    status: Literal["pending", "approved", "rejected"] = "pending"
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------- resume


class ResumeDocument(BaseModel):
    id: str = Field(default_factory=new_id)
    seeker_id: str
    kind: Literal["master", "tailored"] = "master"
    language: Literal["en", "he"] = "en"
    profile_version: int = 0
    posting_id: str | None = None
    ir: dict = {}  # ResumeIR dump (resume/ir.py)
    artifacts: dict[str, str] = {}  # format -> path
    ats_score_before: int | None = None
    ats_score_after: int | None = None
    created_at: datetime = Field(default_factory=utcnow)


# ----------------------------------------------------------------------- application


class Evidence(BaseModel):
    kind: str  # screenshot | confirmation_ref | email | note | review_packet | dry_run
    value: str
    captured_at: datetime = Field(default_factory=utcnow)


class ApplicationRecord(BaseModel):
    id: str = Field(default_factory=new_id)
    seeker_id: str
    posting_id: str
    match_id: str
    resume_id: str | None = None
    status: str = "discovered"
    plan: dict | None = None  # ApplicationPlan dump (application/analyzer.py)
    evidence: list[Evidence] = []
    needs_human_reason: str | None = None
    pending_questions: list[dict] = []
    human_answers: dict[str, str] = {}
    confirmation_ref: str | None = None
    submitted_at: datetime | None = None
    timeline: list[dict] = []
    created_at: datetime = Field(default_factory=utcnow)
