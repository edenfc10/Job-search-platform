"""OpenAI Responses API implementation of the LLM protocols.

Active when AIJAA_LLM_PROVIDER=openai, AIJAA_FAKE_LLM=false, and
AIJAA_OPENAI_API_KEY is configured.
"""

from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI
from pydantic import BaseModel

from aijaa.core.config import get_settings
from aijaa.core.models import JobPosting, JobRequirements
from aijaa.llm.base import (
    ConfirmationJudgment,
    GeneratedAnswer,
    IntakeExtraction,
    RerankItem,
)
from aijaa.resume.ir import ResumeIR

UsageHook = Callable[[str, str, int, int], Awaitable[None]]

RECRUITER_PERSONA = (
    "You are an award-winning veteran recruiter and career coach. You are precise, "
    "honest, and you never invent facts about a candidate. Every claim you produce "
    "must be traceable to the candidate data you were given."
)

TRUTH_RULES = (
    "HARD RULES: Never assert skills, employers, dates, degrees, metrics, or "
    "authorizations that are not present in the provided profile facts. You may "
    "rephrase, reorder, and emphasize only. Cite the fact_ids you used."
)


class _RerankBatch(BaseModel):
    items: list[RerankItem]


class OpenAILLM:
    """Implements all AIJAA LLM protocols through OpenAI structured outputs."""

    def __init__(self, usage_hook: UsageHook | None = None):
        self.settings = get_settings()
        self.client = AsyncOpenAI(api_key=self.settings.openai_api_key or None)
        self.usage_hook = usage_hook

    async def _parse(self, component: str, model: str, system: str, prompt: str, text_format):
        response = await self.client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            text_format=text_format,
        )
        usage = getattr(response, "usage", None)
        if self.usage_hook is not None and usage is not None:
            await self.usage_hook(
                component,
                model,
                int(getattr(usage, "input_tokens", 0) or 0),
                int(getattr(usage, "output_tokens", 0) or 0),
            )
        return response.output_parsed

    async def turn(self, profile, prefs, free_text, missing_sections) -> IntakeExtraction:
        prompt = (
            f"Current profile JSON:\n{profile.model_dump_json()}\n\n"
            f"Current preferences JSON:\n{prefs.model_dump_json()}\n\n"
            f"Sections still incomplete: {missing_sections}\n\n"
            f"The candidate's new CV/answers:\n{free_text}\n\n"
            "Extract structured updates. profile_patch/preferences_patch are deep-merge "
            "patches matching the given JSON shapes; achievements become ProfileFact "
            "objects with fact_id values; quantified=true only when there is a real "
            "metric. Do not embellish. Propose up to 3 next questions only for material "
            "gaps."
        )
        return await self._parse(
            "intake",
            self.settings.openai_model_smart,
            RECRUITER_PERSONA + " " + TRUTH_RULES,
            prompt,
            IntakeExtraction,
        )

    async def write(self, profile, language: str) -> ResumeIR:
        lang_rule = (
            "Write the resume in professional Hebrew."
            if language == "he"
            else "Write the resume in professional English."
        )
        prompt = (
            f"Profile JSON (facts carry fact_id):\n{profile.model_dump_json()}\n\n"
            f"{lang_rule}\n"
            "Produce a ResumeIR. Every bullet MUST list supporting fact_ids. Use strong "
            "recruiter-quality wording, but never add unsupported metrics, tools, dates, "
            "degrees, employers, or authorizations."
        )
        return await self._parse(
            "resume_writer",
            self.settings.openai_model_smart,
            RECRUITER_PERSONA + " " + TRUTH_RULES,
            prompt,
            ResumeIR,
        )

    async def analyze(self, posting: JobPosting) -> JobRequirements:
        prompt = (
            f"Job posting: {posting.title} at {posting.company}\n\n"
            f"{posting.description_text}\n\n"
            "Extract JobRequirements: must_have, nice_to_have, keywords with aliases, "
            "seniority, responsibilities, and disqualifiers."
        )
        return await self._parse(
            "jd_analysis",
            self.settings.openai_model_fast,
            "You are an expert technical recruiter analyzing job descriptions.",
            prompt,
            JobRequirements,
        )

    async def tailor(self, ir: ResumeIR, requirements: JobRequirements, profile) -> ResumeIR:
        prompt = (
            f"Master resume IR:\n{ir.model_dump_json()}\n\n"
            f"Job requirements:\n{requirements.model_dump_json()}\n\n"
            f"Profile facts:\n{profile.model_dump_json()}\n\n"
            "Tailor the resume for the job. ALLOWED: reorder, rephrase with supported "
            "terminology, tune summary, and drop irrelevant bullets. FORBIDDEN: adding "
            "unsupported skills/tools/credentials/metrics. Keep bullet fact_ids accurate."
        )
        return await self._parse(
            "tailor",
            self.settings.openai_model_smart,
            RECRUITER_PERSONA + " " + TRUTH_RULES,
            prompt,
            ResumeIR,
        )

    async def rerank(self, profile, prefs, postings) -> list[RerankItem]:
        items: list[RerankItem] = []
        for i in range(0, len(postings), 8):
            batch = postings[i : i + 8]
            listing = "\n\n".join(
                f"[posting_id={p.id}] {p.title} at {p.company} ({p.location or 'n/a'})\n"
                f"{p.description_text[:2500]}"
                for p in batch
            )
            prompt = (
                f"Candidate profile:\n{profile.model_dump_json()}\n\n"
                f"Preferences:\n{prefs.model_dump_json()}\n\n"
                f"Evaluate these postings:\n{listing}\n\n"
                "For each posting return a 0-100 score, recruiter rationale, and risks "
                "from: seniority_mismatch, skill_gap, location_friction, salary_unknown, "
                "ghost_posting_signals, visa_risk. 70+ means genuinely presentable."
            )
            result = await self._parse(
                "rerank",
                self.settings.openai_model_smart,
                RECRUITER_PERSONA,
                prompt,
                _RerankBatch,
            )
            items.extend(result.items)
        return items

    async def answer(self, question: str, profile, prefs) -> GeneratedAnswer:
        prompt = (
            f"Application screening question:\n{question}\n\n"
            f"Candidate profile:\n{profile.model_dump_json()}\n\n"
            "Write a short truthful answer grounded only in profile facts and cite "
            "fact_ids. For compensation, legal, clearance, references, or unsupported "
            "questions, set needs_human=true with a reason."
        )
        return await self._parse(
            "answers",
            self.settings.openai_model_smart,
            RECRUITER_PERSONA + " " + TRUTH_RULES,
            prompt,
            GeneratedAnswer,
        )

    async def judge(self, page_text: str) -> ConfirmationJudgment:
        prompt = (
            f"Post-submission page text:\n{page_text[:6000]}\n\n"
            "Did the application submission succeed? 'confirmed' only with explicit "
            "thank-you/received/confirmation evidence; 'unconfirmed' for explicit "
            "errors; otherwise 'ambiguous'. Extract confirmation_ref if present."
        )
        return await self._parse(
            "confirmation",
            self.settings.openai_model_fast,
            "You judge whether a job application submission succeeded. Be conservative.",
            prompt,
            ConfirmationJudgment,
        )
