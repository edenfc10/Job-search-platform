"""Claude implementations of the LLM protocols (anthropic SDK, structured
outputs via messages.parse). Active only when AIJAA_FAKE_LLM=false and an API
key is configured. Judgment-heavy calls use the smart model with adaptive
thinking; extraction uses the fast model."""

from collections.abc import Awaitable, Callable

from anthropic import AsyncAnthropic
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

UsageHook = Callable[[str, str, int, int], Awaitable[None]]  # component, model, in, out

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


class ClaudeLLM:
    """Implements all LLM protocols against the Claude API."""

    def __init__(self, usage_hook: UsageHook | None = None):
        self.settings = get_settings()
        self.client = AsyncAnthropic(api_key=self.settings.anthropic_api_key or None)
        self.usage_hook = usage_hook

    async def _parse(self, component: str, model: str, system: str, prompt: str, output_format):
        response = await self.client.messages.parse(
            model=model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=output_format,
        )
        if self.usage_hook is not None:
            await self.usage_hook(
                component, model, response.usage.input_tokens, response.usage.output_tokens
            )
        return response.parsed_output

    # ------------------------------------------------------------------ intake
    async def turn(self, profile, prefs, free_text, missing_sections) -> IntakeExtraction:
        prompt = (
            f"Current profile JSON:\n{profile.model_dump_json()}\n\n"
            f"Current preferences JSON:\n{prefs.model_dump_json()}\n\n"
            f"Sections still incomplete: {missing_sections}\n\n"
            f"The candidate's new answers (free text):\n{free_text}\n\n"
            "Extract structured updates. profile_patch/preferences_patch are deep-merge "
            "patches matching the given JSON shapes; achievements become ProfileFact "
            "objects with quantified=true only when they contain a real metric. Record "
            "exactly what the candidate said — do not embellish. Then propose up to 3 "
            "next questions a great recruiter would ask, prioritizing: quantified "
            "achievements, seniority evidence, dealbreakers, salary floor, locations, "
            "work authorization."
        )
        return await self._parse(
            "intake", self.settings.model_smart, RECRUITER_PERSONA + " " + TRUTH_RULES,
            prompt, IntakeExtraction,
        )

    # ------------------------------------------------------------------ resume
    async def write(self, profile, language: str) -> ResumeIR:
        lang_rule = (
            "Write the resume in professional Hebrew (modern Israeli business register)."
            if language == "he"
            else "Write the resume in professional English."
        )
        prompt = (
            f"Profile JSON (facts carry fact_id):\n{profile.model_dump_json()}\n\n"
            f"{lang_rule}\n"
            "Produce a ResumeIR. Bullet rules: strong action verb + scope/context + "
            "quantified outcome where the cited facts provide one; no first person; no "
            "buzzword filler; every bullet MUST list the fact_ids it was written from; "
            "if facts lack a metric, write the bullet without inventing one. Summary: "
            "3 lines max, positioned for the candidate's actual seniority."
        )
        return await self._parse(
            "resume_writer", self.settings.model_smart,
            RECRUITER_PERSONA + " " + TRUTH_RULES, prompt, ResumeIR,
        )

    # ------------------------------------------------------------- jd analysis
    async def analyze(self, posting: JobPosting) -> JobRequirements:
        prompt = (
            f"Job posting: {posting.title} at {posting.company}\n\n"
            f"{posting.description_text}\n\n"
            "Extract JobRequirements: must_have vs nice_to_have requirements, hard "
            "keywords with realistic aliases/synonyms (e.g. K8s->Kubernetes), seniority "
            "signal, responsibility themes, and disqualifiers (clearance, onsite-only, "
            "licenses)."
        )
        return await self._parse(
            "jd_analysis", self.settings.model_fast,
            "You are an expert technical recruiter analyzing job descriptions.",
            prompt, JobRequirements,
        )

    # ------------------------------------------------------------------ tailor
    async def tailor(self, ir: ResumeIR, requirements: JobRequirements, profile) -> ResumeIR:
        prompt = (
            f"Master resume IR:\n{ir.model_dump_json()}\n\n"
            f"Job requirements:\n{requirements.model_dump_json()}\n\n"
            f"Profile facts (ground truth):\n{profile.model_dump_json()}\n\n"
            "Tailor the resume for this job. ALLOWED: reorder bullets/skills, rephrase "
            "bullets to use the job's terminology where the cited facts genuinely "
            "support it, tune the summary toward the role, drop irrelevant bullets. "
            "FORBIDDEN: adding any skill/tool/credential/metric the cited fact_ids do "
            "not support; keyword stuffing. Keep every bullet's fact_ids accurate."
        )
        return await self._parse(
            "tailor", self.settings.model_smart,
            RECRUITER_PERSONA + " " + TRUTH_RULES, prompt, ResumeIR,
        )

    # ------------------------------------------------------------------ rerank
    async def rerank(self, profile, prefs, postings) -> list[RerankItem]:
        items: list[RerankItem] = []
        batch_size = 8
        for i in range(0, len(postings), batch_size):
            batch = postings[i : i + batch_size]
            listing = "\n\n".join(
                f"[posting_id={p.id}] {p.title} at {p.company} ({p.location or 'n/a'})\n"
                f"{p.description_text[:2500]}"
                for p in batch
            )
            prompt = (
                f"Candidate profile:\n{profile.model_dump_json()}\n\n"
                f"Preferences:\n{prefs.model_dump_json()}\n\n"
                f"Evaluate these postings:\n{listing}\n\n"
                "For each posting return a 0-100 match score, a 2-3 sentence rationale a "
                "recruiter would write, and risks from this taxonomy: seniority_mismatch, "
                "skill_gap, location_friction, salary_unknown, ghost_posting_signals, "
                "visa_risk. Judge only from the given text — no invented company "
                "knowledge. Be strict: 70+ means you would genuinely present this job "
                "to the candidate."
            )
            result = await self._parse(
                "rerank", self.settings.model_smart, RECRUITER_PERSONA, prompt, _RerankBatch
            )
            items.extend(result.items)
        return items

    # ------------------------------------------------------------------ answers
    async def answer(self, question: str, profile, prefs) -> GeneratedAnswer:
        prompt = (
            f"Application screening question:\n{question}\n\n"
            f"Candidate profile (ground truth):\n{profile.model_dump_json()}\n\n"
            "Write a short (<=120 words), professional, truthful answer grounded ONLY in "
            "the profile facts; cite fact_ids. If the question concerns compensation, "
            "legal matters, clearances, references, or anything the profile cannot "
            "truthfully answer, set needs_human=true with a reason instead of answering."
        )
        return await self._parse(
            "answers", self.settings.model_smart,
            RECRUITER_PERSONA + " " + TRUTH_RULES, prompt, GeneratedAnswer,
        )

    # ------------------------------------------------------------- confirmation
    async def judge(self, page_text: str) -> ConfirmationJudgment:
        prompt = (
            f"Post-submission page text:\n{page_text[:6000]}\n\n"
            "Did the application submission succeed? Verdict rules: 'confirmed' only "
            "with explicit evidence (thank-you/received message, confirmation number); "
            "'unconfirmed' for explicit errors; otherwise 'ambiguous'. Quote the "
            "evidence and extract a confirmation reference if present."
        )
        return await self._parse(
            "confirmation", self.settings.model_fast,
            "You judge whether a job application submission succeeded. Be conservative.",
            prompt, ConfirmationJudgment,
        )
