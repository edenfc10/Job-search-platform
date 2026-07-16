"""LLM protocol layer. Every judgment-heavy component talks to an interface;
implementations are deterministic fakes (default — zero API usage) or Claude
(llm/claude.py). Tests use fakes only."""

from typing import Literal, Protocol

from pydantic import BaseModel

from aijaa.core.models import (
    CareerPreferences,
    JobPosting,
    JobRequirements,
    ProfessionalProfile,
)
from aijaa.resume.ir import ResumeIR


class NextQuestion(BaseModel):
    question: str
    why_it_matters: str = ""
    section: str = "general"


class IntakeExtraction(BaseModel):
    profile_patch: dict = {}
    preferences_patch: dict = {}
    next_questions: list[NextQuestion] = []


class RerankItem(BaseModel):
    posting_id: str
    score: int  # 0-100
    rationale: str = ""
    risks: list[str] = []


class GeneratedAnswer(BaseModel):
    text: str
    fact_ids: list[str] = []
    needs_human: bool = False
    reason: str = ""


class ConfirmationJudgment(BaseModel):
    verdict: Literal["confirmed", "unconfirmed", "ambiguous"]
    confirmation_ref: str | None = None
    evidence: str = ""


class IntakeLLM(Protocol):
    async def turn(
        self,
        profile: ProfessionalProfile,
        prefs: CareerPreferences,
        free_text: str,
        missing_sections: list[str],
    ) -> IntakeExtraction: ...


class ResumeLLM(Protocol):
    async def write(self, profile: ProfessionalProfile, language: str) -> ResumeIR: ...


class JDAnalysisLLM(Protocol):
    async def analyze(self, posting: JobPosting) -> JobRequirements: ...


class TailorLLM(Protocol):
    async def tailor(
        self, ir: ResumeIR, requirements: JobRequirements, profile: ProfessionalProfile
    ) -> ResumeIR: ...


class RerankLLM(Protocol):
    async def rerank(
        self,
        profile: ProfessionalProfile,
        prefs: CareerPreferences,
        postings: list[JobPosting],
    ) -> list[RerankItem]: ...


class AnswerLLM(Protocol):
    async def answer(
        self, question: str, profile: ProfessionalProfile, prefs: CareerPreferences
    ) -> GeneratedAnswer: ...


class ConfirmationLLM(Protocol):
    async def judge(self, page_text: str) -> ConfirmationJudgment: ...
